"""Sequential matched context continuations and immutable validation reports."""
import json
from pathlib import Path
import subprocess
import sys
import os
import argparse
from train_student import atomic_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--resume-failed-control',action='store_true')
    args=parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    phase = root / 'out/quality_phase_20260905'
    state = phase / 'appearance_pair_status.json'
    cache = 'C:/OpenNR/TrainingCache/student_v1'
    parent = phase / 'context_continuation/best_feature.pt'
    if args.resume_failed_control:
        previous=json.loads(state.read_text())
        if previous['state']!='failed':raise ValueError('Recovery requires terminal failed controller')
        if not (phase/'context_fresh_control/last.pt').exists():raise ValueError('Missing recovery checkpoint')
        if (phase/'appearance_pair_failure.json').exists():raise ValueError('Recovery already attempted; inspect before further recovery')
        atomic_json(phase/'appearance_pair_failure.json',previous)
    elif state.exists():
        raise ValueError('Pair already dispatched; inspect its process and state before resuming')
    if not (phase / 'dynamic_final_evaluation/complete.json').exists():
        raise ValueError('Finish dynamic evaluation first')
    for name in ('context_fresh_control', 'context_fresh_vgg'):
        if (phase / name).exists() and not (args.resume_failed_control and name=='context_fresh_control'):
            raise ValueError(f'Output already exists: {name}')
    def execute(arguments, label):
        atomic_json(state, dict(state='running', stage=label, pid=os.getpid()))
        suffix='_recovery' if args.resume_failed_control else ''
        with (phase / f'{label}{suffix}.log').open('w') as log:
            subprocess.run([sys.executable, *map(str, arguments)], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
    try:
        for name, weight in [('context_fresh_control', 0), ('context_fresh_vgg', .05)]:
            destination = phase / name
            initialization=['--resume',destination/'last.pt'] if args.resume_failed_control and name=='context_fresh_control' else ['--initialize',parent]
            execute(['tools/train_long_student.py', '--cache', cache,
                     '--output', destination, *initialization,
                     '--dynamic-guides', 'C:/OpenNR/TrainingCache/dynamic_guides_v1',
                     '--workers', 2, '--steps', 12000, '--lr', .00005,
                     '--eval-every', 1000, '--vgg-weight', weight], name)
            result = json.loads((destination / 'status.json').read_text())
            if result['state'] != 'completed' or result['step'] != 12000:
                raise RuntimeError(f'Incomplete training: {name}')
            execute(['tools/evaluate_quality_run.py', '--run', destination,
                     '--cache', cache, '--baseline', parent,
                     '--output', phase / f'{name}_evaluation'], f'{name}_evaluation')
    except Exception as exc:
        atomic_json(state, dict(state='failed', pid=os.getpid(), error=str(exc)))
        raise
    atomic_json(state, dict(state='completed', pid=os.getpid()))


if __name__ == '__main__':
    main()
