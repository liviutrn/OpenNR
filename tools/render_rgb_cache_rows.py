"""CPU-only input/teacher inspection for explicitly named non-test sequences."""
import argparse
import json
from pathlib import Path
import numpy as np
from audit_conditioning_content import picture,sheet


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--sequence',action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    rows=json.loads((a.cache/'rows.json').read_text())
    rgb=np.load(a.cache/'rgb.npy',mmap_mode='r')
    cells=[]
    for seq in a.sequence:
        for i,r in enumerate(rows):
            if r['sequence_id']!=seq or r['frame_id']!=32:continue
            if r['split']=='test':raise ValueError('Test inspection prohibited')
            source,target=np.asarray(rgb[i],dtype=np.float32).transpose(0,2,3,1)/255
            label=f'{seq[-6:]} E{r["eye"]}'
            cells.extend([(label+' input',picture(source)),(label+' teacher',picture(target)),
                          (label+' absolute effect x4',picture(np.abs(target-source)*4))])
    if not cells:raise ValueError('No matching rows')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    sheet(cells,3,a.output,384)


if __name__=='__main__':main()
