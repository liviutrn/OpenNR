"""Native-size verified tone comparisons on previously shown validation scenes."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from aligned_cohort import AlignedCohort
from audit_conditioning_content import picture,sheet
from prepare_conditioning_pilot import save,sha
from verify_spatial_tone import load_tone_checkpoint
from tone_error_metrics import tone_metrics


@torch.no_grad()
def main():
    p=argparse.ArgumentParser();p.add_argument('--local',type=Path,required=True);p.add_argument('--global-run',type=Path,required=True);p.add_argument('--selection',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    torch.set_num_threads(4)
    models={};payloads={};provenance={};display={'input':'input','teacher':'teacher','retained':'retained'}
    for label,root in [('local',a.local),('global',a.global_run)]:
        path=root/'best_all_cohorts.pt';v=json.loads((root/'checkpoint_verification.json').read_text())
        if sha(path)!=v['sha256']:raise ValueError('Unverified head')
        models[label],payloads[label]=load_tone_checkpoint(path)
        run=payloads[label]['run']
        display[label]=run['architecture'] if run.get('architecture') in ('multiscale','stable_unet') else (f"spatial grid 1/{run['grid_downsample']}" if 'grid_downsample' in run else label)
        provenance[label]={'checkpoint':str(path),'sha256':sha(path),'display_label':display[label]}
    if payloads['local']['run']['parent_sha256']!=payloads['global']['run']['parent_sha256']:raise ValueError('Parents differ')
    picks=json.loads(a.selection.read_text())['validation_sequences']
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir(parents=True)
    pages=[];metrics=[]
    for label,root in zip(('prior','high_effect','renderer_pilot'),payloads['local']['run']['cohorts']):
        cache=AlignedCohort(Path(root),'validation')
        for seq in picks[label]:
            for eye in (0,1):
                state=None
                for i in cache.streams[seq,eye][:32]:
                    def tensor(x):return torch.from_numpy(np.array(x,copy=True)).cuda().float()
                    color=tensor(cache.rgb[i:i+1])/255;rgb,target=color[:,0],color[:,1]
                    g=tensor(cache.guides[i:i+1]);c=tensor(cache.context[i:i+1])
                    with torch.autocast('cuda',dtype=torch.bfloat16):base,state=models['local'].parent.forward_temporal(rgb,g,c,state)
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    views={'input':rgb,'teacher':target,'retained':base,'local':models['local'].head(rgb,base,g,c),'global':models['global'].head(rgb,base,g,c)}
                cells=[(display[name],picture(value[0].float().cpu().numpy().transpose(1,2,0))) for name,value in views.items()]
                filename=f'{seq}-eye{eye}.png';sheet(cells,5,a.output/filename,512)
                pages.append(f'<h2>{label}: {seq}, eye{eye}, frame32</h2><a href="{filename}"><img src="{filename}"></a>')
                metrics.append({'sequence':seq,'eye':eye,'cohort':label,'metrics':{name:tone_metrics(views[name].float(),target,rgb) for name in ('retained','local','global')}})
    title=' / '.join(display.values())
    (a.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Verified tone comparison</title><style>body{background:#181a20;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}</style><h1>'+title+'</h1><p>Each image is native512 pixels. Click to enlarge. No exposure adjustment. Previously shown validation scenes, causal frame32, both eyes. No claim that every requested facial condition is present.</p>'+''.join(pages),encoding='utf-8')
    save(a.output/'tone_metrics.json',metrics);save(a.output/'provenance.json',{'models':provenance,'selection_sha256':sha(a.selection),'test_used':False})


if __name__=='__main__':main()
