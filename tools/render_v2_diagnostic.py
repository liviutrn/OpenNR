"""Display deliberately memorized TRAINING examples, not a generalization claim."""
import json
from pathlib import Path
import torch
from torch.utils.data import DataLoader,Subset
from PIL import Image,ImageDraw
from train_student import CachedPatches,batch_to_device
from opennr_student import load_student
from evaluate_student import pil

torch.set_num_threads(4);out=Path('out/student_v2_20260904/diagnostic');run=json.loads((out/'run.json').read_text());ds=CachedPatches('C:/OpenNR/TrainingCache/student_v1','train');m,_=load_student(out/'best.pt','cuda')
with torch.inference_mode():
    for i,b in enumerate(DataLoader(Subset(ds,run['diagnostic_indices']),batch_size=1)):
        x,t,g,c=batch_to_device(b,'cuda')
        with torch.autocast('cuda',dtype=torch.bfloat16):pred=m(x,g,c)
        sheet=Image.new('RGB',(1536,550),'#151a20');d=ImageDraw.Draw(sheet)
        for j,(label,im) in enumerate((('Training input',pil(x)),('Memorized diagnostic output',pil(pred)),('Teacher',pil(t)))):
            sheet.paste(im,(512*j,32));d.text((512*j+8,8),label,fill='white')
        sheet.save(out/f'training_example_{i}.jpg',quality=96)
print('Diagnostic visuals saved')
