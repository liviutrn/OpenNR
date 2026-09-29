"""Paired RGB-context extent diagnostic on audited spatial masters; no test access.

Keep the image patch, guides, context-guide planes, model and reset fixed;
change only context RGB from crop thumbnail to actual full-eye thumbnail.
This is inference sensitivity, not a trained ablation or temporal acceptance.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from prepare_conditioning_pilot import save, sha
from verify_spatial_tone import load_tone_checkpoint


def thumbnail(array):
    return (np.asarray(Image.fromarray(np.ascontiguousarray(array)).resize((96, 96), Image.Resampling.BOX))
            .astype(np.float32).transpose(2, 0, 1) / 255).astype(np.float16)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--primary-manifest', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--split', choices=('train', 'validation'), default='train')
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    meta = json.loads((a.cache / 'complete.json').read_text())
    if meta['source_manifest_sha256'] != sha(a.primary_manifest):
        raise ValueError('Primary spatial manifest changed')
    primary = [json.loads(line) for line in a.primary_manifest.read_text().splitlines() if line]
    allowed = {r['sequence_id'] for r in primary if r['split'] == a.split}
    rows = json.loads((a.cache / 'rows.json').read_text())
    patches = json.loads((a.cache / 'patches.json').read_text())
    selected = {}
    for i, patch in enumerate(patches):
        row = rows[patch['row']]
        if row['split'] != a.split or row['sequence_id'] not in allowed:
            continue
        selected.setdefault((row['sequence_id'], row['eye']), i)
    rgb = np.load(a.cache / 'rgb.npy', mmap_mode='r')
    guides = np.load(a.cache / 'guides.npy', mmap_mode='r')
    contexts = np.load(a.cache / 'context.npy', mmap_mode='r')
    model, payload = load_tone_checkpoint(a.checkpoint)
    results = []
    for key, index in sorted(selected.items()):
        patch = patches[index]
        row = rows[patch['row']]
        x, y, w, h = patch['box']
        width, height = row['color_size']
        source_hashes = {}
        for stage_index, stage in enumerate(('input', 'teacher')):
            path = Path(row['paths'][stage]).with_suffix('.raw.bin')
            if path.stat().st_size != width * height * 4:
                raise ValueError('Raw source size mismatch')
            raw = np.memmap(path, mode='r', dtype='uint8', shape=(height, width, 4))
            if not np.array_equal(raw[y:y+h, x:x+w, :3].transpose(2, 0, 1), rgb[index, stage_index]):
                raise ValueError('Cached RGB differs from committed master')
            if stage == 'input':
                global_rgb = thumbnail(raw[:, :, :3])
                if not np.array_equal(global_rgb, contexts[patch['row'], :3]):
                    raise ValueError('Cached global context RGB differs from source')
            source_hashes[stage] = sha(path)
        values = torch.from_numpy(np.array(rgb[index], copy=True)).cuda().float() / 255
        guide = torch.from_numpy(np.array(guides[index:index+1], copy=True)).cuda().float()
        global_context = np.array(contexts[patch['row']], copy=True)
        cropped_context = global_context.copy()
        cropped_context[:3] = thumbnail(rgb[index, 0].transpose(1, 2, 0))
        metrics = {}
        predictions = {}
        for name, ctx in (('full_eye_rgb', global_context), ('crop_rgb', cropped_context)):
            context = torch.from_numpy(ctx[None]).cuda().float()
            with torch.no_grad(), torch.autocast('cuda', dtype=torch.bfloat16):
                prediction, _ = model.forward_temporal(values[0:1], guide, context, None)
            prediction = prediction.float()
            metrics[name] = float((prediction - values[1:2]).abs().mean())
            predictions[name] = prediction
        results.append({'sequence': key[0], 'eye': key[1], 'frame': row['frame_id'],
                        'box': patch['box'], 'source_sha256': source_hashes, 'mae': metrics,
                        'prediction_difference_mae': float((predictions['full_eye_rgb'] - predictions['crop_rgb']).abs().mean())})
        save(a.output / 'status.json', {'state': 'evaluating', 'done': len(results), 'total': len(selected)})
    result = {'scope': __doc__, 'checkpoint': str(a.checkpoint.resolve()), 'checkpoint_sha256': sha(a.checkpoint),
              'cache': str(a.cache.resolve()), 'cache_complete_sha256': sha(a.cache / 'complete.json'),
              'split': a.split, 'test_used': False, 'validation_used': a.split == 'validation',
              'source_sha256': sha(Path(__file__)),
              'sequence_count': len(allowed), 'images': len(results), 'input_teacher_crops_exact': True,
              'full_eye_context_rgb_exact': True, 'context_guide_planes': 'unchanged whole-eye planes in both variants',
              'mean_mae': {name: float(np.mean([r['mae'][name] for r in results])) for name in ('full_eye_rgb', 'crop_rgb')},
              'mean_prediction_difference_mae': float(np.mean([r['prediction_difference_mae'] for r in results])),
              'records': results}
    save(a.output / 'result.json', result)
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})
    print(json.dumps({k: v for k, v in result.items() if k != 'records'}), flush=True)


if __name__ == '__main__':
    main()
