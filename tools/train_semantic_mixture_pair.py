"""Paired cohort-mixture ablation from a verified joint-parent checkpoint."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
import torch

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_parent_replication import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming
from continue_semantic_parent_training import replay_schedule


ORIGINAL_PROBABILITIES = [0.40, 0.15, 0.10, 0.15, 0.10, 0.10]
REBALANCED_PROBABILITIES = [0.25, 0.10, 0.10, 0.15, 0.20, 0.20]


def load_arm(payload, old):
    parent, *_ = _load_parent(Path(old['parent']))
    parent.load_state_dict(payload['parent_model'], strict=True)
    head = SemanticToneHead(False).cuda()
    head.load_state_dict(payload['head'], strict=True)
    model = JointParentToneModel(parent, head)
    optimizer = torch.optim.AdamW([
        {'params': [v for v in head.parameters() if v.requires_grad], 'lr': old['learning_rate']},
        {'params': list(parent.parameters()), 'lr': old['parent_learning_rate']}], weight_decay=1e-4)
    optimizer.load_state_dict(payload['optimizer'])
    torch.set_rng_state(payload['torch_rng_state'].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in payload['cuda_rng_state']])
    return model, parent, head, optimizer


def run_arm(payload, resume_history, train, validation, labels, probabilities, output, steps, control=False):
    old = payload['run']; start = int(payload['step'])
    model, parent, head, optimizer = load_arm(payload, old)
    rng = np.random.default_rng()
    rng.bit_generator.state = payload['numpy_rng_state']
    digest = hashlib.sha256(); draws = {label: 0 for label in labels}
    if control:
        replay_rng, replay_digest, replay_draws = replay_schedule(train, old['probabilities'], old['seed'], start, labels)
        if replay_digest.hexdigest() != resume_history[-1]['sample_sha256'] or replay_draws != resume_history[-1]['draws']:
            raise ValueError('Original control predecessor schedule mismatch')
        if replay_rng.bit_generator.state != payload['numpy_rng_state']:
            raise ValueError('Original control predecessor RNG mismatch')
    baseline = next(row['validation'] for row in resume_history if row['step'] == 0)
    run = dict(old, architecture='semantic_joint_parent_mixture_v1', steps=steps,
               continuation_start_step=start, resume=str(args_resume.resolve()), resume_sha256=sha(args_resume),
               mixture_probabilities=probabilities, mixture_role='original_control' if control else 'renderer_state_new_pairs_rebalanced',
               trainer_source_sha256=sha(Path(__file__)), optimizer_restored=True, rng_restored=True,
               test_used=False)
    output.mkdir(parents=True)
    save(output / 'run.json', run)
    save(output / 'resume_verification.json', {'resume_sha256': sha(args_resume), 'step': start,
         'numpy_rng_restored': True, 'torch_cuda_rng_restored': True, 'test_used': False,
         'future_sample_schedule': 'restored predecessor RNG; probabilities intentionally set by mixture arm'})
    history = []; started = time.time()

    def checkpoint(name, step, metrics):
        torch.save({'architecture': run['architecture'], 'head': head.state_dict(), 'parent_model': parent.state_dict(),
                    'run': run, 'step': step, 'validation': metrics, 'optimizer': optimizer.state_dict(),
                    'numpy_rng_state': rng.bit_generator.state, 'torch_rng_state': torch.get_rng_state(),
                    'cuda_rng_state': torch.cuda.get_rng_state_all(), 'common_start_validation': baseline,
                    'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}, output / (name + '.tmp'))
        (output / (name + '.tmp')).replace(output / name)

    def evaluate(step):
        metrics = {}
        for label, cache in zip(labels, validation):
            save(output / 'status.json', {'state': 'evaluating', 'step': step, 'cohort': label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        if step == start:
            differences = {label: {key: abs(metrics[label][key] - payload['validation'][label][key]) for key in ('mae', 'psnr', 'temporal_delta_mae', 'first_frame_mae')} for label in labels}
            if any(v > 1e-7 for d in differences.values() for v in d.values()):
                raise ValueError('Mixture predecessor replay mismatch: ' + str(differences))
            save(output / 'predecessor_replay.json', {'step': step, 'differences': differences, 'test_used': False})
        ratios = [metrics[label]['mae'] / baseline[label]['mae'] for label in labels]
        eligible = all(v < 1 for v in ratios)
        history.append({'step': step, 'validation': metrics, 'ratios': ratios,
                        'all_cohorts_improved': eligible, 'sample_sha256': digest.hexdigest(),
                        'draws': dict(draws), 'seconds': time.time() - started})
        save(output / 'history.json', history)
        checkpoint('last.pt', step, metrics)
        print(json.dumps({'mixture': run['mixture_role'], 'step': step,
                          'mae': {label: values['mae'] for label, values in metrics.items()},
                          'all_cohorts_improved': eligible}), flush=True)

    evaluate(start)
    for step in range(start + 1, steps + 1):
        index = int(rng.choice(len(train), p=probabilities))
        _, _, ids = train[index].sample_window(rng, 1, 8)
        digest.update(np.asarray([index], dtype='<i8').tobytes()); digest.update(np.asarray(ids, dtype='<i8').tobytes())
        rgb, target, guides, context = _device_batch(train[index].load_window(ids))
        rgb, target = rgb.float() / 255, target.float() / 255; guides, context = guides.float(), context.float()
        model.train(); optimizer.zero_grad(set_to_none=True); state = previous = None; losses = []
        for frame in range(8):
            with torch.set_grad_enabled(frame >= 2), torch.autocast('cuda', dtype=torch.bfloat16):
                pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                error = pred.float() - target[:, frame]
                if frame >= 2: losses.append(frame_objective(error, previous))
                previous = error if frame >= 2 else error.detach()
        loss = torch.stack(losses).mean()
        if not torch.isfinite(loss): raise ValueError('Nonfinite mixture loss')
        loss.backward(); torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True); torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True); optimizer.step(); draws[labels[index]] += 1
        if step == start + 1 or step % 25 == 0:
            save(output / 'status.json', {'state': 'training', 'step': step, 'steps': steps,
                 'loss': float(loss.detach()), 'seconds': time.time() - started,
                 'gpu_peak_gib': torch.cuda.max_memory_allocated() / 2**30})
        if step == steps: evaluate(step)
    save(output / 'status.json', {'state': 'complete', 'steps': steps, 'test_used': False, 'seconds': time.time() - started})
    del model, parent, head, optimizer
    torch.cuda.empty_cache()


def main():
    global args_resume
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=1600); a = p.parse_args(); args_resume = a.resume
    if a.output.exists(): raise FileExistsError(a.output)
    payload = torch.load(a.resume, map_location='cpu', weights_only=False); old = payload['run']; start = int(payload['step'])
    if payload.get('architecture') != 'semantic_joint_parent_v1' or not old.get('joint_parent') or a.steps <= start: raise ValueError('Expected joint semantic resume')
    if json.loads((a.resume.parent / 'status.json').read_text()).get('state') != 'complete': raise ValueError('Resume incomplete')
    torch.set_num_threads(4); torch.backends.cudnn.benchmark = False
    labels = old['cohort_labels']; train = [cohort(Path(root), 'train') for root in old['cohorts']]; validation = [cohort(Path(root), 'validation') for root in old['cohorts']]
    resume_history = json.loads((a.resume.parent / 'history.json').read_text())
    if [c.sequence_ids for c in train] != old['training_sequences'] or [c.sequence_ids for c in validation] != old['validation_sequences']: raise ValueError('Sequence membership changed')
    # The original arm is the control; the candidate intentionally changes only mixture probabilities.
    run_arm(payload, resume_history, train, validation, labels, ORIGINAL_PROBABILITIES, a.output / 'original_control', a.steps, True)
    run_arm(payload, resume_history, train, validation, labels, REBALANCED_PROBABILITIES, a.output / 'rebalanced_candidate', a.steps, False)
    save(a.output / 'pair.json', {'original_probabilities': ORIGINAL_PROBABILITIES, 'rebalanced_probabilities': REBALANCED_PROBABILITIES,
         'resume': str(a.resume.resolve()), 'resume_sha256': sha(a.resume), 'test_used': False,
         'control': str((a.output / 'original_control').resolve()), 'candidate': str((a.output / 'rebalanced_candidate').resolve())})
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})


if __name__ == '__main__': main()
