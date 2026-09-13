"""Offline input-only YuNet crop-candidate audit; does not modify training."""
import argparse,hashlib,json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw


def row_manifest_digest(rows, meta):
    """Reproduce the source cache's row identity convention.

    Legacy caches used the original sorted JSON encoding. The merged schema-3
    cache preserves its compact merge-time encoding so its provenance hash and
    every downstream training-only audit continue to refer to the same rows.
    """
    if meta.get('schema') == 3 and meta.get('source_type') == 'merged_compatible_spatial_caches':
        payload=json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode('utf-8')
    else:
        payload=json.dumps(rows,sort_keys=True).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def load_input_image(row):
    """Load an audited RGB input from either PNG or raw RGBA capture storage."""
    path=Path(row['paths']['input'])
    if path.name.endswith('.raw.bin'):
        w,h=map(int,row['color_size'])
        if path.stat().st_size != w*h*4:
            raise ValueError(f'Raw input size changed: {path}')
        rgba=np.memmap(path,mode='r',dtype=np.uint8,shape=(h,w,4))
        return Image.fromarray(np.ascontiguousarray(rgba[:,:,:3]))
    return Image.open(path).convert('RGB')

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--all',action='store_true');a=p.parse_args()
    cv2.setNumThreads(2)
    rows=json.loads((a.cache/'rows.json').read_text());meta=json.loads((a.cache/'complete.json').read_text())
    digest=row_manifest_digest(rows,meta)
    if digest!=meta['rows_sha256']:raise ValueError('Row identity mismatch')
    selected=[];seen=set()
    for i,row in enumerate(rows):
        if row['split']!='train':continue
        if not a.all and row['sequence_id'] in seen:continue
        selected.append(i);seen.add(row['sequence_id'])
    detector=cv2.FaceDetectorYN.create(str(a.model),'',(640,640),.85,.3,5000)
    a.output.mkdir(parents=True,exist_ok=True);records=[];tiles=[]
    for i in selected:
        row=rows[i];im=load_input_image(row);w,h=im.size
        scale=640/max(w,h);size=(round(w*scale),round(h*scale));im=im.resize(size)
        bgr=np.asarray(im)[:,:,::-1].copy();detector.setInputSize(size);_,faces=detector.detect(bgr)
        boxes=[];draw=ImageDraw.Draw(im)
        if faces is not None:
            for face in faces:
                x,y,bw,bh=map(float,face[:4]);score=float(face[-1])
                box=[max(0,x*w/size[0]),max(0,y*h/size[1]),min(w,(x+bw)*w/size[0]),min(h,(y+bh)*h/size[1])]
                if box[2]<=box[0] or box[3]<=box[1]:continue
                boxes.append(dict(xyxy=box,confidence=score));draw.rectangle((x,y,x+bw,y+bh),outline='lime',width=2)
        records.append(dict(row=i,sequence=row['sequence_id'],eye=row['eye'],boxes=boxes))
        if boxes and len(tiles)<24:
            tile=Image.new('RGB',(320,370),'#181818');im.thumbnail((320,345));tile.paste(im,((320-im.width)//2,20));ImageDraw.Draw(tile).text((5,3),f'row {i} / {len(boxes)} faces',fill='white');tiles.append(tile)
    result=dict(rows_sha256=digest,model_sha256=hashlib.sha256(a.model.read_bytes()).hexdigest(),model_source='https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet',opencv=cv2.__version__,training_only=True,input_only=True,selection='all training eyes' if a.all else 'first training eye per sequence',rows=len(records),rows_with_faces=sum(bool(r['boxes']) for r in records),records=records)
    (a.output/'result.json').write_text(json.dumps(result,indent=2))
    if tiles:
        sheet=Image.new('RGB',(1280,370*((len(tiles)+3)//4)),'#181818')
        for j,tile in enumerate(tiles):sheet.paste(tile,((j%4)*320,(j//4)*370))
        sheet.save(a.output/'detections.jpg',quality=93)
    print(json.dumps({k:v for k,v in result.items() if k!='records'}))

if __name__=='__main__':main()
