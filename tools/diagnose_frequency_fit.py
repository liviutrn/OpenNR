"""Windowed spectral teacher-effect fit on unchanged validation patches."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import torch
from torch.utils.data import DataLoader
from opennr_student import load_student
from train_student import CachedPatches, batch_to_device, atomic_json


@torch.inference_mode()
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();torch.set_num_threads(4)
    digest=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()
    model,checkpoint=load_student(a.checkpoint,'cuda')
    cache=json.loads((a.cache/'complete.json').read_text())
    if checkpoint['cache']['rows_sha256']!=cache['rows_sha256']:raise ValueError('Dataset mismatch')
    totals=torch.zeros(4,3,device='cuda',dtype=torch.float64)
    count=0;max_parseval=0.
    for batch in DataLoader(CachedPatches(a.cache,'validation'),batch_size=4,pin_memory=True):
        x,t,g,c=batch_to_device(batch,'cuda')
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c)
        h,w=x.shape[-2:]
        window=torch.hann_window(h,periodic=False,device='cuda')[:,None]*torch.hann_window(w,periodic=False,device='cuda')[None,:]
        residual=(pred.float()-x)*window;target=(t-x)*window
        if not torch.isfinite(residual).all():raise ValueError('Nonfinite output')
        pr=torch.fft.fft2(residual,norm='ortho');tr=torch.fft.fft2(target,norm='ortho')
        freq=torch.sqrt(torch.fft.fftfreq(h,device='cuda')[:,None]**2+torch.fft.fftfreq(w,device='cuda')[None,:]**2)
        boundaries=(0.,1/32,1/8,1/4,1.)
        for index,(lo,hi) in enumerate(zip(boundaries,boundaries[1:])):
            mask=(freq>=lo)&(freq<hi)
            totals[index,0]+=pr.abs().square()[...,mask].double().sum()
            totals[index,1]+=tr.abs().square()[...,mask].double().sum()
            totals[index,2]+=(pr*tr.conj()).real[...,mask].double().sum()
        spatial=target.square().double().sum();spectral=tr.abs().square().double().sum()
        max_parseval=max(max_parseval,float((spatial-spectral).abs()/spatial.clamp_min(1e-12)))
        count+=len(x)
    if max_parseval>1e-5:raise ValueError('FFT energy conservation failed')
    records=[];total_teacher=float(totals[:,1].sum())
    for label,(pp,tt,pt) in zip(('below_1_over_32','1_over_32_to_1_over_8','1_over_8_to_1_over_4','above_1_over_4'),totals.cpu().tolist()):
        records.append(dict(band_cycles_per_pixel=label,teacher_effect_energy_fraction=tt/total_teacher,
                            predicted_effect_rms_ratio=math.sqrt(pp/max(tt,1e-12)),
                            effect_cosine=pt/max(math.sqrt(pp*tt),1e-12),
                            error_energy_vs_identity=(pp+tt-2*pt)/max(tt,1e-12)))
    if hashlib.sha256(a.checkpoint.read_bytes()).hexdigest()!=digest:raise ValueError('Checkpoint changed')
    result=dict(checkpoint=str(a.checkpoint),sha256=digest,patches=count,bands=records,max_parseval_relative_error=max_parseval,
                scope='Hann-windowed teacher-minus-input and prediction-minus-input residuals on all validation patches. Ratios within each frequency band; not independent perceptual acceptance or native-eye inference.')
    a.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(a.output,result)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
