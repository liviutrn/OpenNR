"""Reload selected comparison checkpoints and verify all validation metrics."""
import argparse
import json
from pathlib import Path
import torch
from aligned_cohort import AlignedCohort
from train_capacity_temporal_student import _load_parent
from train_temporal_student import evaluate_streaming
from prepare_conditioning_pilot import save, sha


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--single-run',action='store_true',help='Verify one completed continuation rather than corrected/legacy subdirectories')
    a=p.parse_args()
    torch.set_num_threads(4)
    report={'test_used':False,'arms':{}}
    for arm in (('continuation',) if a.single_run else ('corrected','legacy')):
        root=a.root if a.single_run else a.root/arm
        if json.loads((root/'status.json').read_text())['state']!='complete':
            raise ValueError('Verify only completed runs; do not race checkpoint replacement')
        path=root/'best_all_cohorts.pt'
        if not path.exists(): path=root/'best_mean.pt'
        model,payload,*_= _load_parent(path)
        model.eval()
        result={'checkpoint':str(path),'sha256':sha(path),'step':payload['step'],'cohorts':{}}
        for label,cohort in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
            dataset=AlignedCohort(Path(cohort),'validation',payload['run']['guide_mode']=='existing-cache')
            metrics=evaluate_streaming(model,dataset,batch=4)
            expected=payload['validation'][label]
            deltas={key:abs(metrics[key]-expected[key]) for key in ('mae','psnr','temporal_delta_mae')}
            if max(deltas.values())>1e-7:
                raise ValueError(f'Checkpoint reproduction mismatch: {arm} {label} {deltas}')
            result['cohorts'][label]={'metrics':metrics,'absolute_reproduction_difference':deltas}
            print(json.dumps({'arm':arm,'cohort':label,'mae':metrics['mae'],'verified':True}),flush=True)
        report['arms'][arm]=result
        del model
        torch.cuda.empty_cache()
    save(a.root/'checkpoint_verification.json',report)


if __name__=='__main__':main()
