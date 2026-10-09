"""Compile touched pixel shaders with a pairwise selection from upstream validation fixtures."""
from pathlib import Path
import argparse,itertools,json,shutil,subprocess,concurrent.futures
import yaml
root=Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser();ap.add_argument('--fxc',required=True);args=ap.parse_args()
source=root/'runtime/open-shaders';merged=root/'shader-smoke';merged.mkdir(exist_ok=True)
shutil.copytree(source/'package/Shaders',merged,dirs_exist_ok=True)
for feature in sorted((source/'features').iterdir()):
    if (feature/'Shaders').is_dir(): shutil.copytree(feature/'Shaders',merged,dirs_exist_ok=True)
shutil.copyfile(root/'scripts/csx-mask/TestMaskCS.hlsl',merged/'TestMaskCS.hlsl')
cases=[]
for runtime,suffix in [('VR','-vr'),('SE','')]:
    fixture=yaml.safe_load((source/f'.github/configs/shader-validation{suffix}.yaml').read_text())
    for shader in fixture['shaders']:
        if shader['file'] not in ('Lighting.hlsl','Water.hlsl'): continue
        config=shader['configs']['PSHADER'];entries=config['entries']
        def coverage(entry):
            keys=sorted(entry.get('defines',[]));return set((x,) for x in keys)|set(itertools.combinations(keys,2))
        remaining=set().union(*(coverage(e) for e in entries));chosen=[min(entries,key=lambda e:len(e.get('defines',[])))]
        remaining-=coverage(chosen[0])
        while remaining:
            entry=max(entries,key=lambda e:len(coverage(e)&remaining));new=coverage(entry)&remaining
            if not new: raise RuntimeError('Uncovered shader fixture')
            chosen.append(entry);remaining-=new
        for entry in chosen:
            for full in [True,False]:
                common=config['common_defines'] if full else [d for d in config['common_defines'] if d in ('PSHADER','VR','WATER','FOG') or d.startswith('SHADOWSPLITCOUNT=')]
                defines=sorted(set(common+entry.get('defines',[])) - {'D3DCOMPILE_DEBUG','D3DCOMPILE_SKIP_OPTIMIZATION'})
                cases.append((runtime,shader['file'],entry['entry'],'full' if full else 'base',defines))
out=root/'audit-results';out.mkdir(exist_ok=True)
def compile_case(item):
    index,case=item;runtime,file,entry,mode,defines=case
    cmd=[args.fxc,'/nologo','/O3','/T','ps_5_0','/E','main','/I',str(merged),'/Fo',str(merged/f'check-{index}.cso')]
    for define in defines: cmd+=['/D',define]
    cmd+=[str(merged/file)]
    run=subprocess.run(cmd,capture_output=True,text=True)
    record={'runtime':runtime,'file':file,'entry':entry,'feature_mode':mode,'defines':defines,'exit_code':run.returncode}
    (out/f'shader-{index}.log').write_text(run.stdout+run.stderr)
    if run.returncode: print('FAILED',record,run.stdout,run.stderr,flush=True)
    return record
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: records=list(pool.map(compile_case,enumerate(cases)))
(out/'csx-shader-compilation.json').write_text(json.dumps(records,indent=2)+'\n')
assert all(c['exit_code']==0 for c in records),'Touched shader permutation compilation failed'
print(f'{len(records)} optimized shader permutations compiled: VR/SE, Lighting/Water, full/base feature sets')
