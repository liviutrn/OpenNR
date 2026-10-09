"""Verify the compiled R8 CSX-mask package against the reviewed R7 package."""
from pathlib import Path
import hashlib,json,shutil,struct,subprocess,os
root=Path.cwd();seven=shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe';assert Path(seven).exists()
archives={};manifests={}
for revision in ('r7','r8'):
    candidates=list((root/'artifacts'/revision).glob('*.7z'));assert len(candidates)==1
    archive=candidates[0];archives[revision]={'name':archive.name,'size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    subprocess.run([seven,'t',str(archive),'-bd'],check=True)
    output=root/'expanded'/revision;subprocess.run([seven,'x',str(archive),'-o'+str(output),'-y','-bd'],check=True)
    manifests[revision]={p.relative_to(output).as_posix()+('/' if p.is_dir() else ''):{'size':0 if p.is_dir() else p.stat().st_size,'sha256':hashlib.sha256(b'' if p.is_dir() else p.read_bytes()).hexdigest()} for p in sorted(output.rglob('*'))}
old,new=manifests['r7'],manifests['r8'];added=sorted(set(new)-set(old));removed=sorted(set(old)-set(new));changed=sorted(p for p in set(old)&set(new) if old[p]!=new[p])
expected_added=sorted(['Shaders/Upscaling/NeuralRendering/'+n for n in ('FeatherGuidesCS.hlsl','FeatherMap.hlsli','FeatherModelCS.hlsl')]+['Shaders/Common/ShaderDetailFoveation.hlsli'])
assert added==expected_added,('Unexpected additions',added)
assert not removed,('Unexpected removals',removed)
expected_changed=sorted(['SKSE/Plugins/CommunityShaders.dll','Shaders/Common/SharedData.hlsli','Shaders/Lighting.hlsl','Shaders/Water.hlsl','Shaders/WaterEffects/WaterParallax.hlsli'])
assert changed==expected_changed,('Unexpected modifications',changed)
assert not any(p.lower().endswith('nvngx_dlssnr.dll') for p in new)
for name in expected_added+[p for p in expected_changed if p.startswith('Shaders/')]:
    if name.startswith('Shaders/Upscaling/'): source=root/'runtime/open-shaders/features/Upscaling'/name
    elif name.startswith('Shaders/WaterEffects/'): source=root/'runtime/open-shaders/features/Water Effects'/name
    else: source=root/'runtime/open-shaders/package'/name
    assert new[name]['sha256']==hashlib.sha256(source.read_bytes()).hexdigest(),name
dll=(root/'expanded/r8/SKSE/Plugins/CommunityShaders.dll').read_bytes();offset=struct.unpack_from('<I',dll,60)[0]
assert dll[:2]==b'MZ' and dll[offset:offset+4]==b'PE\0\0' and struct.unpack_from('<H',dll,offset+4)[0]==0x8664
for marker in ('Experimental neural feather','Expand SR and neural feather','configureNeuralFeather','neuralFeatherStatus','NeuralRendering::FeatherDownsample','NeuralRendering::FeatherGuides','NeuralRendering::FeatherResolve','configureAdaptivePerformance','configureNeuralBlackProtection','CSX lighting detail mask','CSX water parallax mask','shaderDetailMaskStatus'):
    assert marker.encode() in dll,('Missing runtime integration',marker)
for marker in ('configureOutsideTone','Start settings benchmark','Force one-pass atlas'):assert marker.encode() not in dll
report={'build_commit':os.environ.get('GITHUB_SHA'),'build_run':os.environ.get('GITHUB_RUN_ID'),'archives':archives,'r7_entries':len(old),'r8_entries':len(new),'added':added,'removed':removed,'changed':changed,'all_other_r7_payloads_identical':True,'shader_detail_mask_controls_verified':True,'x64_dll_and_controls_verified':True,'archive_crc_verified':True,'nr_carrier_excluded':True,'hardware_gpu_timing_and_headset_acceptance':False}
(root/'audit-results').mkdir(exist_ok=True)
for name,data in [('r8-csx-mask-package-audit.json',report),('r8-manifest.json',new),('r7-manifest.json',old)]: (root/'audit-results'/name).write_text(json.dumps(data,indent=2)+'\n')
print('PACKAGE_AUDIT_RESULT='+json.dumps(report,separators=(',',':')))
