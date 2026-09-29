"""Fixed training-subset fit and semantic-branch response; never a full fit score."""
import argparse
import json
from pathlib import Path
import torch
from prepare_conditioning_pilot import save, sha
from train_semantic_ablation import cohort
from train_temporal_student import evaluate_streaming
from verify_semantic_ablation import load_checkpoint
from verify_spatial_tone import load_tone_checkpoint


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--control', type=Path, required=True)
    p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    payload = torch.load(a.candidate, map_location='cpu', weights_only=False)
    run = payload['run']
    datasets = []
    selection = {}
    for label, root in zip(run['cohort_labels'], run['cohorts']):
        dataset = cohort(Path(root), 'train')
        ids = sorted(set((dataset.sequence_ids[0], dataset.sequence_ids[-1])))
        dataset.streams = {key: value for key, value in dataset.streams.items() if key[0] in ids}
        datasets.append((label, dataset))
        selection[label] = ids
    result = {'scope': __doc__, 'selection': 'first and last training sequence per cohort; both eyes, all64frames',
              'sequences': selection, 'validation_used': False, 'test_used': False,
              'source_sha256': sha(Path(__file__)), 'arms': {}}
    save(a.output / 'selection.json', result)
    del payload
    for label, path in [('warm', Path(run['warm_head'])), ('random_control', a.control), ('pretrained', a.candidate)]:
        model, payload = load_tone_checkpoint(path) if label == 'warm' else load_checkpoint(path)
        if label != 'warm':
            for key in ('warm_head_sha256', 'cohorts', 'cohort_complete_sha256', 'seed', 'steps'):
                if payload['run'][key] != run[key]:
                    raise ValueError('Probe arm identity mismatch: ' + key)
        modes = (False, True) if label == 'pretrained' else (False,)
        for disabled in modes:
            name = label + ('_projection_disabled' if disabled else '')
            hook = model.head.semantic_projection.register_forward_hook(lambda module, inputs, output: torch.zeros_like(output)) if disabled else None
            try:
                metrics = {}
                for domain, dataset in datasets:
                    save(a.output / 'status.json', {'state': 'evaluating', 'arm': name, 'cohort': domain})
                    metrics[domain] = evaluate_streaming(model, dataset, batch=4)
                    print(json.dumps({'arm': name, 'cohort': domain, 'mae': metrics[domain]['mae']}), flush=True)
                result['arms'][name] = {'checkpoint': str(path.resolve()), 'sha256': sha(path), 'metrics': metrics}
                save(a.output / 'result.json', result)
            finally:
                if hook is not None:
                    hook.remove()
        del model, payload
        torch.cuda.empty_cache()
    save(a.output / 'status.json', {'state': 'complete', 'test_used': False})


if __name__ == '__main__':
    main()
