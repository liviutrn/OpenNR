"""Progress images from an immutable checkpoint snapshot; full replay remains separate."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from verify_spatial_tone import load_tone_checkpoint
from prepare_conditioning_pilot import sha,save
from audit_conditioning_content import picture,sheet


@torch.no_grad()
def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--selection',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    torch.set_num_threads(4);digest=sha(a.checkpoint)
    model,payload=load_tone_checkpoint(a.checkpoint)
    if sha(a.checkpoint)!=digest:raise ValueError('Snapshot changed during loading')
    if payload['run']['test_used']:raise ValueError('Test exposure')
    picks=json.loads(a.selection.read_text())['validation_sequences']['prior'][:2]
    cache=AlignedCohort(Path(payload['run']['cohorts'][0]),'validation')
    if not set(picks)<=set(cache.sequence_ids):raise ValueError('Selection not validation')
    a.output.mkdir(parents=True);pages=[]
    for seq in picks:
        for eye in (0,1):
            state=None
            for i in cache.streams[seq,eye][:32]:
                def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                color=tensor(cache.rgb[i:i+1])/255;rgb,target=color[:,0],color[:,1]
                g=tensor(cache.guides[i:i+1]);c=tensor(cache.context[i:i+1])
                with torch.autocast('cuda',dtype=torch.bfloat16):base,state=model.parent.forward_temporal(rgb,g,c,state)
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=model.head(rgb,base,g,c)
            if not torch.isfinite(pred).all():raise ValueError('Nonfinite prediction')
            filename=f'{seq}-eye{eye}.png'
            views=[('input',rgb),('teacher',target),('retained parent',base),(f"U-Net progress step {payload['step']}",pred)]
            sheet([(label,picture(value[0].float().cpu().numpy().transpose(1,2,0))) for label,value in views],4,a.output/filename,512)
            pages.append(f'<h2>{seq}, eye{eye}, frame32</h2><img src="{filename}" style="max-width:100%">')
    (a.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>U-Net progress samples</title><h1>Validation progress samples</h1><p>Input / teacher / retained parent / current U-Net. No exposure adjustment. Parent and head source hashes checked; full checkpoint validation replay pending.</p>'+''.join(pages),encoding='utf-8')
    save(a.output/'provenance.json',{'checkpoint':str(a.checkpoint),'sha256':digest,'step':payload['step'],'validation_sequences':picks,'selection_sha256':sha(a.selection),'full_replay_verified':False,'test_used':False})
    print(json.dumps({'state':'complete','step':payload['step'],'images':len(pages)}),flush=True)


if __name__=='__main__':main()
