"""Replay temporal checkpoints on named validation cohorts without frozen-test access."""
import argparse
import json
from pathlib import Path
import torch
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save, sha
from train_temporal_student import StrictTemporalCache, _load_temporal, evaluate_streaming


def named_path(value):
    name, path = value.split('=', 1)
    if not name or not path:
        raise argparse.ArgumentTypeError('Expected label=path')
    return name, Path(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', action='append', type=named_path, required=True)
    parser.add_argument('--cohort', action='append', type=named_path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--batch', type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.batch < 1:
        raise ValueError('Batch must be positive')
    for entries in (args.checkpoint, args.cohort):
        if len({name for name, _ in entries}) != len(entries):
            raise ValueError('Duplicate labels')
    args.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    datasets = []
    for name, path in args.cohort:
        metadata = json.loads((path / 'complete.json').read_text())
        if metadata.get('teacher_pass_count', 1) != 1:
            raise ValueError('This evaluator is reserved for ordinary 1x cohorts')
        if metadata['schema'] in ('opennr-aligned-native-guide-overlay-v1', 'opennr-aligned-renderer-pilot-v1'):
            dataset = AlignedCohort(path, 'validation')
        else:
            dataset = StrictTemporalCache(path, 'validation')
        datasets.append((name, path, dataset))
    result = {'test_used': False, 'teacher_pass_count': 1, 'batch': args.batch,
              'source_sha256': sha(Path(__file__)), 'checkpoints': {}}
    for label, checkpoint in args.checkpoint:
        model, payload = _load_temporal(checkpoint)
        record = {'path': str(checkpoint.resolve()), 'sha256': sha(checkpoint),
                  'step': payload.get('step'), 'cohorts': {}}
        for name, path, dataset in datasets:
            save(args.output / 'status.json', {'state': 'evaluating', 'checkpoint': label, 'cohort': name})
            metrics = evaluate_streaming(model, dataset, batch=args.batch)
            record['cohorts'][name] = {'cache': str(path.resolve()),
                                     'complete_sha256': sha(path / 'complete.json'), 'metrics': metrics}
            print(json.dumps({'checkpoint': label, 'cohort': name, 'mae': metrics['mae'],
                              'temporal_delta_mae': metrics['temporal_delta_mae']}), flush=True)
        result['checkpoints'][label] = record
        save(args.output / 'result.json', result)
        del model
        torch.cuda.empty_cache()
    save(args.output / 'status.json', {'state': 'complete', 'test_used': False})


if __name__ == '__main__':
    main()
