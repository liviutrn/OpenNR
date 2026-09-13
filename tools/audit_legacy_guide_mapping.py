"""Training-only proof of cached-guide crop alignment, without changing caches."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from build_raw_crop_cache import _guide_arrays, _guide_tensor
from prepare_conditioning_pilot import aligned_guides, shrink, save, sha
from aligned_native_guides import sample_aligned


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cache',action='append',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    report=[]
    for root in a.cache:
        rows=json.loads((root/'rows.json').read_text())
        guides=np.load(root/'guides.npy',mmap_mode='r')
        train=[i for i,r in enumerate(rows) if r['split']=='train']
        chosen=[train[i] for i in np.linspace(0,len(train)-1,12,dtype=int)]
        samples=[]
        for i in chosen:
            row=rows[i]
            item={'row':i,'sequence':row['sequence_id'],'eye':row['eye'],'frame':row['frame_id']}
            try:
                values=_guide_arrays(row)
                legacy=_guide_tensor(row,*values,128,legacy_alignment=True)
                correct=sample_aligned(row,*values,128)
                item.update(legacy_reconstruction_max_difference=float(np.abs(legacy.astype(float)-guides[i]).max()),
                    corrected_difference_per_channel=np.abs(correct.astype(float)-guides[i]).mean((1,2)).tolist(),
                    native_source=row['artifacts']['depth']['source_rect'],
                    color_source=row['artifacts']['teacher']['source_rect'],
                    native_crop=row['artifacts']['depth']['crop_rect'],
                    color_crop=row['artifacts']['teacher']['crop_rect'])
            except FileNotFoundError as e:
                item['missing_raw']=str(e)
            samples.append(item)
        report.append({'cache':str(root.resolve()),'complete_sha256':sha(root/'complete.json'),
                       'rows':len(rows),'training_rows':len(train),'samples':samples})
    save(a.output,{'scope':'training rows only; no held-out target evaluation','caches':report})
    for r in report:
        valid=[s for s in r['samples'] if 'legacy_reconstruction_max_difference' in s]
        print(json.dumps({'cache':r['cache'],'sampled':len(r['samples']),'available':len(valid),
            'legacy_exact':sum(s['legacy_reconstruction_max_difference']==0 for s in valid),
            'corrected_changed':sum(max(s['corrected_difference_per_channel'])>0 for s in valid)}),flush=True)


if __name__=='__main__':
    torch.set_num_threads(1)
    main()
