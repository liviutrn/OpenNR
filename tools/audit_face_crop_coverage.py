"""Measure actual deterministic training-crop intersections with detected faces."""
import argparse,json
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--faces',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--mixed-guides',type=Path);a=p.parse_args()
    sampler=None
    if a.mixed_guides:
        from face_patches import FacePatches
        sampler=FacePatches(a.cache,a.mixed_guides,a.faces)
    faces=json.loads(a.faces.read_text());rows=json.loads((a.cache/'rows.json').read_text());meta=json.loads((a.cache/'complete.json').read_text())
    if faces['rows_sha256']!=meta['rows_sha256'] or not faces['training_only'] or faces['selection']!='all training eyes':raise ValueError('Require full training-only face audit')
    ids=[i for i,r in enumerate(rows) if r['split']=='train'];mapping={r['row']:r['boxes'] for r in faces['records']}
    if len(mapping)!=len(ids) or set(mapping)!=set(ids):raise ValueError('Incomplete or duplicate mapping')
    hits=significant=total=0;face_row_hits=0;overlaps=[]
    for epoch in range(6):
        for j,ri in enumerate(ids):
            w,h=rows[ri]['color_size'];row_hit=False
            for slot in range(8):
                index=j*8+slot;rng=np.random.default_rng(np.random.SeedSequence([1947,epoch,index]))
                x=int(rng.integers((w-512)//4+1))*4;y=int(rng.integers((h-512)//4+1))*4
                if sampler is not None:x,y,_,_=sampler.box(index,epoch)
                # Maximum intersection avoids double counting overlapping detections.
                overlap=max((max(0,min(x+512,b['xyxy'][2])-max(x,b['xyxy'][0]))*max(0,min(y+512,b['xyxy'][3])-max(y,b['xyxy'][1]))/512**2 for b in mapping[ri]),default=0.)
                total+=1;hits+=overlap>0;significant+=overlap>=.1;row_hit|=overlap>0;overlaps.append(overlap)
            face_row_hits+=bool(mapping[ri]) and row_hit
    detected=sum(bool(v) for v in mapping.values())
    result=dict(training_eyes=len(ids),detected_face_eyes=detected,epochs=6,crops=total,
                crops_touching_detected_face_fraction=hits/total,
                crops_at_least_10_percent_face_fraction=significant/total,
                detected_face_eye_epochs_with_any_hit_fraction=face_row_hits/max(1,detected*6),
                mean_max_face_fraction_of_crop=float(np.mean(overlaps)),
                sampler='mixed_two_face_six_general' if sampler is not None else 'uniform',
                scope='Six epochs of seeded 512px crop sampling. Detected boxes are heuristic; missed faces are not counted. Maximum single-box intersection, not segmentation or union coverage.')
    a.output.write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

if __name__=='__main__':main()
