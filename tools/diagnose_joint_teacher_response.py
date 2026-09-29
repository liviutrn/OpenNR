"""Fixed training-frame mode/precision/bound diagnostic; no optimizer or test access."""
import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save, sha
from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
from verify_spatial_tone import load_tone_checkpoint


def correction_bound(parent, target):
    """Optimistic per-pixel bound, ignoring spatial coefficient coupling."""
    radius = .25 * parent.float().sum(1, keepdim=True) + .15
    lower = (parent.float() - radius).clamp(0, 1)
    upper = (parent.float() + radius).clamp(0, 1)
    distance = (lower - target).clamp_min(0) + (target - upper).clamp_min(0)
    return float(distance.mean()), float((distance > 0).float().mean())


def ordered_picks(sequence_ids):
    return [sequence_ids[i] for i in sorted({0, len(sequence_ids)//2, len(sequence_ids)-1})]


@torch.no_grad()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--expected-snapshot-sha256')
    parser.add_argument('--expected-snapshot-step', type=int)
    args = parser.parse_args()
    if args.snapshot and (not args.expected_snapshot_sha256 or args.expected_snapshot_step is None):
        parser.error('Snapshot requires independently recorded SHA256 and step')
    if not args.snapshot and (args.expected_snapshot_sha256 or args.expected_snapshot_step is not None):
        parser.error('Snapshot identity arguments require --snapshot')
    if args.output.exists():
        raise FileExistsError(args.output)
    if json.loads((args.run/'status.json').read_text())['state'] != 'complete':
        raise ValueError('Run is not complete')
    checkpoint = args.snapshot or args.run/'last.pt'
    verified = json.loads((args.run/'final_checkpoint_verification.json').read_text())
    digest = sha(checkpoint)
    if verified['test_used'] or sha(args.run/'last.pt') != verified['sha256']:
        raise ValueError('Missing or mismatched final replay')
    if args.snapshot and digest != args.expected_snapshot_sha256.lower():
        raise ValueError('Snapshot identity mismatch')
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    model, payload = load_tone_checkpoint(checkpoint)
    if args.snapshot:
        if payload['step'] != args.expected_snapshot_step:
            raise ValueError('Snapshot step mismatch')
        if payload['run'] != json.loads((args.run/'run.json').read_text()):
            raise ValueError('Snapshot belongs to another run')
    if payload['run']['architecture'] not in ('stable_unet_teacher_mode','stable_unet_teacher_multilayer'):
        raise ValueError('Expected mode-conditioned U-Net')
    model.eval().requires_grad_(False)
    args.output.mkdir(parents=True)
    run = payload['run']
    report = dict(checkpoint=str(checkpoint), sha256=digest, step=payload['step'],
                  snapshot=bool(args.snapshot), checkpoint_full_validation_replayed=not bool(args.snapshot),
                  script_sha256=sha(Path(__file__)), test_used=False,
                  scope='TRAINING DIAGNOSTIC ONLY; no optimizer; not promotable',
                  selection='first/middle/last training sequences in recorded order, both eyes, frame32',
                  precision_scope='head only; identical frozen-parent BF16 causal replay for both heads',
                  caveats=['Not full training-set MAE or generalization evidence',
                           'Forward precision differences do not measure optimization precision effects',
                           'Correction-bound MAE is an optimistic lower bound, not attainable oracle fit',
                           'Only the recorded target mode is scored; alternate mode measures sensitivity'],
                  cohorts={}, images=[])
    bias = model.head.stem[0].mode_bias.detach().float()
    report['mode_bias'] = dict(l2=float(bias.norm()), max_abs=float(bias.abs().max()))
    raw_values = []
    handle = model.head.affine.register_forward_hook(lambda module, inputs, value: raw_values.append(value.float()))
    try:
        for j, (label, root, mode) in enumerate(zip(run['cohort_labels'], run['cohorts'], run['teacher_pass_counts'])):
            cache = AlignedCohort(Path(root), 'train', expected_pass_count=mode)
            if cache.sequence_ids != run['training_sequences'][j]:
                raise ValueError('Changed training membership')
            rows = []
            for sequence in ordered_picks(cache.sequence_ids):
                for eye in (0, 1):
                    state = None
                    for index in cache.streams[sequence, eye][:32]:
                        def tensor(value):
                            return torch.from_numpy(np.array(value, copy=True)).cuda().float()
                        color = tensor(cache.rgb[index:index+1])/255
                        rgb, target = color[:, 0], color[:, 1]
                        guides = tensor(cache.guides[index:index+1])
                        context = tensor(cache.context[index:index+1])
                        with torch.autocast('cuda', dtype=torch.bfloat16):
                            base, state = model.parent.forward_temporal(rgb, guides, context, state)
                    predictions = {}
                    for requested in (1, 2):
                        set_teacher_mode(model.head, requested)
                        with torch.autocast('cuda', dtype=torch.bfloat16):
                            predictions[requested] = model.head(rgb, base, guides, context).float()
                        raw_values.clear()
                    set_teacher_mode(model.head, mode)
                    full = model.head(rgb, base.float(), guides, context).float()
                    raw = F.interpolate(raw_values.pop(), size=base.shape[-2:], mode='bilinear', align_corners=False)
                    lower_mae, outside = correction_bound(base, target)
                    values = dict(
                        identity_mae=float((rgb-target).abs().mean()),
                        parent_mae=float((base.float()-target).abs().mean()),
                        bf16_target_mode_mae=float((predictions[mode]-target).abs().mean()),
                        fp32_target_mode_mae=float((full-target).abs().mean()),
                        fp32_minus_bf16_mae=float((full-target).abs().mean()-(predictions[mode]-target).abs().mean()),
                        precision_prediction_mae=float((full-predictions[mode]).abs().mean()),
                        mode_switch_prediction_mae=float((predictions[2]-predictions[1]).abs().mean()),
                        raw_coefficient_tanh_saturation_fraction=float((raw.tanh().abs()>.99).float().mean()),
                        optimistic_bound_mae=lower_mae, target_outside_bound_fraction=outside)
                    if not all(np.isfinite(value) for value in values.values()):
                        raise ValueError('Nonfinite diagnostic')
                    row = dict(cohort=label, sequence=sequence, eye=eye, frame=32, teacher_pass_count=mode, **values)
                    rows.append(row)
                    report['images'].append(row)
                    save(args.output/'partial.json', report)
            report['cohorts'][label] = dict(images=len(rows), **{key:float(np.mean([row[key] for row in rows])) for key in values})
            save(args.output/'partial.json', report)
            print(json.dumps(dict(cohort=label, **report['cohorts'][label])), flush=True)
        if sha(checkpoint) != digest:
            raise ValueError('Checkpoint changed during diagnostic')
        save(args.output/'result.json', report)
        save(args.output/'status.json', dict(state='complete', test_used=False, images=len(report['images'])))
    except Exception as error:
        save(args.output/'status.json', dict(state='failed', error=repr(error)))
        raise
    finally:
        handle.remove()


if __name__ == '__main__':
    main()
