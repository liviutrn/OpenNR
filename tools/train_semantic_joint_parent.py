"""Joint causal-parent adaptation versus the matched frozen-parent semantic control."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from evaluate_temporal_cohorts import named_path
from semantic_tone_head import load_semantic_warm_head, encoder_provenance
from prepare_conditioning_pilot import save, sha
from joint_parent_tone_model import JointParentToneModel
from train_capacity_temporal_student import _load_parent
from train_temporal_student import StrictTemporalCache, _device_batch, evaluate_streaming
from train_spatial_tone import frame_objective


def cohort(path, split):
    metadata = json.loads((path / 'complete.json').read_text())
    if metadata.get('teacher_pass_count', 1) != 1:
        raise ValueError('Only ordinary 1x teacher data is allowed')
    if metadata['schema'] in ('opennr-aligned-native-guide-overlay-v1', 'opennr-aligned-renderer-pilot-v1'):
        return AlignedCohort(path, split)
    cache = StrictTemporalCache(path, split)
    if any(r.get('pass_count', 1) != 1 for r in cache.rows):
        raise ValueError('Non-1x row in strict cache')
    return cache


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--warm-head', type=Path, required=True)
    p.add_argument('--cohort', action='append', type=named_path, required=True)
    p.add_argument('--probabilities', type=float, nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--parent-learning-rate', type=float, default=1e-5)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--steps', type=int, default=400)
    p.add_argument('--seed', type=int, default=367)
    p.add_argument('--learning-rate', type=float, default=1e-4)
    p.add_argument('--eval-every', type=int, default=400)
    p.add_argument('--pixel-only', action='store_true',
                   help='Optimize ordinary per-pixel L1 only; omit pooled and temporal terms.')
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    if len(a.cohort) != len(a.probabilities) or any(v < 0 for v in a.probabilities) or not np.isclose(sum(a.probabilities), 1):
        raise ValueError('Cohort probability mismatch')
    if a.steps < 1 or a.eval_every < 1 or a.learning_rate <= 0 or a.parent_learning_rate <= 0:
        raise ValueError('Positive steps, evaluation interval and LR required')
    if len({name for name, _ in a.cohort}) != len(a.cohort):
        raise ValueError('Duplicate cohort label')
    verified = json.loads((a.warm_head.parent / 'checkpoint_verification.json').read_text())
    if sha(a.warm_head) != verified['sha256']:
        raise ValueError('Warm head is not the verified checkpoint')
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.manual_seed(a.seed)
    torch.cuda.manual_seed_all(a.seed)
    torch.backends.cudnn.benchmark = False
    rng = np.random.default_rng(a.seed)
    labels = [name for name, _ in a.cohort]
    train = [cohort(path, 'train') for _, path in a.cohort]
    validation = [cohort(path, 'validation') for _, path in a.cohort]
    memberships = {}
    for cache in train + validation:
        for row in cache.rows:
            seq, split = row['sequence_id'], row['split']
            if seq in memberships and memberships[seq] != split:
                raise ValueError('Cross-cohort split leakage')
            memberships[seq] = split
    for datasets in (train, validation):
        seqs = [seq for cache in datasets for seq in cache.sequence_ids]
        if len(seqs) != len(set(seqs)):
            raise ValueError('Duplicate sequences across cohorts')
    head, warm = load_semantic_warm_head(a.warm_head, True)
    parent_path = Path(warm['run']['parent'])
    if sha(parent_path) != warm['run']['parent_sha256']:
        raise ValueError('Frozen parent identity changed')
    parent, *_ = _load_parent(parent_path)
    model = JointParentToneModel(parent, head)
    scientific = {'warm_head': str(a.warm_head.resolve()), 'warm_head_sha256': sha(a.warm_head),
                  'parent': str(parent_path.resolve()), 'parent_sha256': sha(parent_path),
                  'cohorts': [str(path.resolve()) for _, path in a.cohort], 'cohort_labels': labels,
                  'cohort_complete_sha256': [sha(path / 'complete.json') for _, path in a.cohort],
                  'probabilities': a.probabilities, 'seed': a.seed, 'steps': a.steps,
                  'learning_rate': a.learning_rate, 'eval_every': a.eval_every, 'window': 8,
                  'burn_in': 2, 'batch': 1,
                  'loss': 'L1' if a.pixel_only else 'L1 + .5 pooled16 RGB L1 + .12 temporal error delta',
                  'pixel_only': bool(a.pixel_only),
                  'training_sequences': [c.sequence_ids for c in train],
                  'validation_sequences': [c.sequence_ids for c in validation], 'test_used': False}
    run = dict(scientific, pretrained_encoder=True,
               head_parameters=sum(p.numel() for p in head.parameters()),
               source_sha256={name: sha(Path(__file__).with_name(name)) for name in
                   ('train_semantic_joint_parent.py', 'joint_parent_tone_model.py', 'semantic_tone_head.py',
                    'train_capacity_temporal_student.py', 'capacity_temporal_student.py', 'temporal_student.py',
                    'capacity_student.py', 'student_v2.py', 'student_v3.py', 'student_v4.py', 'opennr_student.py',
                    'stable_oversized_tone_head.py', 'oversized_tone_head.py', 'spatial_tone_head.py')})
    run['joint_parent'] = True
    run['parent_learning_rate'] = a.parent_learning_rate
    run['trainable_parent_parameters'] = sum(p.numel() for p in parent.parameters() if p.requires_grad)
    run['encoder_provenance'] = encoder_provenance()
    run['trainable_head_parameters'] = sum(p.numel() for p in head.parameters() if p.requires_grad)
    control_history = None
    if a.control:
        cr = json.loads((a.control / 'run.json').read_text())
        if json.loads((a.control / 'status.json').read_text())['state'] != 'complete':
            raise ValueError('Control incomplete')
        for key, value in scientific.items():
            if cr[key] != value:
                raise ValueError('Control differs: ' + key)
        if not cr['pretrained_encoder'] or cr.get('projection_only') or cr.get('joint_parent'):
            raise ValueError('Control must use a pretrained encoder, train the full head and freeze the parent')
        control_history = {r['step']: r for r in json.loads((a.control / 'history.json').read_text())}
        run['control'] = str(a.control.resolve())
        run['control_history_sha256'] = sha(a.control / 'history.json')
    save(a.output / 'run.json', run)
    optimizer = torch.optim.AdamW([{'params': [p for p in head.parameters() if p.requires_grad], 'lr': a.learning_rate},
                                  {'params': list(parent.parameters()), 'lr': a.parent_learning_rate}], weight_decay=1e-4)
    history = []
    digest = hashlib.sha256()
    draws = {label: 0 for label in labels}
    started = time.time()
    baseline = None
    best = 1.0

    def checkpoint(name, step, metrics):
        tmp = a.output / (name + '.tmp')
        torch.save({'architecture': 'semantic_joint_parent_v1', 'head': head.state_dict(),
                    'parent_model': parent.state_dict(), 'run': run, 'step': step, 'validation': metrics,
                    'optimizer': optimizer.state_dict(), 'numpy_rng_state': rng.bit_generator.state,
                    'torch_rng_state': torch.get_rng_state(), 'cuda_rng_state': torch.cuda.get_rng_state_all()}, tmp)
        tmp.replace(a.output / name)

    def evaluate(step):
        nonlocal baseline, best
        metrics = {}
        for label, cache in zip(labels, validation):
            save(a.output / 'status.json', {'state': 'evaluating', 'step': step, 'cohort': label})
            metrics[label] = evaluate_streaming(model, cache, batch=4)
            print(json.dumps({'step': step, 'cohort': label, 'mae': metrics[label]['mae']}), flush=True)
        if baseline is None:
            baseline = metrics
        if control_history is not None:
            reference = control_history[step]
            if reference['sample_sha256'] != digest.hexdigest() or reference['draws'] != draws:
                raise ValueError('Matched sample schedule diverged')
            if step == 0:
                differences = {label: {k: abs(metrics[label][k] - reference['validation'][label][k])
                               for k in ('mae', 'psnr', 'temporal_delta_mae')} for label in labels}
                if any(v > 1e-7 for d in differences.values() for v in d.values()):
                    raise ValueError('Step-zero control identity failed: ' + str(differences))
                save(a.output / 'step_zero_replay.json', differences)
        ratios = [metrics[label]['mae'] / baseline[label]['mae'] for label in labels]
        eligible = all(r < 1 for r in ratios)
        history.append({'step': step, 'validation': metrics, 'ratios': ratios,
                        'all_cohorts_improved': eligible, 'sample_sha256': digest.hexdigest(),
                        'draws': dict(draws), 'seconds': time.time() - started})
        save(a.output / 'history.json', history)
        if step == 0 or (eligible and np.mean(ratios) < best):
            if step:
                best = float(np.mean(ratios))
            checkpoint('best_all_cohorts.pt', step, metrics)
        checkpoint('last.pt', step, metrics)

    try:
        evaluate(0)
        for step in range(1, a.steps + 1):
            index = int(rng.choice(len(train), p=a.probabilities))
            _, _, ids = train[index].sample_window(rng, 1, 8)
            digest.update(np.asarray([index], dtype='<i8').tobytes())
            digest.update(np.asarray(ids, dtype='<i8').tobytes())
            rgb, target, guides, context = _device_batch(train[index].load_window(ids))
            rgb, target = rgb.float() / 255, target.float() / 255
            guides, context = guides.float(), context.float()
            model.train()
            optimizer.zero_grad(set_to_none=True)
            state = None
            previous = None
            losses = []
            for frame in range(8):
                with torch.set_grad_enabled(frame >= 2), torch.autocast('cuda', dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                    error = pred.float() - target[:, frame]
                    if frame >= 2:
                        losses.append(frame_objective(error, previous, a.pixel_only))
                    previous = error if frame >= 2 else error.detach()
            loss = torch.stack(losses).mean()
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite training loss')
            loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(), 1, error_if_nonfinite=True)
            torch.nn.utils.clip_grad_norm_(parent.parameters(), 1, error_if_nonfinite=True)
            optimizer.step()
            draws[labels[index]] += 1
            if step == 1 or step % 25 == 0:
                status = {'state': 'training', 'step': step, 'steps': a.steps,
                          'loss': float(loss.detach()), 'seconds': time.time() - started,
                          'gpu_peak_gib': torch.cuda.max_memory_allocated() / 2**30}
                save(a.output / 'status.json', status)
                print(json.dumps(status), flush=True)
            if step % a.eval_every == 0 or step == a.steps:
                evaluate(step)
        save(a.output / 'status.json', {'state': 'complete', 'steps': a.steps, 'best_ratio': best,
                                      'test_used': False, 'seconds': time.time() - started})
    except Exception as exc:
        save(a.output / 'status.json', {'state': 'failed', 'error': repr(exc)})
        raise


if __name__ == '__main__':
    main()
