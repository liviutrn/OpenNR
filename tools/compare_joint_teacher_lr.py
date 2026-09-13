"""Compare matched LR arms without GPU work or test access."""
import argparse
import json
import math
from pathlib import Path
from prepare_conditioning_pilot import save, sha


def compare(control_run, arm_run, control_history, arm_history):
    differences = {key for key in set(control_run) | set(arm_run)
                   if control_run.get(key) != arm_run.get(key)}
    if differences != {'learning_rate', 'trainer_source_sha256'}:
        raise ValueError(f'Unexpected configuration differences: {sorted(differences)}')
    if control_run['test_used'] or arm_run['test_used']:
        raise ValueError('Test data used')
    labels = control_run['cohort_labels']
    if len(labels) != 5 or control_run['teacher_pass_counts'] != [1,1,1,1,2]:
        raise ValueError('Expected explicit five-cohort teacher modes')
    def keyed(history):
        result = {entry['step']:entry for entry in history}
        if len(result) != len(history) or 0 not in result:
            raise ValueError('Missing baseline or duplicate steps')
        return result
    control, arm = keyed(control_history), keyed(arm_history)
    baseline_difference = {}
    for label in labels:
        baseline_difference[label] = {}
        for metric in ('mae','psnr','temporal_delta_mae'):
            if not all(math.isfinite(entry[0]['validation'][label][metric]) for entry in (control, arm)):
                raise ValueError('Nonfinite baseline metric')
            delta = abs(control[0]['validation'][label][metric]-arm[0]['validation'][label][metric])
            if delta > 1e-7:
                raise ValueError(f'Baseline mismatch: {label}/{metric}')
            baseline_difference[label][metric] = delta
    paired = []
    for step in sorted(set(control) & set(arm)):
        left, right = control[step], arm[step]
        for key in ('sample_schedule_sha256','baseline_sample_schedule_sha256','cohort_draws','hard_draws'):
            if left[key] != right[key]:
                raise ValueError(f'Unmatched samples/exposure at step{step}: {key}')
        metrics = {}
        for label in labels:
            c, a, b = left['validation'][label], right['validation'][label], control[0]['validation'][label]
            if not all(math.isfinite(entry[key]) for entry in (c,a,b) for key in ('mae','temporal_delta_mae')):
                raise ValueError('Nonfinite paired metric')
            if min(c['mae'], a['mae'], b['mae']) <= 0:
                raise ValueError('Invalid MAE denominator')
            metrics[label] = dict(control_mae=c['mae'], arm_mae=a['mae'],
                arm_minus_control_mae=a['mae']-c['mae'],
                control_relative_to_start=c['mae']/b['mae'],
                arm_relative_to_start=a['mae']/b['mae'],
                arm_minus_control_temporal=a['temporal_delta_mae']-c['temporal_delta_mae'])
        paired.append(dict(step=step, sample_hash=left['sample_schedule_sha256'],
                           exposure=left['cohort_draws'], cohorts=metrics,
                           arm_all_cohort_mae_eligible=all(m['arm_relative_to_start']<1 for m in metrics.values())))
    return dict(test_used=False, baseline_difference=baseline_difference, paired=paired,
                scope='Recorded validation history; does not replace independent checkpoint replay or training-fit evaluation',
                unpaired_arm_steps=sorted(set(arm)-set(control)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--control', type=Path, required=True)
    parser.add_argument('--arm', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = [args.control/'run.json', args.arm/'run.json', args.control/'history.json', args.arm/'history.json']
    digests = [sha(path) for path in paths]
    report = compare(*(json.loads(path.read_text()) for path in paths))
    if digests != [sha(path) for path in paths]:
        raise ValueError('Source changed during comparison; retry this read-only snapshot')
    report.update(sources={str(path):digest for path,digest in zip(paths,digests)}, script_sha256=sha(Path(__file__)))
    save(args.output, report)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
