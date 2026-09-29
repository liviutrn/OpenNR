"""Run a bounded validation-selected comparison and longer refinement, sequentially."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from train_student import atomic_json

def main():
    p=argparse.ArgumentParser();p.add_argument('--cache',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    if (a.output/'pipeline_status.json').exists():
        raise ValueError('Experiment output already exists; choose a new directory to preserve checkpoints and frozen evidence')
    script=Path(__file__).with_name('train_student.py')
    experiments=[('guided_quality','guided',40,1600),('rgb_control','rgb',40,1600),('guided_fast','guided',24,1000)]
    results=[]
    for label,name,width,steps in experiments:
        dest=a.output/label;dest.mkdir(exist_ok=True)
        atomic_json(a.output/'pipeline_status.json',dict(state='training',current=label,completed=results,updated=time.time()))
        cmd=[sys.executable,str(script),'--cache',str(a.cache),'--output',str(dest),'--name',name,'--width',str(width),'--steps',str(steps),'--batch','8','--eval-every','200']
        print('START '+label,flush=True)
        with (dest/'console.log').open('w') as log:
            run=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
        if run.returncode:
            atomic_json(a.output/'pipeline_status.json',dict(state='failed',current=label,returncode=run.returncode,log=str(dest/'console.log')));raise RuntimeError(f'{label} failed; inspect console.log')
        status=json.loads((dest/'status.json').read_text());results.append(dict(label=label,name=name,width=width,steps=steps,validation_mae=status['best_validation_mae'],checkpoint=str(dest/'best.pt')))
        print(json.dumps(results[-1]),flush=True)
    winner=min(results,key=lambda x:x['validation_mae']);dest=a.output/'refined';dest.mkdir(exist_ok=True)
    atomic_json(a.output/'pipeline_status.json',dict(state='refining',selected_on_validation=winner,completed=results,updated=time.time()))
    cmd=[sys.executable,str(script),'--cache',str(a.cache),'--output',str(dest),'--name',winner['name'],'--width',str(winner['width']),'--steps','4000','--batch','8','--eval-every','200','--lr','0.00012','--resume',winner['checkpoint']]
    with (dest/'console.log').open('w') as log:run=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT)
    if run.returncode:raise RuntimeError('refinement failed; inspect console.log')
    status=json.loads((dest/'status.json').read_text());chosen=dest/'best.pt' if (dest/'best.pt').exists() else Path(winner['checkpoint'])
    result=dict(state='training_completed',comparisons=results,selected_before_refinement=winner,best_checkpoint=str(chosen),best_validation_mae=status['best_validation_mae'],test_evaluated=False,updated=time.time())
    atomic_json(a.output/'pipeline_status.json',result);print(json.dumps(result),flush=True)

if __name__=='__main__':main()
