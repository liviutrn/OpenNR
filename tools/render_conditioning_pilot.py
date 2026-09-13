"""Render fixed midpoint held-out examples after the locked pilot evaluation."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from audit_conditioning_content import picture,sheet
from train_conditioning_pilot import Cache,RendererRefiner


@torch.no_grad()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    config=json.loads((a.run/'run.json').read_text())
    cache=Cache(Path(config['cache']))
    cache.parent=np.load(a.run/'parent.npy',mmap_mode='r')
    models={}
    for name in ('control','conditioned'):
        model=RendererRefiner().cuda().eval()
        model.load_state_dict(torch.load(a.run/name/'best.pt',map_location='cuda',weights_only=False)['model'])
        models[name]=model
    pages=[]
    for seq in cache.complete['split']['test']:
        cells=[]
        for eye in (0,1):
            ids=cache.streams['test',seq,eye]
            rgb,target,g,c,parent=cache.batch([ids[31]])
            views=[('input',rgb),('teacher',target),('parent',parent)]
            for name,m in models.items():
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    views.append((name,m(rgb,parent,g,c,name=='control')))
            for name,value in views:
                cells.append((f'E{eye} F32 {name}',picture(value[0].float().cpu().numpy().transpose(1,2,0))))
        filename=seq+'_test_samples.png'
        sheet(cells,5,a.run/filename,384)
        pages.append(f'<h2>{seq}</h2><a href="{filename}"><img src="{filename}"></a>')
    html='<!doctype html><meta charset="utf-8"><title>Renderer-conditioning pilot samples</title>'
    html+='<style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}a{color:#8cf}</style>'
    html+='<h1>Renderer-conditioning pilot samples</h1><p>Untouched test clips, fixed frame 32, both eyes. Columns: input, teacher, frozen parent, control refiner, renderer-conditioned refiner. Same display scale; no brightness enhancement.</p>'
    html+='<p>The conditioned arm won validation but lost to the control on test. These visualizations do not trigger additional tuning or checkpoint selection.</p>'
    html+=''.join(pages)
    (a.run/'samples.html').write_text(html,encoding='utf-8')


if __name__=='__main__':
    torch.set_num_threads(4)
    main()
