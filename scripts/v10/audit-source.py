"""Verify r10 integration and unchanged r7 gaze/history contracts."""
import hashlib,json,re
from pathlib import Path
root=Path(__file__).resolve().parents[2]
def read(name):return (root/name).read_text(encoding='utf-8-sig')
def digest(name):return hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
contract=json.loads(read('scripts/v10/source-contract.json'))
for name,value in contract.items(): assert digest(name)==value['after'],('r10 postimage mismatch',name)
retained=json.loads(read('scripts/v07/retained-gaze.json'))
modified=set(contract)
for name,value in retained.items():
    if name not in modified: assert digest(name)==value,('retained gaze/history changed',name)
prefix='runtime/open-shaders/src/Features/Upscaling/'
fov=read(prefix+'FoveatedRender.cpp');header=read(prefix+'FoveatedRender.h')
integration=read(prefix+'NeuralRendering/Integration.cpp');renderer=read(prefix+'NeuralRendering/Renderer.cpp')
page=read('runtime/open-shaders/src/Features/Upscaling.cpp')
schema=read('runtime/open-shaders/src/Features/RemoteControl/DevBenchBridge.cpp')
ladder=read(prefix+'NeuralRendering/SinglePassLadder.h')
for name in ('neuralRenderingCropDrop','cropDrop'):
    assert name not in fov+header+page+schema,('retired control remains',name)
fields=fov[fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'):fov.index('template <typename BasicJsonType>',fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'))]
names=re.findall(r'X\((\w+)\)',fields);assert len(names)==len(set(names))
for stage,default in zip(range(2,6),(90,80,70,60)):
    name=f'neuralRenderingStage{stage}Crop'
    assert name in names and f'{name} = {default};' in header
    assert f'stage{stage}Crop' in page+schema
assert 'cropConfig.targetCoverage = adaptiveCropTargetCoverage;' in fov
assert 'committedRenderCrop == adaptiveCropTargetCoverage' in fov
assert 'if (adaptiveUpdateFrame == frame) return;' in fov
assert 'Force stage 6 (NR off)' in fov
assert '60,85' not in ladder and '60,70' not in ladder
assert '{100,100,false}' in ladder
assignments=re.findall(r'tuning\.modelResolutionPercent\s*=\s*([^;]+);',integration)
assert assignments and all(value.strip() in ('100','100u') for value in assignments),assignments
normalize=re.search(r'NormalizeModelResolution\(std::uint32_t\)\s*\{([^}]+)\}',renderer).group(1)
assert normalize.strip()=='return 100;'
assert 'tuning.stereoAtlas && atlasResult != StereoAtlasResult::Applied' in renderer
pack=renderer[renderer.index('bool PackLadderGuides'):renderer.index('StereoAtlasResult ApplyStereoAtlasNative')]
assert 'CSSetShaderResources(0, 6, sources)' in pack and 'CSSetShaderResources(0, 6, nullSources)' in pack
assert 'CSSetUnorderedAccessViews(0, 3, targets' in pack and 'CSSetUnorderedAccessViews(0, 3, nullTargets' in pack
assert 'CS_GPU_PASS("NeuralRendering::LadderAtlasGuides")' in pack
shader=read('runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/ResultShapingCS.hlsl')
assert shader.index('gHistoryOutput[pixel]')<shader.index('gNearBlackProtection > 0.0')<shader.index('delta * saturate(gResumeBlendAlpha)')
old=read('scripts/v10/reference-guides.hlsl')
new=read('runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/LadderAtlasGuidesCS.hlsl')
anchor='\tconst uint rightStart = gCurrent.z + gFlags.y;'
assert old[old.index(anchor):].rstrip()==new[new.index(anchor):].rstrip(),'motion/depth arithmetic changed'
report={'reviewed_r7_parent':'1620bde5b9f9f504046c16056fa12c17efac74f1','source_files':len(contract),
 'unchanged_gaze_history_files':len(set(retained)-modified),'nr_resolution_fixed_100':True,
 'stage_defaults':[100,90,80,70,60,100],'stage6_nr_off':True,'exact_motion_depth_arithmetic_retained':True,
 'gpu_timings_and_headset_acceptance':False}
(root/'audit-results').mkdir(exist_ok=True)
(root/'audit-results/r10-source-audit.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
