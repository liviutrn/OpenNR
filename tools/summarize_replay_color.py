"""Pixel-weighted color diagnostics from fixed replay samples, not full cohorts."""
import argparse
import hashlib
import json
from pathlib import Path


def summarize(report):
    result = {}
    for label, cohort in report['cohorts'].items():
        samples = cohort.get('samples', [])
        if not samples:
            raise ValueError('Rendered sample metrics required: ' + label)
        groups = {}
        for group in samples[0]['color']:
            rows = [s['color'][group] for s in samples if s['color'][group]['pixels']]
            pixels = sum(r['pixels'] for r in rows)
            if not pixels:
                groups[group] = {'pixels': 0}
                continue
            def mean(key):
                return sum(r[key] * r['pixels'] for r in rows) / pixels
            values = {key: mean(key) for key in ('signed_luma_error', 'luma_mae',
                       'rgb_mae', 'teacher_minus_input_luma')}
            values['signed_rgb_error'] = [sum(r['signed_rgb_error'][c] * r['pixels']
                                               for r in rows) / pixels for c in range(3)]
            values['pixels'] = pixels
            if abs(values['signed_luma_error']) > values['luma_mae'] + 1e-7:
                raise ValueError('Signed/absolute metric inconsistency')
            groups[group] = values
        result[label] = {'samples': len(samples), 'groups': groups}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replay', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    raw = args.replay.read_bytes()
    report = json.loads(raw)
    result = {'scope': 'Fixed first/last sequence, both eyes, frames32/64; not full-cohort color statistics.',
              'source': str(args.replay.resolve()), 'source_sha256': hashlib.sha256(raw).hexdigest(),
              'checkpoint_sha256': report['sha256'], 'step': report['step'], 'split': report['split'],
              'test_used': report['test_used'], 'cohorts': summarize(report)}
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    for label, entry in result['cohorts'].items():
        g = entry['groups']
        print(json.dumps({'cohort': label, 'samples': entry['samples'],
              'brightened_region_signed_error': g['teacher_brightens'].get('signed_luma_error'),
              'darkened_region_signed_error': g['teacher_darkens'].get('signed_luma_error'),
              'overall_signed_rgb': g['all']['signed_rgb_error']}))


if __name__ == '__main__':
    main()
