"""Independent validation replay, fixed visual samples, and color diagnostics."""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
import torch
from joint_parent_tone_model import load_joint_checkpoint as load_checkpoint
from stable_oversized_tone_head import StableOversizedToneHead
from prepare_conditioning_pilot import save, sha
from spatial_tone_head import FrozenParentToneModel
from train_capacity_temporal_student import _load_parent
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming, _device_batch
from tone_error_metrics import tone_metrics


def pil(value):
    return Image.fromarray((value.detach().float().clamp(0, 1).cpu().numpy().transpose(1, 2, 0) * 255).round().astype('uint8'))


@torch.no_grad()
def render_samples(model, dataset, label, output):
    chosen = sorted(set([dataset.sequence_ids[0], dataset.sequence_ids[-1]]))
    records = []
    for sequence in chosen:
        for eye in (0, 1):
            ids = dataset.streams[(sequence, eye)]
            rgb, target, guides, context = _device_batch(dataset.load_window(ids[None]))
            rgb, target = rgb.float() / 255, target.float() / 255
            guides, context = guides.float(), context.float()
            state = None
            for frame in range(64):
                with torch.autocast('cuda', dtype=torch.bfloat16):
                    pred, state = model.forward_temporal(rgb[:, frame], guides[:, frame], context[:, frame], state)
                if frame not in (31, 63):
                    continue
                images = [('Input', rgb[0, frame]), (label, pred[0]),
                          ('Feature18 teacher', target[0, frame]),
                          ('Absolute difference x4', (pred[0] - target[0, frame]).abs() * 4)]
                sheet = Image.new('RGB', (2048, 550), '#171b22')
                draw = ImageDraw.Draw(sheet)
                for i, (title, value) in enumerate(images):
                    draw.text((i * 512 + 8, 8), title, fill='white')
                    sheet.paste(pil(value), (i * 512, 32))
                filename = f'{sequence}_e{eye}_f{frame+1:02d}.jpg'
                sheet.save(output / filename, quality=95)
                records.append({'file': filename, 'sequence': sequence, 'eye': eye, 'frame': frame + 1,
                                'color': tone_metrics(pred.float(), target[:, frame], rgb[:, frame])})
    return records


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--render', action='store_true')
    p.add_argument('--split', choices=('train', 'validation'), default='validation')
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    model, payload = load_checkpoint(a.checkpoint)
    run = payload['run']
    report = {'checkpoint': str(a.checkpoint.resolve()), 'sha256': sha(a.checkpoint),
              'step': payload['step'], 'split': a.split, 'test_used': False, 'cohorts': {}}
    for label, root in zip(run['cohort_labels'], run['cohorts']):
        save(a.output / 'status.json', {'state': 'evaluating', 'cohort': label})
        cache = cohort(Path(root), a.split)
        metrics = evaluate_streaming(model, cache, batch=4)
        entry = {'metrics': metrics}
        if a.split == 'validation':
            expected = payload['validation'][label]
            differences = {key: abs(metrics[key] - expected[key]) for key in ('mae', 'psnr', 'temporal_delta_mae')}
            if max(differences.values()) > 1e-7:
                raise ValueError('Independent replay mismatch: ' + str(differences))
            entry['replay_difference'] = differences
        if a.render:
            folder = a.output / label
            folder.mkdir()
            entry['samples'] = render_samples(model, cache, 'DINO joint parent' if run['pretrained_encoder'] else 'DINO random control', folder)
        report['cohorts'][label] = entry
        save(a.output / 'result.json', report)
        print(json.dumps({'cohort': label, 'mae': metrics['mae'], 'split': a.split}), flush=True)
    if a.render:
        links = ''.join(f'<p>{label}</p>' + ''.join(f'<a href="{label}/{s["file"]}"><img src="{label}/{s["file"]}" style="max-width:100%"></a>' for s in v['samples']) for label, v in report['cohorts'].items())
        (a.output / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>OpenNR frozen semantic-feature experiment</title><h1>Experimental checkpoint: ' + a.split + '</h1><p>Fixed frame32/64 samples, both eyes. No exposure adjustment. Color metrics are code-value errors, not physical luminance or skin labels.</p>' + links, encoding='utf-8')
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})


if __name__ == '__main__':
    main()
