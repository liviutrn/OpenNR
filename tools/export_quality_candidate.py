"""Export a strictly loadable, inference-only quality candidate with provenance."""
import argparse
import hashlib
import json
from pathlib import Path
import torch
from opennr_student import load_student

p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
model,source=load_student(a.checkpoint,'cpu')
payload={k:source[k] for k in ('architecture','config','model','cache','step')}
payload['provenance']=dict(source_checkpoint=str(a.checkpoint.resolve()),source_sha256=hashlib.sha256(a.checkpoint.read_bytes()).hexdigest(),role='Offline quality candidate; not teacher-equivalent or live accepted')
a.output.parent.mkdir(parents=True,exist_ok=True)
tmp=a.output.with_suffix('.tmp');torch.save(payload,tmp);tmp.replace(a.output)
exported,_=load_student(a.output,'cpu')
if any(not torch.equal(value,exported.state_dict()[key]) for key,value in model.state_dict().items()):raise ValueError('Exported model state differs')
result=dict(path=str(a.output.resolve()),sha256=hashlib.sha256(a.output.read_bytes()).hexdigest(),parameters=sum(x.numel() for x in model.parameters()),architecture=source['architecture'],step=source['step'],exact_state=True)
a.output.with_suffix('.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
