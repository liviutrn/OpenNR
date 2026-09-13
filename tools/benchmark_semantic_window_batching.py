"""Training-window throughput and BF16 gradient parity; no inference/VR claim."""
import argparse
from pathlib import Path
import statistics
import time
import torch
from joint_parent_tone_model import JointParentToneModel, load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from semantic_window_batching import sequential_window_loss, batched_head_window_loss
from spatial_tone_head import FrozenParentToneModel
from train_semantic_ablation import cohort
from train_temporal_student import _device_batch


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--iterations', type=int, default=5)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    model, payload = load_joint_checkpoint(a.checkpoint)
    head, parent = model.head, model.parent
    dataset = cohort(Path(payload['run']['cohorts'][0]), 'train')
    sequence = dataset.sequence_ids[0]
    ids = dataset.streams[(sequence, 0)][24:32][None]
    rgb, target, guides, context = _device_batch(dataset.load_window(ids))
    inputs = (rgb.float() / 255, target.float() / 255, guides.float(), context.float())
    del rgb, target, guides, context, dataset
    report = {'scope': __doc__, 'checkpoint_sha256': sha(a.checkpoint), 'sequence': sequence,
              'eye': 0, 'frame_indices': list(range(24, 32)), 'test_used': False,
              'training_data_only': True, 'torch': torch.__version__, 'gpu': torch.cuda.get_device_name(),
              'iterations_per_block': a.iterations, 'block_order': ['sequential', 'batched', 'batched', 'sequential'],
              'source_sha256': {name: sha(Path(__file__).with_name(name)) for name in
                               ('benchmark_semantic_window_batching.py', 'semantic_window_batching.py')}, 'modes': {}}
    functions = {'sequential': sequential_window_loss, 'batched': batched_head_window_loss}
    for mode, wrapper in [('frozen_parent', FrozenParentToneModel), ('joint_parent', JointParentToneModel)]:
        model = wrapper(parent, head).train()
        head.load_state_dict(payload['head'], strict=True)
        parent.load_state_dict(payload['parent_model'], strict=True)
        reference = None
        parity = {}
        for algorithm, loss_function in functions.items():
            save(a.output / 'status.json', {'state': 'gradient_comparison', 'mode': mode, 'algorithm': algorithm})
            model.zero_grad(set_to_none=True)
            loss = loss_function(model, *inputs)
            loss.backward()
            gradients = {name: parameter.grad.detach().cpu().clone() for name, parameter in model.named_parameters()
                         if parameter.grad is not None}
            if reference is None:
                reference = gradients
                reference_loss = float(loss.detach())
            else:
                if gradients.keys() != reference.keys():
                    raise ValueError('BF16 gradient ownership differs')
                numerator = sum(float((gradients[key].double() - value.double()).square().sum()) for key, value in reference.items())
                denominator = sum(float(value.double().square().sum()) for value in reference.values())
                parity = {'loss_absolute_difference': abs(float(loss.detach()) - reference_loss),
                          'gradient_relative_l2_difference': (numerator / max(denominator, 1e-30))**.5,
                          'gradient_tensors': len(gradients)}
            del gradients, loss
        del reference
        records = []
        for block, algorithm in enumerate(report['block_order']):
            save(a.output / 'status.json', {'state': 'timing', 'mode': mode, 'algorithm': algorithm, 'block': block})
            model.zero_grad(set_to_none=True)
            head.load_state_dict(payload['head'], strict=True)
            parent.load_state_dict(payload['parent_model'], strict=True)
            optimizer = torch.optim.AdamW([{'params': [v for v in head.parameters() if v.requires_grad], 'lr': 1e-4},
                                           {'params': list(parent.parameters()), 'lr': 1e-5 if mode == 'joint_parent' else 0.}], weight_decay=1e-4)
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
            times = []
            for iteration in range(a.iterations + 2):
                torch.cuda.synchronize()
                start = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                loss = functions[algorithm](model, *inputs)
                if not torch.isfinite(loss):
                    raise ValueError('Nonfinite benchmark loss')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True)
                torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True)
                optimizer.step()
                torch.cuda.synchronize()
                if iteration >= 2:
                    times.append((time.perf_counter() - start) * 1000)
            records.append({'algorithm': algorithm, 'block': block, 'milliseconds': times,
                            'peak_allocated_gib': torch.cuda.max_memory_allocated() / 2**30})
            del optimizer, loss
        values = {name: [t for row in records if row['algorithm'] == name for t in row['milliseconds']] for name in functions}
        medians = {name: statistics.median(times) for name, times in values.items()}
        report['modes'][mode] = {'parity': parity, 'blocks': records, 'median_window_ms': medians,
                                'speedup': medians['sequential'] / medians['batched'],
                                'numerical_screen_pass': parity['loss_absolute_difference'] <= 1e-5 and parity['gradient_relative_l2_difference'] <= .01}
        save(a.output / 'result.json', report)
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})
    print({mode: {key: value for key, value in values.items() if key != 'blocks'} for mode, values in report['modes'].items()})


if __name__ == '__main__':
    main()
