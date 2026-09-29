"""Paired scene-level comparison of existing native-eye validation results."""
import argparse
import json
from pathlib import Path
from statistics import mean


def compare(baseline, candidate):
    def index(report):
        rows = report['records']
        result = {(r['sequence'], r['frame'], r['eye'], r['row']): r for r in rows}
        if len(result) != len(rows):
            raise ValueError('Duplicate native eye')
        return result
    left, right = index(baseline), index(candidate)
    if left.keys() != right.keys() or baseline['mask_definition'] != candidate['mask_definition']:
        raise ValueError('Unmatched validation eyes or masks')
    for key in left:
        if abs(left[key]['identity_mae'] - right[key]['identity_mae']) > 1e-10:
            raise ValueError('Input/teacher baseline changed')
    records = []
    for sequence in sorted({key[0] for key in left}):
        keys = [key for key in left if key[0] == sequence]
        record = dict(sequence=sequence, eyes=len(keys))
        for metric in ('mae', 'changed_region_mae'):
            before = mean(left[key][metric] for key in keys)
            after = mean(right[key][metric] for key in keys)
            record[metric] = dict(baseline=before, candidate=after,
                                  relative_change_percent=100*(after/before-1),
                                  improved_eyes=sum(right[key][metric] < left[key][metric] for key in keys))
        records.append(record)
    return dict(baseline_sha256=baseline['checkpoint_sha256'],
                candidate_sha256=candidate['checkpoint_sha256'], records=records,
                scope='Paired unchanged native validation eyes. Scene metrics are equal-eye means, including changed-region MAE; not pooled changed-pixel errors. Four sequences are not broad independent acceptance.')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args()
    result=compare(json.loads(a.baseline.read_text()), json.loads(a.candidate.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
