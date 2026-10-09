"""Source and retained-policy checks; hardware acceptance is separate."""
from pathlib import Path
import hashlib,json,re
root=Path(__file__).resolve().parents[2]
def read(p): return (root/p).read_text(encoding='utf-8-sig')
def sha(data): return hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
contract=json.loads(read('scripts/v08/source-contract.json'))
for p,v in contract.items(): assert sha((root/p).read_bytes())==v['after'],p
retained=json.loads(read('scripts/v08/retained.json'))
for p,h in retained['files'].items(): assert sha((root/p).read_bytes())==h,('Retained source changed',p)
base='runtime/open-shaders/src/Features/Upscaling/'
fov=read(base+'FoveatedRender.cpp');start=fov.index('void FoveatedRender::UpdateAdaptiveState(');end=fov.index('void FoveatedRender::LatchQualityMode()',start)
assert sha(fov[start:end].encode())==retained['controller_body_sha256'],'Controller body changed'
fields=re.findall(r'X\((\w+)\)',fov[fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'):fov.index('template <typename BasicJsonType>',fov.index('#define OPENNR_FOVEATED_SETTINGS_FIELDS'))]);assert len(fields)==len(set(fields))
for name in ('Enabled','Expansion','Compression','Curve','Strength','Fade'): assert 'neuralFeather'+name in fields
header=read(base+'FoveatedRender.h');assert 'bool neuralFeatherEnabled = false;' in header
integration=read(base+'NeuralRendering/Integration.cpp');renderer=read(base+'NeuralRendering/Renderer.cpp');params=read(base+'FoveatedRender/Params.cpp')
assert 'if (featherActive)' in integration and 'tuning.singlePassLadder = true;' in integration
assert 'adaptiveActivePasses > 0' in params and 'neuralFeatherExpansion > 0.0f' in params
for token in ('tuning.stereoAtlas = true;', 'tuning.multiPass = 0;', 'tuning.stabilizeMode = 0;', 'tuning.temporalReuseCadence = 0;'): assert token in integration
assert 'tuning.stereoAtlas && atlasResult != StereoAtlasResult::Applied' in renderer
assert 'featherEnabled ? resourceColorWidth + 2u' in renderer and 'featherEnabled ? resourceColorHeight + 2u' in renderer
assert 'FeatherGeometry::MakeAxis' in integration and 'neuralCorePlan' in params
assert 'configureNeuralFeather' in read(base+'../Upscaling.cpp') and 'configureNeuralFeather' in read(base+'../RemoteControl/DevBenchBridge.cpp')
shader=read('runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/FeatherGuidesCS.hlsl')
for token in ('gPreviousLeft','gPreviousRight','StableDelta','!sourceValid ? raw','float(gPrevious.x + gLayout.w)'): assert token in shader
report={'changed_runtime_files':len(contract),'retained_files':len(retained['files']),'controller_body_unchanged':True,'default_off':True,'strict_single_atlas':True,'near_black_shader_unchanged':True,'hardware_acceptance':False}
(root/'audit-results').mkdir(exist_ok=True);(root/'audit-results/r8-source-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
