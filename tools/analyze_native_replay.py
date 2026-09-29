"""Summarize warm replay timing and visibly verify native Feature 18 output."""
import argparse
import csv
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--teacher', type=Path, required=True)
    p.add_argument('--student', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((a.teacher / 'provenance.json').read_text())
    student = json.loads((a.student / 'result.json').read_text())
    if student['contended_smoke']:
        raise ValueError('Contended smoke is not a performance result')
    with (a.teacher / 'timings.csv').open() as f:
        timing = [r for r in csv.DictReader(f) if int(r['warm']) == 1]
    if not timing:
        raise ValueError('No warm teacher samples')
    summary = {'teacher': {}, 'student': student, 'output_checks': [],
               'scope': 'Offline static stereo replay, not Skyrim/headset acceptance. Teacher repeats motion/history; student is spatial. No quality equivalence claim.'}
    for key in ('pair_gpu_ms', 'pair_wall_ms'):
        values = [float(r[key]) for r in timing]
        summary['teacher'][key] = {'median': float(np.median(values)), 'p95': float(np.percentile(values, 95)), 'count': len(values)}
    summary['wall_speedup'] = summary['teacher']['pair_wall_ms']['median'] / student['wall_median_ms']
    for row in provenance['rows']:
        w, h = row['color_size']; eye = row['eye']
        if student['resolution'] != [w, h]:
            raise ValueError('Resolution mismatch')
        inp = np.asarray(Image.open(row['paths']['input']).convert('RGB'))
        captured = np.asarray(Image.open(row['paths']['teacher']).convert('RGB'))
        native = np.fromfile(a.teacher / f'teacher_eye{eye}.rgba', dtype='u1').reshape(h, w, 4)[..., :3]
        pred = np.fromfile(a.student / f'student_eye{eye}.rgba', dtype='u1').reshape(h, w, 4)[..., :3]
        difference = np.abs(native.astype('f4') - inp.astype('f4')) / 255
        check = {'eye': eye, 'native_min': int(native.min()), 'native_max': int(native.max()),
                 'native_vs_input_mae': float(difference.mean()),
                 'changed_channel_fraction': float(np.mean(native != inp)),
                 'native_vs_captured_teacher_mae': float(np.abs(native.astype('f4') - captured.astype('f4')).mean() / 255)}
        if check['native_max'] <= check['native_min'] or check['native_vs_input_mae'] <= .0001:
            raise ValueError(f'Teacher output is empty or effectively pass-through: {check}')
        summary['output_checks'].append(check)
        ims = [inp, pred, native, captured]
        labels = ['Recorded input', 'Student via D3D12', 'Native NVIDIA replay', 'Captured teacher (different history)']
        full = Image.new('RGB', (480 * 4, 550), '#151a20')
        detail = Image.new('RGB', (512 * 4, 550), '#151a20')
        for i, (pixels, label) in enumerate(zip(ims, labels)):
            im = Image.fromarray(pixels)
            cx, cy = int(.56*w), int(.36*h)
            detail.paste(im.crop((cx-256, cy-256, cx+256, cy+256)), (512*i, 32))
            ImageDraw.Draw(detail).text((512*i+8, 8), label, fill='white')
            im.thumbnail((480, 518)); full.paste(im, (480*i, 32))
            ImageDraw.Draw(full).text((480*i+8, 8), label, fill='white')
        full.save(a.output / f'replay_eye{eye}.jpg', quality=96)
        detail.save(a.output / f'replay_detail_eye{eye}.jpg', quality=96)
    (a.output / 'comparison.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
