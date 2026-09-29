"""Registered training-subset feature-history probe; no fitting or test access."""
import argparse
from pathlib import Path
import torch
from prepare_conditioning_pilot import save, sha
from semantic_feature_history import SemanticFeatureHistoryModel
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming
from verify_semantic_ablation import load_checkpoint


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    base, payload = load_checkpoint(a.checkpoint)
    run = payload['run']
    datasets, selection = [], {}
    for label, root in zip(run['cohort_labels'], run['cohorts']):
        dataset = cohort(Path(root), 'train')
        ids = sorted(set((dataset.sequence_ids[0], dataset.sequence_ids[-1])))
        dataset.streams = {key: value for key, value in dataset.streams.items() if key[0] in ids}
        datasets.append((label, dataset))
        selection[label] = ids
    report = {'scope': __doc__, 'checkpoint': str(a.checkpoint.resolve()), 'sha256': sha(a.checkpoint),
              'selection': selection, 'validation_used': False, 'test_used': False,
              'fixed_alpha': .25, 'photometric_threshold': .08, 'arms': {},
              'source_sha256': {name: sha(Path(__file__).with_name(name)) for name in
                               ('probe_semantic_feature_history.py', 'semantic_feature_history.py', 'warp_temporal_student.py')}}
    save(a.output / 'selection.json', report)
    for label, alpha in [('bare', None), ('zero_history', 0), ('quarter_history', .25)]:
        model = base if alpha is None else SemanticFeatureHistoryModel(base, alpha).eval()
        try:
            metrics = {}
            for domain, dataset in datasets:
                save(a.output / 'status.json', {'state': 'evaluating', 'arm': label, 'cohort': domain})
                metrics[domain] = evaluate_streaming(model, dataset, batch=4)
                if alpha == 0:
                    reference = report['arms']['bare'][domain]
                    for key in ('mae', 'psnr', 'temporal_delta_mae', 'first_frame_mae'):
                        if abs(metrics[domain][key] - reference[key]) > 1e-7:
                            raise ValueError('Zero-history identity failed: ' + domain + '/' + key)
                print(label, domain, metrics[domain]['mae'], metrics[domain]['temporal_delta_mae'], flush=True)
            report['arms'][label] = metrics
            save(a.output / 'result.json', report)
        finally:
            if alpha is not None:
                model.close()
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})


if __name__ == '__main__':
    main()
