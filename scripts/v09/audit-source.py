"""Validate the rebuilt runtime and retained working contracts, separately from hardware acceptance."""
from pathlib import Path
import hashlib
import json
import re

root = Path(__file__).resolve().parents[2]
def read(path):
    return (root / path).read_text(encoding='utf-8-sig')
def sha(path):
    return hashlib.sha256((root / path).read_bytes().replace(b'\r\n', b'\n')).hexdigest()

contract = json.loads(read('scripts/v09/source-contract.json'))
for path, versions in contract.items():
    assert sha(path) == versions['after'], ('Rebuilt source differs', path)
retained = json.loads(read('scripts/v09/retained.json'))
for path, expected in retained['files'].items():
    assert sha(path) == expected, ('Retained working source changed', path)
base = 'runtime/open-shaders/src/Features/Upscaling/'
renderer = read(base + 'NeuralRendering/Renderer.cpp')
params = read(base + 'FoveatedRender/Params.cpp')
fov = read(base + 'FoveatedRender.cpp')
integration = read(base + 'NeuralRendering/Integration.cpp')
controller = re.search(r'void FoveatedRender::UpdateAdaptiveState\([^\n]*\)\n\{.*?\n\}', fov, re.S).group()
assert hashlib.sha256(controller.encode()).hexdigest() == retained['controller_sha256']
assert 'FeatherPlan::Make' in params and 'FeatherPlan::Make' in fov
assert 'IsNeuralFeatherRouteEnabled()' in params
assert 'return !NeuralRendering::Renderer::Instance().IsFailureLatched()' in fov
assert 'ShaderDetailMask::ProtectRenderRectangles(profile, plan.sr)' in fov
assert 'FeatherPlan::Contains(sr.output, core.output)' in integration
assert 'FeatherPlan::Mapping(core, sr' in integration
assert 'featherPackCS, featherResolveCS' in renderer
assert 'feather packing shader compile/load' in renderer
assert 'feather texture extent/view contract' in renderer
assert 'featherModelCS' not in renderer
assert 'if (!eyes[0].featherEnabled && !ladderAtlasGuidesCS.Get' in renderer
start = renderer.index('bool DispatchFeatherModel(')
end = renderer.index('bool DispatchModelInput(', start)
assert 'EnsureModelResolutionResources' not in renderer[start:end]
assert 'if (globals::game::isVR && ImGui::CollapsingHeader("CSX shader detail mask"' in fov
assert fov.index('CSX shader detail mask') < fov.index('if (settings.neuralRenderingEnabled)', fov.index('void FoveatedRender::DrawSettings'))
lighting = read('runtime/open-shaders/package/Shaders/Lighting.hlsl')
assert lighting.count('if (SharedData::hairSpecularSettings.Enabled && shaderDetailActive) {') == 3
for name in ('FeatherModelCS.hlsl', 'FeatherGuidesCS.hlsl'):
    text = read('runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/' + name)
    assert '#include "Upscaling/NeuralRendering/FeatherMap.hlsli"' in text
    assert '#include "FeatherMap.hlsli"' not in text
model = read('runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/FeatherModelCS.hlsl')
assert '#if !defined(FEATHER_RESOLVE)' in model and 'if (gOptions.x == 0.0)' not in model
harness = read('scripts/v09/test-packaged-warp.cpp')
assert 'Util::CustomInclude include(file)' in harness and 'D3D_COMPILE_STANDARD_FILE_INCLUDE' not in harness
assert 'D3D11_CREATE_DEVICE_DEBUG' in harness and 'zeroCalibration' in harness
assert 'StereoAtlasPackColorCS.hlsl' in harness
report = dict(rebuilt_runtime_files=len(contract), retained_files=len(retained['files']),
              controller_unchanged=True, central_frame_plan=True, explicit_pack_resolve=True,
              quantized_mask_protection=True, coherent_hair_material=True,
              packaged_production_loader_validation_required=True, hardware_acceptance=False)
(root / 'audit-results').mkdir(exist_ok=True)
(root / 'audit-results/r9-source-audit.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
