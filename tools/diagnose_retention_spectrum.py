"""Causal frame32 spectral error audit on every training sequence, both eyes."""
import argparse
import json
from pathlib import Path
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
    path=a.run/'best_all_cohorts.pt'
    verification=json.loads((a.run/'checkpoint_verification.json').read_text())['arms']['continuation']
    if sha(path)!=verification['sha256']:raise ValueError('Checkpoint changed')
    model,payload,*_=_load_parent(path)
    model.eval()
    report={'checkpoint_sha256':sha(path),'test_used':False,'frame':32,
        'scope':'All training sequences, both eyes, causal frame32. Unwindowed orthonormal FFT error energy; periodic-edge artifacts possible. Energy fractions are MSE, not additive MAE or perceptual quality.',
        'cohorts':{}}
    for label,root in zip(('prior','high_effect','renderer_pilot'),payload['run']['cohorts']):
        cache=AlignedCohort(Path(root),'train')
        totals=torch.zeros(4,3,device='cuda',dtype=torch.float64)
        count=0;absolute=0.;spatial_energy=0.
        for keys,arrays in cache.stream_batches(4):
            rgb,t,g,c=_device_batch(arrays)
            rgb=rgb.float()/255;t=t.float()/255;g=g.float();c=c.float();state=None
            for f in range(32):
                with torch.autocast('cuda',dtype=torch.bfloat16):
                    pred,state=model.forward_temporal(rgb[:,f],g[:,f],c[:,f],state)
            pred=pred.float();target=t[:,31];source=rgb[:,31]
            error=pred-target
            if not torch.isfinite(error).all():raise ValueError('Nonfinite error')
            ep=torch.fft.fft2(error,norm='ortho')
            effect=torch.fft.fft2(target-source,norm='ortho')
            h,w=error.shape[-2:]
            radius=(torch.fft.fftfreq(h,device='cuda')[:,None]**2+torch.fft.fftfreq(w,device='cuda')[None,:]**2).sqrt()
            for i,(lo,hi) in enumerate(zip((0.,1/32,1/8,1/4),(1/32,1/8,1/4,1.))):
                mask=(radius>=lo)&(radius<hi)
                totals[i,0]+=ep.abs().square()[...,mask].double().sum()
                totals[i,1]+=effect.abs().square()[...,mask].double().sum()
                totals[i,2]+=mask.sum()*len(keys)*3
            absolute+=float(error.abs().double().sum());spatial_energy+=float(error.square().double().sum())
            count+=len(keys)
            save(a.output/'status.json',{'state':'evaluating','cohort':label,'eyes':count,'total':len(cache.streams)})
            if count%40==0:print(json.dumps({'cohort':label,'eyes':count}),flush=True)
        energy=float(totals[:,0].sum())
        relative=abs(energy-spatial_energy)/max(spatial_energy,1e-12)
        if relative>1e-5:raise ValueError('Parseval mismatch')
        report['cohorts'][label]={'eyes':count,'mae':absolute/(count*3*h*w),'parseval_relative_error':relative,
          'bands':[{'cycles_per_pixel':name,'error_energy_fraction':e/energy,'error_vs_identity_energy':e/max(t,1e-12),'teacher_effect_energy':t}
                   for name,(e,t,n) in zip(('below1/32','1/32to1/8','1/8to1/4','above1/4'),totals.cpu().tolist())]}
        save(a.output/'partial.json',report)
        print(json.dumps({label:report['cohorts'][label]}),flush=True)
    save(a.output/'result.json',report)
    save(a.output/'status.json',{'state':'complete','test_used':False})


if __name__=='__main__':main()
