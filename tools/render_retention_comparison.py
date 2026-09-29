"""Render fixed validation scenes for verified retention seeds; no test access."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from audit_conditioning_content import picture,sheet
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent


@torch.no_grad()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runs',type=Path,nargs=2,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    configs=[json.loads((r/'run.json').read_text()) for r in a.runs]
    for key in ('parent_sha256','cohort_complete_sha256','steps','probabilities','learning_rate','loss'):
        if configs[0][key]!=configs[1][key]:raise ValueError('Recipe mismatch: '+key)
    checkpoints={}
    for r,c in zip(a.runs,configs):
        path=r/'best_all_cohorts.pt'
        verification=json.loads((r/'checkpoint_verification.json').read_text())['arms']['continuation']
        if sha(path)!=verification['sha256']:raise ValueError('Selected checkpoint not verified')
        checkpoints[f"seed{c['seed']}"]=path
    # Resolve original parent through the pre-retention run's recorded lineage.
    parent_config=json.loads((Path(configs[0]['parent']).parent/'run.json').read_text())
    original=Path(parent_config['parent'])
    if sha(original)!=parent_config['parent_sha256']:raise ValueError('Original parent changed')
    checkpoints={'original':original,**checkpoints}
    models={name:_load_parent(path)[0].eval() for name,path in checkpoints.items()}
    a.output.mkdir(parents=True,exist_ok=False)
    pages=[];selected={}
    for label,root in zip(('prior','high_effect','renderer_pilot'),configs[0]['cohorts']):
        corrected=AlignedCohort(Path(root),'validation')
        legacy=AlignedCohort(Path(root),'validation',True)
        seqs=corrected.sequence_ids
        picked=sorted({seqs[i] for i in (0,len(seqs)//2,len(seqs)-1)})
        selected[label]=picked;cells=[]
        for seq in picked:
            for eye in (0,1):
                states={key:None for key in models}
                for i in corrected.streams[seq,eye][:32]:
                    def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                    color=tensor(corrected.rgb[i:i+1])/255
                    rgb,target=color[:,0],color[:,1]
                    views={'input':rgb,'teacher':target}
                    for name,model in models.items():
                        d=legacy if name=='original' else corrected
                        with torch.autocast('cuda',dtype=torch.bfloat16):
                            views[name],states[name]=model.forward_temporal(rgb,tensor(d.guides[i:i+1]),tensor(d.context[i:i+1]),states[name])
                for name,value in views.items():
                    cells.append((f'{seq[-6:]} E{eye} F32 {name}',picture(value[0].float().cpu().numpy().transpose(1,2,0))))
        sheet(cells,5,a.output/(label+'.png'),256)
        pages.append(f'<h2>{label}</h2><img src="{label}.png">')
    (a.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Retention seeds</title><style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}</style><h1>Verified retention models</h1><p>Input, teacher, original model, seed352, seed353. Fixed validation sequences; both eyes, causal history through frame32. No test access or display enhancement.</p>'+''.join(pages),encoding='utf-8')
    save(a.output/'provenance.json',{'checkpoints':{n:{'path':str(p),'sha256':sha(p)} for n,p in checkpoints.items()},'validation_sequences':selected,'test_used':False})


if __name__=='__main__':
    torch.set_num_threads(4)
    main()
