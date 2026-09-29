"""Paired same-frame full-history versus eight-frame-window training diagnostic."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_temporal_student import _device_batch


@torch.no_grad()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    checkpoint=a.run/'best_all_cohorts.pt'
    verified=json.loads((a.run/'checkpoint_verification.json').read_text())['arms']['continuation']
    if sha(checkpoint)!=verified['sha256']:raise ValueError('Unverified checkpoint')
    model,payload,*_=_load_parent(checkpoint)
    model.eval().requires_grad_(False)
    report={'checkpoint_sha256':sha(checkpoint),'test_used':False,
            'scope':'all training sequences; matched frames with offset2..7 in noninitial eight-frame blocks',
            'limitation':'Fixed block starts sample the training window distribution; not all random starts. No gradient or training-trajectory claim.',
            'cohorts':{}}
    for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
        cache=AlignedCohort(Path(root),'train')
        totals=np.zeros(3,dtype=np.float64);count=0;rows=[]
        for batch_index,(keys,arrays) in enumerate(cache.stream_batches(4)):
            rgb,target,g,c=_device_batch(arrays)
            rgb=rgb.float()/255;target=target.float()/255;g=g.float();c=c.float()
            continuous=window=None
            sums=np.zeros((len(keys),3),dtype=np.float64);frames=0
            for f in range(64):
                if f%8==0:window=None
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    full,continuous=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],continuous)
                    short,window=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],window)
                if f>=8 and f%8>=2:
                    values=torch.stack(((full.float()-target[:,f]).abs().mean((1,2,3)),
                                        (short.float()-target[:,f]).abs().mean((1,2,3)),
                                        (full.float()-short.float()).abs().mean((1,2,3))),1)
                    sums+=values.cpu().numpy();frames+=1
            totals+=sums.sum(0);count+=frames*len(keys)
            for key,values in zip(keys,sums):rows.append({'sequence':key[0],'eye':key[1],'frames':frames,'full_mae':values[0]/frames,'window_mae':values[1]/frames,'prediction_difference_mae':values[2]/frames})
            save(a.output/'status.json',{'state':'evaluating','cohort':label,'completed_eye_streams':len(rows),'total_eye_streams':len(cache.streams)})
            if batch_index%10==0:print(json.dumps({'cohort':label,'eye_streams':len(rows)}),flush=True)
        report['cohorts'][label]={'matched_eye_frames':count,'full_mae':totals[0]/count,'window_mae':totals[1]/count,'prediction_difference_mae':totals[2]/count,'streams':rows}
        save(a.output/'partial.json',report)
        print(json.dumps({'cohort':label,**{k:v for k,v in report['cohorts'][label].items() if k!='streams'}}),flush=True)
    save(a.output/'result.json',report)
    save(a.output/'status.json',{'state':'complete','test_used':False})


if __name__=='__main__':main()
