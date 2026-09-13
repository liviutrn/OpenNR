"""Evaluate a terminal quality experiment with the same patch/native/LPIPS gates."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess
import sys
from train_student import atomic_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    for field in ('run','cache','baseline','output'):setattr(a,field,getattr(a,field).resolve())
    state=json.loads((a.run/'status.json').read_text())
    if state['state']!='completed':raise ValueError('Evaluate immutable terminal run only')
    if (a.output/'complete.json').exists():raise ValueError('Completed evaluation exists; use a fresh output')
    a.output.mkdir(parents=True,exist_ok=True)
    candidates=[a.run/'best_mae.pt',a.run/'best_feature.pt']
    sources=[a.baseline]+candidates
    hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    def execute(script,args,label):
        atomic_json(a.output/'status.json',dict(state='evaluating',stage=label))
        with (a.output/f'{label}.log').open('w') as log:
            subprocess.run([sys.executable,str(root/'tools'/script),*map(str,args)],cwd=root,stdout=log,stderr=subprocess.STDOUT,check=True)
    execute('evaluate_lpips_validation.py',['--cache',a.cache,'--output',a.output/'lpips','--models',*sources],'lpips')
    execute('compare_v2.py',['--cache',a.cache,'--output',a.output/'comparison','--models',*sources],'comparison')
    native={}
    for path in sources:
        label='baseline' if path==a.baseline else path.stem
        dest=a.output/f'native_{label}'
        execute('evaluate_native_validation.py',['--cache',a.cache,'--checkpoint',path,'--output',dest],f'native_{label}')
        native[str(path)]=json.loads((dest/'result.json').read_text())
    if any(hashlib.sha256(Path(path).read_bytes()).hexdigest()!=digest for path,digest in hashes.items()):raise ValueError('Source checkpoint changed during evaluation')
    lpips=json.loads((a.output/'lpips/result.json').read_text())['results']
    patches=json.loads((a.output/'comparison/validation.json').read_text())
    from compare_native_sequences import compare
    sequence_comparisons={str(path):compare(native[str(a.baseline)],native[str(path)]) for path in candidates}
    atomic_json(a.output/'sequence_comparisons.json',sequence_comparisons)
    for path in candidates:
        execute('diagnose_frequency_fit.py',['--cache',a.cache,'--checkpoint',path,'--output',a.output/f'frequency_{path.stem}.json'],f'frequency_{path.stem}')
    records=[]
    for path in sources:
        key=str(path);n=native[key]
        if n['checkpoint_sha256']!=hashes[key] or lpips[key]['checkpoint_sha256']!=hashes[key]:raise ValueError('Evaluation checkpoint identity mismatch')
        records.append(dict(checkpoint=key,sha256=hashes[key],step=n['step'],patch_mae=patches[key]['mae'],native_mae=n['mae'],changed_mae=n['changed_region_mae'],lpips=lpips[key]['lpips']))
    result=dict(run=str(a.run),run_state=state,records=records,sequence_comparisons=sequence_comparisons,scope='Unchanged validation patches and 88 native eyes. No test evaluation, runtime benchmark, temporal or live-game acceptance.')
    rows='\n'.join(f'| {Path(r["checkpoint"]).parent.name}/{Path(r["checkpoint"]).stem} | {r["step"]:,} | {r["patch_mae"]:.6f} | {r["native_mae"]:.6f} | {r["changed_mae"]:.6f} | {r["lpips"]:.6f} |' for r in records)
    (a.output/'report.md').write_text(f'# {a.run.name} quality evaluation\n\n{result["scope"]}\n\nLower is better for all reported errors. Check the gallery before making a visual-quality claim; best patch MAE can differ from best native or perceptual quality.\n\n| Candidate | Step | Patch MAE | Native MAE | Changed-region MAE | LPIPS |\n|---|---:|---:|---:|---:|---:|\n{rows}\n',encoding='utf-8')
    page=['<!doctype html><meta charset="utf-8"><title>OpenNR quality comparison</title><style>body{background:#15191f;color:#eee;font:18px system-ui;margin:24px}img{max-width:100%}</style><h1>Quality experiment comparison</h1><p>Input / baseline / best patch-MAE / best feature / teacher. Validation only.</p>']
    for pattern in ('validation_detail_*.jpg','validation_eye_*.jpg'):
        for path in sorted((a.output/'comparison').glob(pattern)):page.append(f'<h2>{html.escape(path.stem)}</h2><img src="comparison/{html.escape(path.name)}">')
    (a.output/'gallery.html').write_text('\n'.join(page),encoding='utf-8')
    atomic_json(a.output/'complete.json',result)
    atomic_json(a.output/'status.json',dict(state='completed'))
    print(json.dumps(records,indent=2),flush=True)


if __name__=='__main__':main()
