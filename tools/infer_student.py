"""Run a trained student on one audited eye identified in the cache row manifest."""
import argparse,json
from pathlib import Path
import numpy as np
import torch
from opennr_student import load_student
from evaluate_student import load_eye,pil

def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--row',type=int,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    torch.set_num_threads(4);rows=json.loads((a.cache/'rows.json').read_text());contexts=np.load(a.cache/'context.npy',mmap_mode='r');model,_=load_student(a.checkpoint,'cuda')
    with torch.inference_mode():
        rgb,_,guides,context=load_eye(rows[a.row],contexts[a.row])
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=model(rgb,guides,context)
        a.output.parent.mkdir(parents=True,exist_ok=True);pil(pred).save(a.output)
    print(json.dumps(dict(output=str(a.output.resolve()),row=a.row,sequence=rows[a.row]['sequence_id'],eye=rows[a.row]['eye'])))

if __name__=='__main__':main()
