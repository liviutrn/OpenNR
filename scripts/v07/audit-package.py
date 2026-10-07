"""Compare the compiled r7 package against the tested r6 archive, payload by payload."""
from pathlib import Path
import hashlib,json,shutil,struct,subprocess,os
root=Path.cwd(); seven=shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe'
assert Path(seven).exists()
archives={}; manifests={}
for revision in ('r6','r7'):
    candidates=list((root/'artifacts'/revision).glob('*.7z')); assert len(candidates)==1
    archive=candidates[0];archives[revision]={'name':archive.name,'size':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    subprocess.run([seven,'t',str(archive),'-bd'],check=True)
    output=root/'expanded'/revision
    subprocess.run([seven,'x',str(archive),'-o'+str(output),'-y','-bd'],check=True)
    manifests[revision]={p.relative_to(output).as_posix()+('/' if p.is_dir() else ''):{'size':0 if p.is_dir() else p.stat().st_size,'sha256':hashlib.sha256(b'' if p.is_dir() else p.read_bytes()).hexdigest()} for p in sorted(output.rglob('*'))}
old,new=manifests['r6'],manifests['r7']
added=sorted(set(new)-set(old));removed=sorted(set(old)-set(new));changed=sorted(p for p in set(old)&set(new) if old[p]!=new[p])
expected_removed=sorted(['SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json']+['Shaders/Upscaling/NeuralRendering/'+n+'.hlsl' for n in ('OutsideSeamApplyCS','OutsideSeamMapCS','OutsideSeamSmoothCS','OutsideToneApplyCS','OutsideToneMapCS','OutsideToneSmoothCS')])
assert not added, ('Unexpected additions',added)
assert removed==expected_removed, ('Unexpected removals',removed)
assert changed==['SKSE/Plugins/CommunityShaders.dll','Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl'], ('Unexpected modifications',changed)
assert not any(p.lower().endswith('nvngx_dlssnr.dll') for p in new)
source=root/'runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl'
assert new['Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl']['sha256']==hashlib.sha256(source.read_bytes()).hexdigest()
dll=(root/'expanded/r7/SKSE/Plugins/CommunityShaders.dll').read_bytes()
assert dll[:2]==b'MZ';offset=struct.unpack_from('<I',dll,60)[0];assert dll[offset:offset+4]==b'PE\0\0';assert struct.unpack_from('<H',dll,offset+4)[0]==0x8664
for marker in ('Adaptive Performance','Controller mode','Force stage 6 (NR off)','Crop reduction per step','Disable NR above (stage 5 only)','Re-enable NR below (stage 6 only)','configureAdaptivePerformance','configureNeuralBlackProtection','NR near-black protection'):
    assert marker.encode() in dll, ('New runtime control missing',marker)
for marker in ('configureOutsideTone','Start settings benchmark','startSettingsBenchmark','Outside NR tone transfer','NeuralRendering::OutsideToneMap','Force one-pass atlas'):
    assert marker.encode() not in dll, ('Retired runtime code still active',marker)
report={'build_commit':os.environ.get('GITHUB_SHA'),'build_run':os.environ.get('GITHUB_RUN_ID'),
        'archives':archives,'r6_entries':len(old),'r7_entries':len(new),
        'added':added,'removed':removed,'changed':changed,'all_other_r6_payloads_identical':True,
        'shader_matches_reviewed_source':True,'x64_dll_and_controls_verified':True,
        'archive_crc_verified':True,'nr_carrier_excluded':True,'hardware_gpu_timing_and_headset_acceptance':False}
(root/'audit-results').mkdir(exist_ok=True)
for name,data in (('r7-package-audit.json',report),('r7-manifest.json',new),('r6-manifest.json',old)):
    (root/'audit-results'/name).write_text(json.dumps(data,indent=2)+'\n')
print('PACKAGE_AUDIT_RESULT='+json.dumps(report,separators=(',',':')))
