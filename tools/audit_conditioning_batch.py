"""Save structural gates first, then bounded parallel per-sequence content audits."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
from prepare_conditioning_pilot import save


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--after',required=True)
    p.add_argument('--expected-pass-count',type=int,choices=(1,2),default=1)
    a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    tools=Path(__file__).parent
    accepted,excluded,gates=[],[],[]
    for seq in sorted(a.root.glob('seq-*')):
        if seq.name<=a.after: continue
        errors=[]
        for tool,args in [('validate_capture.py',['--json']),('validate_temporal_capture.py',['--mode','crop','--expected-pass-count',str(a.expected_pass_count)])]:
            r=subprocess.run([sys.executable,str(tools/tool),*args,str(seq)],capture_output=True,text=True)
            report=json.loads(r.stdout)
            gates.append({'sequence':seq.name,'tool':tool,'report':report})
            if r.returncode or report.get('errors') or (tool.startswith('validate_temporal') and not report['temporal_ready']):
                errors.append({'tool':tool,'report':report})
        frames=[json.loads(line) for line in (seq/'frames.jsonl').read_text().splitlines()]
        if len(frames)!=64 or any(f['status']!='complete' for f in frames):
            errors.append({'reason':'not 64 complete frames'})
        if errors: excluded.append({'sequence':seq.name,'reasons':errors})
        else: accepted.append(seq)
        print(json.dumps({'sequence':seq.name,'accepted':not errors}),flush=True)
    save(a.output/'structural_gates.json',{'checks':gates,'excluded':excluded})
    def work(seq):
        dest=a.output/seq.name
        r=subprocess.run([sys.executable,str(tools/'audit_conditioning_content.py'),'--output',str(dest),str(seq)],
                         capture_output=True,text=True)
        if r.returncode: raise RuntimeError(seq.name+': '+r.stderr)
        print('content complete '+seq.name,flush=True)
        return json.loads((dest/'audit.json').read_text())['sequences'][0]
    with ThreadPoolExecutor(max_workers=3) as pool:
        reports=list(pool.map(work,accepted))
    save(a.output/'audit.json',{'sequences':reports,'excluded':excluded,'expected_pass_count':a.expected_pass_count,'scope':'Complete-clip content audit; failed clips preserved and excluded'})
    html='<h1>64-frame capture validation</h1><p>Complete clips only. See structural_gates.json for exclusions.</p>'
    html+=''.join(f'<p><a href="{s.name}/index.html">{s.name}</a></p>' for s in accepted)
    (a.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>64-frame capture validation</title>'+html,encoding='utf-8')
    print(json.dumps({'accepted':len(reports),'excluded':len(excluded)}),flush=True)


if __name__=='__main__': main()
