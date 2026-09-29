"""Create validation-only face boxes for evaluation; never used by training."""
import argparse,hashlib,json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    cv2.setNumThreads(2);rows=json.loads((a.cache/'rows.json').read_text());meta=json.loads((a.cache/'complete.json').read_text())
    digest=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    if digest!=meta['rows_sha256']:raise ValueError('Row identity mismatch')
    ids=[i for i,r in enumerate(rows) if r['split']=='validation'];detector=cv2.FaceDetectorYN.create(str(a.model),'',(640,640),.85,.3,5000)
    records=[]
    for i in ids:
        row=rows[i];im=Image.open(row['paths']['input']).convert('RGB');w,h=im.size;scale=640/max(w,h);size=(round(w*scale),round(h*scale));im=im.resize(size)
        bgr=np.asarray(im)[:,:,::-1].copy();detector.setInputSize(size);_,faces=detector.detect(bgr);boxes=[]
        if faces is not None:
            for face in faces:
                x,y,bw,bh=map(float,face[:4]);score=float(face[-1]);box=[max(0,x*w/size[0]),max(0,y*h/size[1]),min(w,(x+bw)*w/size[0]),min(h,(y+bh)*h/size[1])]
                if box[2]>box[0] and box[3]>box[1]:boxes.append(dict(xyxy=box,confidence=score))
        records.append(dict(row=i,sequence=row['sequence_id'],frame=row['frame_id'],eye=row['eye'],boxes=boxes))
    result=dict(rows_sha256=digest,model_sha256=hashlib.sha256(a.model.read_bytes()).hexdigest(),model_source='https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet',opencv=cv2.__version__,training_only=False,input_only=True,split='validation',rows=len(records),rows_with_faces=sum(bool(r['boxes']) for r in records),records=records)
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='records'}))

if __name__=='__main__':main()
