"""Causal signed tone diagnostic responding to highlight/shadow/color feedback."""
import argparse
import json
from pathlib import Path
import torch
from aligned_cohort import AlignedCohort
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_temporal_student import _device_batch
from tone_error_metrics import tone_metrics


@torch.no_grad()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    torch.set_num_threads(4)
    path=a.run/'best_all_cohorts.pt'
    verification=json.loads((a.run/'checkpoint_verification.json').read_text())['arms']['continuation']
    if sha(path)!=verification['sha256']:raise ValueError('Unverified checkpoint')
    model,payload,*_=_load_parent(path);model.eval()
    report={'checkpoint_sha256':sha(path),'test_used':False,'scope':'training frame32, both eyes, causal history; per-image teacher quintiles with ties included; code-value luma, not physical luminance or skin segmentation','cohorts':{}}
    for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
        cache=AlignedCohort(Path(root),'train');rows=[]
        for keys,arrays in cache.stream_batches(4):
            rgb,t,g,c=_device_batch(arrays)
            rgb=rgb.float()/255;t=t.float()/255;g=g.float();c=c.float();state=None
            for f in range(32):
                with torch.autocast('cuda',dtype=torch.bfloat16):pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
            for i,key in enumerate(keys):
                rows.append({'sequence':key[0],'eye':key[1],'metrics':tone_metrics(pred[i:i+1].float(),t[i:i+1,31],rgb[i:i+1,31])})
            save(a.output/'status.json',{'state':'evaluating','cohort':label,'eyes':len(rows),'total':len(cache.streams)})
            if len(rows)%40==0:print(json.dumps({'cohort':label,'eyes':len(rows)}),flush=True)
        report['cohorts'][label]=rows
        save(a.output/'partial.json',report)
    save(a.output/'result.json',report)
    save(a.output/'status.json',{'state':'complete','test_used':False})


if __name__=='__main__':main()
