"""Compare frozen v1 and v2 candidates on VALIDATION only, with visible evidence."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
import torch
from torch.utils.data import DataLoader
from train_student import CachedPatches,evaluate,batch_to_device
from opennr_student import load_student
from perceptual_features import FeatureDistance
from evaluate_student import load_eye,pil

@torch.inference_mode()
def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--models',nargs='+',required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(4);feature=FeatureDistance().cuda().eval();dataset=CachedPatches(a.cache,'validation');loader=DataLoader(dataset,batch_size=8,pin_memory=True)
    models=[load_student(path,'cuda')[0] for path in a.models];results={}
    for path,model in zip(a.models,models):
        metrics=evaluate(model,loader,'cuda');fs=bs=0;n=0
        for b in loader:
            x,t,g,c=batch_to_device(b,'cuda')
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c);dist=feature(pred.float(),t);base=feature(x,t)
            fs+=dist.item()*len(x);bs+=base.item()*len(x);n+=len(x)
        metrics.update(feature_distance=fs/n,identity_feature_distance=bs/n);results[path]=metrics;print(path,json.dumps(metrics),flush=True)
    (a.output/'validation.json').write_text(json.dumps(results,indent=2))
    # Fixed patches cover each validation sequence's first eye, then an offset.
    chosen=[];seen=set()
    for i in range(len(dataset)):
        item=dataset[i]
        if item['seq'] not in seen:chosen.append(i);seen.add(item['seq'])
    for index in chosen:
        b=next(iter(DataLoader(torch.utils.data.Subset(dataset,[index]),batch_size=1)));x,t,g,c=batch_to_device(b,'cuda');ims=[pil(x)]
        for m in models:
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=m(x,g,c)
            ims.append(pil(pred))
        ims.append(pil(t));labels=['Input']+[f'{Path(v).parent.name}/{Path(v).stem}' for v in a.models]+['Teacher']
        sheet=Image.new('RGB',(512*len(ims),544),'#151a20');d=ImageDraw.Draw(sheet)
        for j,(label,im) in enumerate(zip(labels,ims)):sheet.paste(im,(512*j,32));d.text((512*j+8,8),label,fill='white')
        sheet.save(a.output/f'validation_patch_{index}.jpg',quality=96)
    rows=json.loads((a.cache/'rows.json').read_text());contexts=np.load(a.cache/'context.npy',mmap_mode='r');ids=[];seen=set()
    for i,r in enumerate(rows):
        if r['split']=='validation' and r['sequence_id'] not in seen:ids.append(i);seen.add(r['sequence_id'])
    for i in ids:
        x,t,g,c=load_eye(rows[i],contexts[i]);ims=[pil(x)]
        for m in models:
            with torch.autocast('cuda',dtype=torch.bfloat16):pred=m(x,g,c)
            ims.append(pil(pred))
        ims.append(pil(t))
        w,h=rows[i]['color_size'];cx,cy=int(.56*w),int(.36*h)
        face=Image.new('RGB',(512*len(ims),544),'#151a20');fd=ImageDraw.Draw(face)
        for j,(label,im) in enumerate(zip(labels,ims)):
            face.paste(im.crop((cx-256,cy-256,cx+256,cy+256)),(512*j,32));fd.text((512*j+8,8),label,fill='white')
        face.save(a.output/f'validation_detail_{i}.jpg',quality=96)
        sheet=Image.new('RGB',(480*len(ims),550),'#151a20');d=ImageDraw.Draw(sheet)
        for j,(label,im) in enumerate(zip(labels,ims)):im.thumbnail((480,518));sheet.paste(im,(480*j,32));d.text((480*j+8,8),label,fill='white')
        sheet.save(a.output/f'validation_eye_{i}.jpg',quality=96)
    print('VALIDATION COMPARISON COMPLETE',flush=True)

if __name__=='__main__':main()
