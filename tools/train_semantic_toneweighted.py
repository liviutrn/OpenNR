"""Matched joint-parent pilot weighting pixels by teacher-input tone change."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F

from joint_parent_tone_model import JointParentToneModel
from prepare_conditioning_pilot import save, sha
from semantic_tone_head import SemanticToneHead
from train_capacity_temporal_student import _load_parent
from train_semantic_parent_replication import cohort
from train_temporal_student import _device_batch, evaluate_streaming
from continue_semantic_parent_training import replay_schedule


def tone_weighted_objective(error, previous, target, source):
    weights = error.new_tensor([.2126, .7152, .0722])[None, :, None, None]
    change = ((target - source) * weights).sum(1, keepdim=True).abs().detach()
    pixel_weight = 1.0 + 3.0 * change
    pixel_weight = pixel_weight / pixel_weight.mean().detach().clamp_min(1e-6)
    pixel = (pixel_weight * error.abs()).mean()
    pooled = F.avg_pool2d(error, 16).abs().mean()
    temporal = (error - previous).abs().mean()
    return pixel + .5 * pooled + .12 * temporal


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume', type=Path, required=True)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--steps', type=int, default=1600)
    p.add_argument('--eval-every', type=int, default=400)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    payload = torch.load(a.resume, map_location='cpu', weights_only=False)
    if payload.get('architecture') != 'semantic_joint_parent_v1':
        raise ValueError('Expected semantic joint checkpoint')
    old = payload['run']; start_step = int(payload['step'])
    if a.steps <= start_step or a.eval_every < 1 or not old.get('joint_parent'):
        raise ValueError('Invalid pilot continuation contract')
    if json.loads((a.resume.parent / 'status.json').read_text()).get('state') != 'complete':
        raise ValueError('Resume run is not complete')
    control_run = json.loads((a.control / 'run.json').read_text())
    if json.loads((a.control / 'status.json').read_text()).get('state') != 'complete':
        raise ValueError('Matched control is not complete')
    for key in ('cohorts', 'cohort_labels', 'probabilities', 'seed', 'learning_rate',
                'window', 'burn_in', 'batch', 'training_sequences', 'validation_sequences'):
        if control_run.get(key) != old.get(key):
            raise ValueError('Control/resume mismatch: ' + key)
    torch.set_num_threads(4); torch.backends.cudnn.benchmark = False
    parent, *_ = _load_parent(Path(old['parent']))
    parent.load_state_dict(payload['parent_model'], strict=True)
    head = SemanticToneHead(False).cuda()
    head.load_state_dict(payload['head'], strict=True)
    model = JointParentToneModel(parent, head)
    labels = old['cohort_labels']
    train = [cohort(Path(root), 'train') for root in old['cohorts']]
    validation = [cohort(Path(root), 'validation') for root in old['cohorts']]
    if [c.sequence_ids for c in train] != old['training_sequences'] or [c.sequence_ids for c in validation] != old['validation_sequences']:
        raise ValueError('Sequence membership changed')
    optimizer = torch.optim.AdamW([
        {'params': [v for v in head.parameters() if v.requires_grad], 'lr': old['learning_rate']},
        {'params': list(parent.parameters()), 'lr': old['parent_learning_rate']}], weight_decay=1e-4)
    optimizer.load_state_dict(payload['optimizer'])
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
    baseline = next(r['validation'] for r in predecessor_history if r['step'] == 0)
    run = dict(old, architecture='semantic_joint_parent_toneweighted_v1', steps=a.steps,
               eval_every=a.eval_every, continuation_start_step=start_step,
               resume=str(a.resume.resolve()), resume_sha256=sha(a.resume),
               matched_control=str(a.control.resolve()), matched_control_history_sha256=sha(a.control / 'history.json'),
               trainer_source_sha256=sha(Path(__file__)), original_semantic_head_source_sha256=sha(Path(__file__).with_name('semantic_tone_head.py')),
               optimizer_restored=True, rng_restored=True,
               loss='weighted RGB L1 by 1+3*abs(teacher-input luma) + .5 pooled16 RGB L1 + .12 temporal error delta',
               tone_weight_formula='normalize per frame by mean; target/source weight detached; no inference target input')
    a.output.mkdir(parents=True)
    save(a.output / 'run.json', run)
    save(a.output / 'resume_verification.json', {'resume_sha256': sha(a.resume), 'step': start_step,
         'sample_sha256': digest.hexdigest(), 'draws': draws, 'optimizer_restored': True,
         'numpy_rng_replayed_and_restored': True, 'torch_cuda_rng_restored': True, 'test_used': False})
    history = []; started = __import__('time').time(); best = min([1.0] + [float(np.mean(r['ratios'])) for r in predecessor_history if r['all_cohorts_improved']])

    def checkpoint(name, step, metrics):
        tmp = a.output / (name + '.tmp')
        torch.save({'architecture': run['architecture'], 'head': head.state_dict(), 'parent_model': parent.state_dict(),
                    'run': run, 'step': step, 'validation': metrics, 'optimizer': optimizer.state_dict(),
                    'numpy_rng_state': rng.bit_generator.state, 'torch_rng_state': torch.get_rng_state(),
                    'cuda_rng_state': torch.cuda.get_rng_state_all(), 'common_start_validation': baseline,
                    'history_best_score': best, 'sample_sha256': digest.hexdigest(), 'draws': dict(draws)}, tmp)
        tmp.replace(a.output / name)

    def evaluate(step):
        nonlocal best
        metrics = {}
        for label, cache in zip(labels, validation):
            save(a.output / 'status.json', {'state': 'evaluating', 'step': step, 'cohort': label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
        if step == start_step:
            differences = {label: {key: abs(metrics[label][key] - payload['validation'][label][key]) for key in ('mae', 'psnr', 'temporal_delta_mae', 'first_frame_mae')} for label in labels}
            if any(v > 1e-7 for d in differences.values() for v in d.values()):
                raise ValueError('Predecessor replay mismatch: ' + str(differences))
            save(a.output / 'predecessor_replay.json', {'step': step, 'differences': differences, 'test_used': False})
        reference = control_history.get(step)
        if reference and (digest.hexdigest() != reference['sample_sha256'] or draws != reference['draws']):
            raise ValueError('Matched sample schedule diverged')
        ratios = [metrics[label]['mae'] / baseline[label]['mae'] for label in labels]
        eligible = all(v < 1 for v in ratios)
        history.append({'step': step, 'validation': metrics, 'ratios': ratios, 'all_cohorts_improved': eligible,
                        'sample_sha256': digest.hexdigest(), 'draws': dict(draws), 'seconds': __import__('time').time() - started})
        save(a.output / 'history.json', history)
        if eligible and float(np.mean(ratios)) < best:
            best = float(np.mean(ratios)); checkpoint('best_all_cohorts.pt', step, metrics)
        checkpoint('last.pt', step, metrics)
        print(json.dumps({'step': step, 'mae': {label: values['mae'] for label, values in metrics.items()}, 'all_cohorts_improved': eligible}), flush=True)

    try:
        evaluate(start_step)
        for step in range(start_step + 1, a.steps + 1):
            index = int(rng.choice(len(train), p=run['probabilities']))
            _, _, ids = train[index].sample_window(rng, 1, 8)
            digest.update(np.asarray([index], dtype='<i8').tobytes()); digest.update(np.asarray(ids, dtype='<i8').tobytes())
            rgb, target, guides, context = _device_batch(train[index].load_window(ids))
            rgb, target = rgb.float() / 255, target.float() / 255; guides, context = guides.float(), context.float()
            model.train(); optimizer.zero_grad(set_to_none=True); state = previous = None; losses = []
            for frame in range(8):
                with torch.set_grad_enabled(frame >= 2), torch.autocast('cuda', dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= 2: losses.append(tone_weighted_objective(error, previous, target[:, frame], rgb[:, frame]))
                    previous = error if frame >= 2 else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss): raise ValueError('Nonfinite tone-weighted loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True); torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True); optimizer.step(); draws[labels[index]] += 1
            if step == start_step + 1 or step % 25 == 0:
                save(a.output / 'status.json', {'state': 'training', 'step': step, 'steps': a.steps, 'loss': float(loss.detach()), 'seconds': __import__('time').time() - started, 'gpu_peak_gib': torch.cuda.max_memory_allocated() / 2**30})
            if step % a.eval_every == 0 or step == a.steps: evaluate(step)
        save(a.output / 'status.json', {'state': 'complete', 'steps': a.steps, 'best_ratio': best, 'test_used': False, 'seconds': __import__('time').time() - started})
    except Exception as exc:
        save(a.output / 'status.json', {'state': 'failed', 'error': repr(exc)}); raise


if __name__ == '__main__': main()
