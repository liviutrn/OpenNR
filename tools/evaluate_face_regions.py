"""Evaluate candidate checkpoints inside validation-only detected face regions."""
import argparse,hashlib,json,math,time
from collections import defaultdict
from pathlib import Path
import numpy as np
import torch
from evaluate_student import load_eye
from opennr_student import load_student
from train_student import atomic_json

@torch.inference_mode()
def evaluate(path,rows,contexts,faces,cache_hash):
    model,ckpt=load_student(path,'cuda')
    if ckpt['cache']['rows_sha256']!=cache_hash:raise ValueError('Dataset mismatch')
    sums=np.zeros(8,dtype='f8');by_seq=defaultdict(list);records=[];start=time.time()
    for item in faces['records']:
        row=rows[item['row']];x,t,g,c=load_eye(row,contexts[item['row']])
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(x,g,c)
        err=(pred.float()-t);base=(x-t);h,w=row['color_size'][1],row['color_size'][0];mask=np.zeros((h,w),dtype=bool)
        for box in item['boxes']:
            x1,y1,x2,y2=map(lambda z:int(round(z)),box['xyxy']);mask[max(0,y1):min(h,y2),max(0,x1):min(w,x2)]=True
        changed=(base.abs().mean(1,keepdim=True)>.05)
        fm=torch.from_numpy(mask).to('cuda',non_blocking=True)[None,None]
        face_count=int(mask.sum())*3;changed_count=int((mask & changed[0,0].cpu().numpy()).sum())*3
        values=np.array([err.abs().mul(fm).sum().item(),base.abs().mul(fm).sum().item(),err.square().mul(fm).sum().item(),err.abs().mul(fm*changed).sum().item(),base.abs().mul(fm*changed).sum().item(),changed_count,face_count,err.numel()])
        sums+=values;record=dict(row=item['row'],sequence=item['sequence'],frame=item['frame'],eye=item['eye'],face_pixels=int(mask.sum()),face_mae=values[0]/max(1,values[6]),face_identity_mae=values[1]/max(1,values[6]),face_changed_mae=values[3]/max(1,values[5]) if changed_count else None)
        records.append(record);by_seq[item['sequence']].append(record['face_mae']);del x,t,g,c,pred,err,base,changed,fm
    result=dict(checkpoint=str(path),checkpoint_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),step=ckpt['step'],eyes=len(records),eyes_with_faces=sum(r['face_pixels']>0 for r in records),face_mae=sums[0]/max(1,sums[6]),face_identity_mae=sums[1]/max(1,sums[6]),face_changed_mae=sums[3]/max(1,sums[5]),changed_face_pixels=int(sums[5]),face_pixels=int(sums[6]),sequence_face_mae={k:float(np.mean(v)) for k,v in by_seq.items()},records=records,seconds=time.time()-start)
    del model;return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--faces',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--models',nargs='+',required=True);a=p.parse_args();torch.set_num_threads(4)
    cache=json.loads((a.cache/'complete.json').read_text());rows=json.loads((a.cache/'rows.json').read_text());contexts=np.load(a.cache/'context.npy',mmap_mode='r');faces=json.loads(a.faces.read_text())
    if faces['rows_sha256']!=cache['rows_sha256'] or faces['split']!='validation' or not faces['input_only']:raise ValueError('Validation face audit mismatch')
    results=[]
    for path in a.models:results.append(evaluate(path,rows,contexts,faces,cache['rows_sha256']));print(json.dumps({k:v for k,v in results[-1].items() if k!='records'}),flush=True)
    source_hash=hashlib.sha256(a.faces.read_bytes()).hexdigest();result=dict(face_audit_sha256=source_hash,model_source=faces['model_source'],scope='Validation-only detected input face regions; no face boxes used in training. Heuristic detector recall is unknown. Metrics pool detected-face pixels and report sequence means; not test, temporal or live-game acceptance.',results=results)
    a.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(a.output,result)

if __name__=='__main__':main()
