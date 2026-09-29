"""Mode-labeled held-out visual checks; no test access, no optimizer."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from verify_spatial_tone import load_tone_checkpoint
from multilayer_teacher_mode import set_conditioned_teacher_mode as set_teacher_mode
from prepare_conditioning_pilot import sha,save
from audit_conditioning_content import picture,sheet


@torch.no_grad()
def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    torch.set_num_threads(4)
    digest=sha(a.checkpoint);model,payload=load_tone_checkpoint(a.checkpoint)
    if sha(a.checkpoint)!=digest:raise ValueError('Snapshot changed during load')
    if payload['run']['architecture'] not in ('stable_unet_teacher_mode','stable_unet_teacher_multilayer'):raise ValueError('Wrong architecture')
    warm_path=Path(payload['run']['initial_head'])
    if sha(warm_path)!=payload['run']['initial_head_sha256']:raise ValueError('Warm reference changed')
    warm,wp=load_tone_checkpoint(warm_path)
    if wp['run']['parent_sha256']!=payload['run']['parent_sha256']:raise ValueError('Different parents')
    a.output.mkdir(parents=True);pages=[];picks=[]
    for label,root,mode in zip(payload['run']['cohort_labels'],payload['run']['cohorts'],payload['run']['teacher_pass_counts']):
        if label not in ('prior','fresh_session','two_pass'):continue
        cache=AlignedCohort(Path(root),'validation',expected_pass_count=mode)
        known_face='seq-1788671399304-47'
        seq=known_face if label=='prior' and known_face in cache.sequence_ids else cache.sequence_ids[0]
        picks.append(dict(cohort=label,sequence=seq,teacher_pass_count=mode))
        for eye in (0,1):
            state=None
            for i in cache.streams[seq,eye][:32]:
                def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                color=tensor(cache.rgb[i:i+1])/255;rgb,target=color[:,0],color[:,1]
                g=tensor(cache.guides[i:i+1]);c=tensor(cache.context[i:i+1])
                with torch.autocast('cuda',dtype=torch.bfloat16):base,state=model.parent.forward_temporal(rgb,g,c,state)
            with torch.autocast('cuda',dtype=torch.bfloat16):
                reference=warm.head(rgb,base,g,c)
                set_teacher_mode(model.head,1);normal=model.head(rgb,base,g,c)
                set_teacher_mode(model.head,2);amplified=model.head(rgb,base,g,c)
            views=[('input',rgb),(f'teacher {mode}x',target),('warm U-Net 5600 (1x)',reference),
                   (f"student step{payload['step']} mode1x",normal),(f"student step{payload['step']} mode2x",amplified)]
            if any(not torch.isfinite(value).all() for _,value in views):raise ValueError('Nonfinite view')
            filename=f'{label}-{seq}-eye{eye}.png'
            sheet([(label,picture(value[0].float().cpu().numpy().transpose(1,2,0))) for label,value in views],5,a.output/filename,512)
            pages.append(f'<h2>{label}, {seq}, eye{eye}, frame32, target{mode}x</h2><a href="{filename}"><img src="{filename}"></a>')
    (a.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Joint teacher-mode progress</title><style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}</style><h1>Normal and amplified mode progress</h1><p>Native512 tiles; no exposure adjustment. Input / captured teacher mode / warm5600 / current mode1 / current mode2. The alternate requested mode has no paired target here. These are fixed progress views, not independent checkpoint metric replay or stereo/headset acceptance.</p>'+''.join(pages),encoding='utf-8')
    save(a.output/'provenance.json',dict(checkpoint=str(a.checkpoint),sha256=digest,step=payload['step'],
        warm_reference=str(warm_path),warm_sha256=sha(warm_path),selection=picks,test_used=False,
        full_replay_verified=False,images=len(pages),scope='validation progress; alternate mode not scored against mismatched teacher'))
    print(json.dumps(dict(state='complete',step=payload['step'],images=len(pages))),flush=True)


if __name__=='__main__':main()
