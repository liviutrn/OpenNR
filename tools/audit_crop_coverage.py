"""Exact geometric pixel coverage of fixed versus epoch-varying training crops."""
import json
from pathlib import Path
import numpy as np
from dynamic_patches import DynamicPatches

root=Path('C:/OpenNR/TrainingCache/student_v1')
d=DynamicPatches(root,'C:/OpenNR/TrainingCache/dynamic_guides_v1')
plan=json.loads((root/'patches.json').read_text());fixed={}
for p in plan:
    if p['split']=='train':fixed.setdefault(p['row'],[]).append(p['box'])
seen=set();records=[]
for j,ri in enumerate(d.row_ids):
    row=d.rows[ri];seq=row['sequence_id']
    if seq in seen:continue
    seen.add(seq);w,h=row['color_size']
    inp=np.memmap(Path(row['paths']['input']).with_suffix('.raw.bin'),mode='r',dtype='u1',shape=(h,w,4))
    target=np.memmap(Path(row['paths']['teacher']).with_suffix('.raw.bin'),mode='r',dtype='u1',shape=(h,w,4))
    # Integer equivalent of mean absolute normalized RGB difference >0.05.
    changed=np.abs(inp[...,:3].astype(np.int16)-target[...,:3].astype(np.int16)).sum(2,dtype=np.int16)>=39
    changed_count=int(changed.sum())
    mask=np.zeros((h,w),dtype=bool)
    for x,y,pw,ph in fixed[ri]:mask[y:y+ph,x:x+pw]=True
    old=float(mask.mean());old_changed=float((mask&changed).sum()/changed_count) if changed_count else None
    mask.fill(False);fractions={};changed_fractions={}
    for epoch in range(10):
        d.set_epoch(epoch)
        for slot in range(8):
            x,y,pw,ph=d.box(j*8+slot);mask[y:y+ph,x:x+pw]=True
        if epoch in (0,4,9):
            fractions[str(epoch+1)]=float(mask.mean())
            changed_fractions[str(epoch+1)]=float((mask&changed).sum()/changed_count) if changed_count else None
    records.append(dict(row=ri,sequence=seq,fixed_coverage=old,dynamic_coverage_by_epoch=fractions,teacher_changed_pixels=changed_count,fixed_changed_coverage=old_changed,dynamic_changed_coverage=changed_fractions))
result=dict(scope='First training eye from each of 65 training sequences; exact union of covered native pixels, not model quality or target-change coverage',sequences=len(records),fixed_mean=float(np.mean([r['fixed_coverage'] for r in records])),dynamic_means={str(n):float(np.mean([r['dynamic_coverage_by_epoch'][str(n)] for r in records])) for n in (1,5,10)},records=records)
result['scope']='First training eye per training sequence; exact geometric and teacher-changed pixel coverage, not model quality. Changed mask uses mean absolute teacher/input RGB difference >0.05.'
result['fixed_changed_mean']=float(np.mean([r['fixed_changed_coverage'] for r in records if r['teacher_changed_pixels']]))
result['dynamic_changed_means']={str(n):float(np.mean([r['dynamic_changed_coverage'][str(n)] for r in records if r['teacher_changed_pixels']])) for n in (1,5,10)}
Path('out/quality_phase_20260905/crop_coverage.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:v for k,v in result.items() if k!='records'}))
