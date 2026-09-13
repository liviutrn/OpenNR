"""Matched native-residual extension from a verified semantic joint checkpoint."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import torch

from aligned_cohort import AlignedCohort
from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_native_residual_tone_head import SemanticNativeResidualToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_parent_replication import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming
from continue_semantic_parent_training import replay_schedule


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume', type=Path, required=True)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=4000)
    p.add_argument('--eval-every', type=int, default=400)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    payload = torch.load(a.resume, map_location='cpu', weights_only=False)
    if payload.get('architecture') != 'semantic_joint_parent_v1':
        raise ValueError('Expected semantic joint checkpoint')
    old = payload['run']
    start_step = int(payload['step'])
    if a.steps <= start_step or a.eval_every < 1:
        raise ValueError('Continuation must extend the predecessor')
    if not old.get('joint_parent') or old.get('window') != 8 or old.get('burn_in') != 2:
        raise ValueError('Expected joint semantic continuation contract')
    if json.loads((a.resume.parent / 'status.json').read_text()).get('state') != 'complete':
        raise ValueError('Resume run is not complete')
    control_run = json.loads((a.control / 'run.json').read_text())
    if json.loads((a.control / 'status.json').read_text()).get('state') != 'complete':
        raise ValueError('Matched control is not complete')
    for key in ('cohorts', 'cohort_labels', 'probabilities', 'seed', 'learning_rate',
                'window', 'burn_in', 'batch', 'loss', 'training_sequences', 'validation_sequences'):
        if key in control_run and key in old and control_run[key] != old[key]:
            raise ValueError('Control/resume mismatch: ' + key)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    model_parent, *_ = _load_parent(Path(old['parent']))
    model_parent.load_state_dict(payload['parent_model'], strict=True)
    head = SemanticNativeResidualToneHead(pretrained=False).cuda()
    result = head.load_state_dict(payload['head'], strict=False)
    if result.unexpected_keys or set(result.missing_keys) != {'native_residual.weight', 'native_residual.bias'}:
        raise ValueError('Semantic head warm-start identity mismatch')
    model = JointParentToneModel(model_parent, head)
    labels = old['cohort_labels']
    train = [cohort(Path(root), 'train') for root in old['cohorts']]
    validation = [cohort(Path(root), 'validation') for root in old['cohorts']]
    if [c.sequence_ids for c in train] != old['training_sequences'] or [c.sequence_ids for c in validation] != old['validation_sequences']:
        raise ValueError('Sequence membership changed')
    # Restore the predecessor optimizer exactly for the original head and parent parameters,
    # then add the two new residual tensors with a fresh AdamW state.
    base_head = [v for n, v in head.named_parameters()
                 if v.requires_grad and not n.startswith('native_residual.')]
    extra = [v for n, v in head.named_parameters() if n.startswith('native_residual.')]
    parent_params = list(model_parent.parameters())
    optimizer = torch.optim.AdamW([
        {'params': base_head, 'lr': old['learning_rate']},
        {'params': parent_params, 'lr': old['parent_learning_rate']}], weight_decay=1e-4)
    optimizer.load_state_dict(payload['optimizer'])
    optimizer.add_param_group({'params': extra, 'lr': old['learning_rate']})
    predecessor_history = json.loads((a.resume.parent / 'history.json').read_text())
    predecessor_record = next(row for row in predecessor_history if row['step'] == start_step)
    rng, digest, draws = replay_schedule(train, old['probabilities'], old['seed'], start_step, labels)
    if digest.hexdigest() != predecessor_record['sample_sha256'] or draws != predecessor_record['draws']:
        raise ValueError('Predecessor sample schedule does not reproduce')
    if rng.bit_generator.state != payload['numpy_rng_state']:
        raise ValueError('Predecessor NumPy RNG does not reproduce')
    torch.set_rng_state(payload['torch_rng_state'].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in payload['cuda_rng_state']])
    control_history = {r['step']: r for r in json.loads((a.control / 'history.json').read_text())}
    if start_step not in control_history:
        raise ValueError('Control lacks matched start checkpoint')
    baseline = payload.get('common_start_validation')
    if baseline is None:
        baseline = next(r['validation'] for r in predecessor_history if r['step'] == 0)
    previous_history = predecessor_history
    inherited_best = float(payload.get('history_best_score', min([1.0] + [float(np.mean(r['ratios'])) for r in previous_history if r['all_cohorts_improved']])))
    run = dict(old, architecture='semantic_joint_parent_native_residual_v1', steps=a.steps,
               eval_every=a.eval_every, continuation_start_step=start_step,
               resume=str(a.resume.resolve()), resume_sha256=sha(a.resume),
               matched_control=str(a.control.resolve()), matched_control_history_sha256=sha(a.control / 'history.json'),
               semantic_native_residual_source_sha256=sha(Path(__file__).with_name('semantic_native_residual_tone_head.py')),
               trainer_source_sha256=sha(Path(__file__)),
               original_semantic_head_source_sha256=sha(Path(__file__).with_name('semantic_tone_head.py')),
               optimizer_restored=True, rng_restored=True, native_residual_scale=0.15,
               new_residual_parameters=sum(v.numel() for v in extra))
    a.output.mkdir(parents=True)
    checkpoint_bytes = a.resume.stat().st_size
    if torch.cuda.is_available() and a.output.parent.stat().st_ctime is None:
        raise RuntimeError('Unexpected output parent state')
    save(a.output / 'run.json', run)
    save(a.output / 'resume_verification.json', {'resume_sha256': sha(a.resume), 'step': start_step,
         'sample_sha256': digest.hexdigest(), 'draws': draws, 'optimizer_restored': True,
         'numpy_rng_replayed_and_restored': True, 'torch_cuda_rng_restored': True,
         'head_missing_keys': sorted(result.missing_keys), 'test_used': False})
    history = []
    best = inherited_best
    started = __import__('time').time()

    def checkpoint(name, step, metrics):
        tmp = a.output / (name + '.tmp')
        torch.save({'architecture': run['architecture'], 'head': head.state_dict(),
                    'parent_model': model_parent.state_dict(), 'run': run, 'step': step,
                    'validation': metrics, 'optimizer': optimizer.state_dict(),
                    'numpy_rng_state': rng.bit_generator.state, 'torch_rng_state': torch.get_rng_state(),
                    'cuda_rng_state': torch.cuda.get_rng_state_all(), 'common_start_validation': baseline,
                    'history_best_score': best, 'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}, tmp)
        tmp.replace(a.output / name)
        if name == 'last.pt':
            snapshot = a.output / f'checkpoint_{step}.pt'
            if snapshot.exists():
                raise FileExistsError('Refusing to overwrite checkpoint: ' + str(snapshot))
            try:
                os.link(a.output / name, snapshot)
                method = 'hardlink'
            except OSError:
                snapshot_tmp = snapshot.with_suffix('.pt.tmp')
                import shutil
                shutil.copyfile(a.output / name, snapshot_tmp)
                snapshot_tmp.replace(snapshot)
                method = 'copy'
            save(a.output / f'checkpoint_{step}_identity.json', {'step': step, 'path': str(snapshot.resolve()),
                 'sha256': sha(snapshot), 'method': method})

    def evaluate(step):
        nonlocal best
        metrics = {}
        for label, cache in zip(labels, validation):
            save(a.output / 'status.json', {'state': 'evaluating', 'step': step, 'cohort': label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        if step == start_step:
            differences = {label: {key: abs(metrics[label][key] - payload['validation'][label][key])
                           for key in ('mae', 'psnr', 'temporal_delta_mae', 'first_frame_mae')} for label in labels}
            if any(v > 1e-7 for d in differences.values() for v in d.values()):
                raise ValueError('Zero residual predecessor replay mismatch: ' + str(differences))
            save(a.output / 'predecessor_replay.json', {'step': step, 'differences': differences, 'test_used': False})
        if step in control_history:
            reference = control_history[step]
            if digest.hexdigest() != reference['sample_sha256'] or draws != reference['draws']:
                raise ValueError('Matched sample schedule diverged at ' + str(step))
        ratios = [metrics[label]['mae'] / baseline[label]['mae'] for label in labels]
        eligible = all(v < 1 for v in ratios)
        history.append({'step': step, 'validation': metrics, 'ratios': ratios,
                        'all_cohorts_improved': eligible, 'sample_sha256': digest.hexdigest(),
                        'draws': dict(draws), 'seconds': __import__('time').time() - started})
        save(a.output / 'history.json', history)
        if eligible and float(np.mean(ratios)) < best:
            best = float(np.mean(ratios))
            checkpoint('best_all_cohorts.pt', step, metrics)
        checkpoint('last.pt', step, metrics)
        print(json.dumps({'step': step, 'mae': {label: values['mae'] for label, values in metrics.items()},
                          'all_cohorts_improved': eligible}), flush=True)

    try:
        evaluate(start_step)
        for step in range(start_step + 1, a.steps + 1):
            index = int(rng.choice(len(train), p=run['probabilities']))
            _, _, ids = train[index].sample_window(rng, 1, 8)
            digest.update(np.asarray([index], dtype='<i8').tobytes())
            digest.update(np.asarray(ids, dtype='<i8').tobytes())
            rgb, target, guides, context = _device_batch(train[index].load_window(ids))
            rgb, target = rgb.float() / 255, target.float() / 255
            guides, context = guides.float(), context.float()
            model.train(); optimizer.zero_grad(set_to_none=True)
            state = previous = None; losses = []
            for frame in range(8):
                with torch.set_grad_enabled(frame >= 2), torch.autocast('cuda', dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= 2:
                        losses.append(frame_objective(error, previous))
                    previous = error if frame >= 2 else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite residual loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(model_parent.parameters(), 1, error_if_nonfinite=True)
            optimizer.step(); draws[labels[index]] += 1
            if step == start_step + 1 or step % 25 == 0:
                save(a.output / 'status.json', {'state': 'training', 'step': step, 'steps': a.steps,
                     'loss': float(loss.detach()), 'seconds': __import__('time').time() - started,
                     'gpu_peak_gib': torch.cuda.max_memory_allocated() / 2**30})
            if step % a.eval_every == 0 or step == a.steps:
                evaluate(step)
        save(a.output / 'status.json', {'state': 'complete', 'steps': a.steps, 'best_ratio': best,
                                      'test_used': False, 'seconds': __import__('time').time() - started})
    except Exception as exc:
        save(a.output / 'status.json', {'state': 'failed', 'error': repr(exc)})
        raise


if __name__ == '__main__':
    main()
