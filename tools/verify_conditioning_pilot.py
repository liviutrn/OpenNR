"""Independent direct causal validation replay of the selected pilot checkpoints.

No optimization or test-set metric read. Compare parent-cache values against
fresh inference and report validation metrics from frame-at-a-time execution.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from prepare_conditioning_pilot import save,sha
from train_capacity_temporal_student import _load_parent
from train_conditioning_pilot import RendererRefiner, Cache


@torch.no_grad()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--run',type=Path,required=True)
    a=p.parse_args()
    config=json.loads((a.run/'run.json').read_text())
    results=json.loads((a.run/'result.json').read_text())
    parent_path=Path(config['parent'])
    if sha(parent_path)!=config['parent_sha256']: raise ValueError('Parent changed')
    cache=Cache(Path(config['cache']))
    cache.parent=np.load(a.run/'parent.npy',mmap_mode='r')
    parent,*_= _load_parent(parent_path)
    parent.eval().requires_grad_(False)
    models={}
    for name in ('control','conditioned'):
        saved=torch.load(a.run/name/'best.pt',map_location='cuda',weights_only=False)
        m=RendererRefiner().cuda().eval()
        m.load_state_dict(saved['model'])
        models[name]=m
    totals={name:0. for name in ('parent','control','conditioned')}
    pixels=0
    max_parent_difference=0.
    fallback_difference=0.
    for (split,seq,eye),ids in cache.streams.items():
        if split!='validation': continue
        state=None
        for i in ids:
            rgb,target,g,c,cached=cache.batch([i])
            context=torch.from_numpy(np.array(cache.arrays['context'][i:i+1],copy=True)).cuda().float()
            with torch.autocast('cuda',dtype=torch.bfloat16):
                base,state=parent.forward_temporal(rgb,g,context,state)
                predictions={'parent':base,**{name:m(rgb,base,g,c,name=='control') for name,m in models.items()}}
            max_parent_difference=max(max_parent_difference,(base-cached).abs().max().item())
            fallback_difference=max(fallback_difference,(models['conditioned'](rgb,base,g,None)-base).abs().max().item())
            for name,pred in predictions.items():
                if not torch.isfinite(pred).all(): raise ValueError('Nonfinite direct replay')
                totals[name]+=(pred.float()-target).abs().sum().item()
            pixels+=target.numel()
    mae={name:value/pixels for name,value in totals.items()}
    differences={name:mae[name]-results[name]['validation']['mae'] for name in mae}
    report={'validation_mae':mae,'difference_from_batch4_cached_evaluator':differences,
            'parent_max_pixel_difference':max_parent_difference,'missing_feature_bypass_max_difference':fallback_difference,
            'eye_frames':pixels//(3*512*512),'scope':'direct frame-at-a-time causal validation, not game/runtime timing',
            'checkpoint_sha256':{name:sha(a.run/name/'best.pt') for name in models},
            'parent_sha256':sha(parent_path)}
    # BF16 kernels can vary with batch size. A small tolerance is explicit.
    report['passed']=max_parent_difference<=1e-6 and fallback_difference==0 and max(abs(v) for v in differences.values())<1e-5
    save(a.run/'direct_validation_verification.json',report)
    print(json.dumps(report),flush=True)
    if not report['passed']: raise ValueError('Direct replay verification failed')


if __name__=='__main__':
    torch.set_num_threads(4)
    main()
