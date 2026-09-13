"""Continue a completed semantic-parent run without resetting optimizer or RNG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import numpy as np
import torch
from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import save, sha
from spatial_tone_head import FrozenParentToneModel
from train_semantic_ablation import cohort
from train_spatial_tone import frame_objective
from train_temporal_student import _device_batch, evaluate_streaming


def replay_schedule(datasets, probabilities, seed, steps, labels):
    rng = np.random.default_rng(seed)
    digest = hashlib.sha256()
    draws = dict.fromkeys(labels, 0)
    for _ in range(steps):
        index = int(rng.choice(len(datasets), p=probabilities))
        _, _, ids = datasets[index].sample_window(rng, 1, 8)
        digest.update(np.asarray([index], dtype='<i8').tobytes())
        digest.update(np.asarray(ids, dtype='<i8').tobytes())
        draws[labels[index]] += 1
    return rng, digest, draws


def restore_sampling(payload, history, datasets):
    run, step = payload['run'], payload['step']
    rng, digest, draws = replay_schedule(datasets, run['probabilities'], run['seed'], step, run['cohort_labels'])
    recorded = next(row for row in history if row['step'] == step)
    if digest.hexdigest() != recorded['sample_sha256'] or draws != recorded['draws']:
        raise ValueError('Predecessor sample schedule does not reproduce')
    if rng.bit_generator.state != payload['numpy_rng_state']:
        raise ValueError('Predecessor NumPy RNG does not match replayed schedule')
    rng.bit_generator.state = payload['numpy_rng_state']
    return rng, digest, draws


def metric_differences(metrics, reference):
    differences = {label: {key: abs(values[key] - reference[label][key])
                          for key in ('mae', 'psnr', 'temporal_delta_mae', 'first_frame_mae')}
                   for label, values in metrics.items()}
    if any(value > 1e-7 for group in differences.values() for value in group.values()):
        raise ValueError('Predecessor checkpoint replay mismatch: ' + str(differences))
    return differences


def restore_optimizer_rng(optimizer, payload, restore_cuda=True):
    optimizer.load_state_dict(payload['optimizer'])
    torch.set_rng_state(payload['torch_rng_state'].cpu())
    if restore_cuda:
        torch.cuda.set_rng_state_all([value.cpu() for value in payload['cuda_rng_state']])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, required=True, help='Absolute total update count, including predecessor')
    p.add_argument('--eval-every', type=int, default=400)
    p.add_argument('--control', type=Path)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    if json.loads((a.resume.parent / 'status.json').read_text())['state'] != 'complete':
        raise ValueError('Predecessor must be complete before this continuation')
    if a.eval_every < 1:
        raise ValueError('Positive evaluation interval required')
    resume_sha = sha(a.resume)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    model, payload = load_joint_checkpoint(a.resume)
    if sha(a.resume) != resume_sha:
        raise ValueError('Predecessor changed during loading')
    old = payload['run']
    start_step = int(payload['step'])
    if a.steps <= start_step:
        raise ValueError('Total steps must extend the predecessor')
    if (old['window'], old['burn_in'], old['batch']) != (8, 2, 1):
        raise ValueError('Unsupported window contract')
    if old['loss'] != 'L1 + .5 pooled16 RGB L1 + .12 temporal error delta':
        raise ValueError('Unsupported objective')
    if bool(old['joint_parent']) != bool(a.control):
        raise ValueError('Joint continuation requires its completed frozen-parent control')
    if not old['joint_parent']:
        model = FrozenParentToneModel(model.parent, model.head)
    head, parent = model.head, model.parent
    labels = old['cohort_labels']
    train = [cohort(Path(root), 'train') for root in old['cohorts']]
    validation = [cohort(Path(root), 'validation') for root in old['cohorts']]
    if [c.sequence_ids for c in train] != old['training_sequences'] or [c.sequence_ids for c in validation] != old['validation_sequences']:
        raise ValueError('Sequence membership changed')
    previous_history = json.loads((a.resume.parent / 'history.json').read_text())
    rng, digest, draws = restore_sampling(payload, previous_history, train)
    baseline = payload.get('common_start_validation')
    if baseline is None:
        baseline = next(row['validation'] for row in previous_history if row['step'] == 0)
    best = payload.get('history_best_score', min([1.0] + [float(np.mean(row['ratios']))
                                for row in previous_history if row['all_cohorts_improved']]))
    parent_lr = old['parent_learning_rate'] if old['joint_parent'] else 0.0
    optimizer = torch.optim.AdamW([
        {'params': [v for v in head.parameters() if v.requires_grad], 'lr': old['learning_rate']},
        {'params': list(parent.parameters()), 'lr': parent_lr}], weight_decay=1e-4)
    restore_optimizer_rng(optimizer, payload)
    if [group['lr'] for group in optimizer.param_groups] != [old['learning_rate'], parent_lr]:
        raise ValueError('Restored optimizer learning rates differ')
    run = dict(old, steps=a.steps, eval_every=a.eval_every, continuation_start_step=start_step,
               resume=str(a.resume.resolve()), resume_sha256=resume_sha,
               predecessor_history_sha256=sha(a.resume.parent / 'history.json'),
               common_start_validation=baseline, optimizer_restored=True, rng_restored=True)
    run['source_sha256'] = dict(old['source_sha256'])
    run['source_sha256'][Path(__file__).name] = sha(Path(__file__))
    control_history = None
    if a.control:
        cr = json.loads((a.control / 'run.json').read_text())
        if json.loads((a.control / 'status.json').read_text())['state'] != 'complete' or cr['joint_parent']:
            raise ValueError('Completed frozen-parent control required')
        common = ('warm_head_sha256', 'parent_sha256', 'cohorts', 'cohort_labels', 'cohort_complete_sha256',
                  'probabilities', 'seed', 'steps', 'learning_rate', 'eval_every', 'window', 'burn_in',
                  'batch', 'loss', 'training_sequences', 'validation_sequences', 'continuation_start_step')
        for key in common:
            if cr[key] != run[key]:
                raise ValueError('Continued control differs: ' + key)
        metric_differences(baseline, cr['common_start_validation'])
        control_history = {row['step']: row for row in json.loads((a.control / 'history.json').read_text())}
        run['control'] = str(a.control.resolve())
        run['control_history_sha256'] = sha(a.control / 'history.json')
    a.output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_bytes = a.resume.stat().st_size
    if shutil.disk_usage(a.output.parent).free < 3 * checkpoint_bytes + 2 * 2**30:
        raise OSError('Insufficient space for continuation checkpoints; triage storage first')
    a.output.mkdir()
    save(a.output / 'run.json', run)
    previous_best = a.resume.parent / 'best_all_cohorts.pt'
    if not previous_best.is_file():
        raise FileNotFoundError('Predecessor selected checkpoint is missing')
    shutil.copyfile(previous_best, a.output / 'best_all_cohorts.pt')
    if sha(previous_best) != sha(a.output / 'best_all_cohorts.pt'):
        raise ValueError('Selected predecessor copy differs')
    save(a.output / 'resume_verification.json', {'resume_sha256': resume_sha, 'step': start_step,
         'sample_sha256': digest.hexdigest(), 'draws': draws, 'optimizer_restored': True,
         'numpy_rng_replayed_and_restored': True, 'torch_cuda_rng_restored': True,
         'selected_predecessor_sha256': sha(previous_best), 'test_used': False})
    history = []
    started = time.time()

    def checkpoint(name, step, metrics):
        if shutil.disk_usage(a.output).free < 2 * checkpoint_bytes + 512 * 2**20:
            raise OSError('Checkpoint storage reserve exhausted')
        tmp = a.output / (name + '.tmp')
        torch.save({'architecture': 'semantic_joint_parent_v1', 'head': head.state_dict(),
                    'parent_model': parent.state_dict(), 'run': run, 'step': step, 'validation': metrics,
                    'optimizer': optimizer.state_dict(), 'numpy_rng_state': rng.bit_generator.state,
                    'torch_rng_state': torch.get_rng_state(), 'cuda_rng_state': torch.cuda.get_rng_state_all(),
                    'common_start_validation': baseline, 'history_best_score': best,
                    'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}, tmp)
        tmp.replace(a.output / name)
        if name == 'last.pt':
            snapshot = a.output / f'checkpoint_{step}.pt'
            if snapshot.exists():
                raise FileExistsError('Refusing to overwrite an evaluated checkpoint: ' + str(snapshot))
            try:
                os.link(a.output / name, snapshot)
                method = 'hardlink; later last.pt writes use atomic replacement'
            except OSError:
                snapshot_tmp = snapshot.with_suffix('.pt.tmp')
                shutil.copyfile(a.output / name, snapshot_tmp)
                snapshot_tmp.replace(snapshot)
                method = 'copy'
            save(a.output / f'checkpoint_{step}_identity.json',
                 {'step': step, 'path': str(snapshot.resolve()), 'sha256': sha(snapshot), 'method': method})

    def evaluate(step):
        nonlocal best
        metrics = {}
        for label, cache in zip(labels, validation):
            save(a.output / 'status.json', {'state': 'evaluating', 'step': step, 'cohort': label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        if step == start_step:
            save(a.output / 'predecessor_replay.json', metric_differences(metrics, payload['validation']))
        if control_history is not None:
            reference = control_history[step]
            if digest.hexdigest() != reference['sample_sha256'] or draws != reference['draws']:
                raise ValueError('Continued paired sample schedule differs')
        ratios = [metrics[label]['mae'] / baseline[label]['mae'] for label in labels]
        eligible = all(value < 1 for value in ratios)
        history.append({'step': step, 'validation': metrics, 'ratios': ratios,
                        'all_cohorts_improved': eligible, 'sample_sha256': digest.hexdigest(),
                        'draws': dict(draws), 'seconds': time.time() - started})
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
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = previous = None
            losses = []
            for frame in range(8):
                with torch.set_grad_enabled(frame >= 2), torch.autocast('cuda', dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= 2:
                        losses.append(frame_objective(error, previous))
                    previous = error if frame >= 2 else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite continuation loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True)
            optimizer.step()
            draws[labels[index]] += 1
            if step == start_step + 1 or step % 25 == 0:
                save(a.output / 'status.json', {'state': 'training', 'step': step, 'steps': a.steps,
                     'loss': float(loss.detach()), 'seconds': time.time() - started,
                     'gpu_peak_gib': torch.cuda.max_memory_allocated() / 2**30})
            if step % a.eval_every == 0 or step == a.steps:
                evaluate(step)
        save(a.output / 'status.json', {'state': 'complete', 'steps': a.steps, 'best_ratio': best,
                                      'test_used': False, 'seconds': time.time() - started})
    except Exception as exc:
        save(a.output / 'status.json', {'state': 'failed', 'error': repr(exc)})
        raise


if __name__ == '__main__':
    main()
