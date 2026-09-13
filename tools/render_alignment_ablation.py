"""Fixed broad validation examples for the completed alignment comparison."""
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
    p.add_argument('--root',type=Path,required=True)
    a=p.parse_args()
    configs={arm:json.loads((a.root/arm/'run.json').read_text()) for arm in ('corrected','legacy')}
    if configs['corrected']['parent_sha256']!=configs['legacy']['parent_sha256']:
        raise ValueError('Parents differ')
    for key in ('cohorts','seed','steps','learning_rate','loss','probabilities'):
        if configs['corrected'][key]!=configs['legacy'][key]: raise ValueError('Ablation recipe differs: '+key)
    output=a.root/'visuals'
    output.mkdir(exist_ok=True)
    checkpoints={}
    for arm in configs:
        all_path=a.root/arm/'best_all_cohorts.pt'
        checkpoints[arm]=all_path if all_path.exists() else a.root/arm/'best_mean.pt'
    models={'parent':_load_parent(Path(configs['legacy']['parent']))[0]}
    models.update({arm:_load_parent(path)[0] for arm,path in checkpoints.items()})
    for model in models.values():model.eval()
    pages=[]
    for label,root in zip(('prior','high_effect','renderer_pilot'),configs['corrected']['cohorts']):
        datasets={arm:AlignedCohort(Path(root),'validation',arm=='legacy') for arm in configs}
        seqs=datasets['corrected'].sequence_ids
        picked=sorted({seqs[i] for i in (0,len(seqs)//2,len(seqs)-1)})
        cells=[]
        for seq in picked:
            for eye in (0,1):
                ids=datasets['corrected'].streams[seq,eye]
                states={key:None for key in models}
                for frame,i in enumerate(ids[:32]):
                    def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                    color=tensor(datasets['corrected'].rgb[i:i+1])/255
                    rgb,target=color[:,0],color[:,1]
                    predictions={}
                    for name,model in models.items():
                        data=datasets['corrected' if name=='corrected' else 'legacy']
                        with torch.autocast('cuda',dtype=torch.bfloat16):
                            predictions[name],states[name]=model.forward_temporal(rgb,
                                tensor(data.guides[i:i+1]),tensor(data.context[i:i+1]),states[name])
                views={'input':rgb,'teacher':target,**predictions}
                for name,value in views.items():
                    cells.append((f'{seq[-6:]} E{eye} F32 {name}',
                        picture(value[0].float().cpu().numpy().transpose(1,2,0))))
        filename=label+'.png'
        sheet(cells,5,output/filename,256)
        pages.append(f'<h2>{label}</h2><a href="{filename}"><img src="{filename}"></a>')
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Alignment comparison</title>'
        '<style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}</style>'
        '<h1>Full-model native-guide alignment comparison</h1>'
        '<p>Fixed first/middle/last validation sequences; both eyes at frame 32. Columns: input, teacher, original parent, corrected-guides model, existing-guides model. No test frames or display enhancement.</p>'
        +''.join(pages),encoding='utf-8')
    save(output/'provenance.json',{'checkpoints':{key:{'path':str(path),'sha256':sha(path)} for key,path in checkpoints.items()},
                                 'selection':'best all-cohort checkpoint if present; otherwise best mean research checkpoint',
                                 'scope':'fixed validation examples; offline causal predictions; no VR acceptance'})


if __name__=='__main__':
    torch.set_num_threads(4)
    main()
