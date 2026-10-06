"""Check generated v6 integration contracts; this does not execute the GPU backend."""
import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
parser.add_argument("--write-layout-cpp", type=Path)
args = parser.parse_args()
src = args.root / "runtime/open-shaders/src/Features/Upscaling"
shaders = args.root / "runtime/open-shaders/features/Upscaling/Shaders/Upscaling"

def require(condition, message):
    if not condition:
        raise SystemExit(message)

def read(path):
    return path.read_text(encoding="utf-8-sig")

renderer = read(src / "NeuralRendering/Renderer.cpp")
foveated = read(src / "FoveatedRender.cpp")
header = read(src / "FoveatedRender.h")
integration = read(src / "NeuralRendering/Integration.cpp")
gaze = read(src / "NativeOpenVRGaze.cpp")
require("adaptiveController" not in foveated + header + integration,
        "Inactive model controller still supplies runtime state")
require("if (adaptiveUpdateFrame == frame) return;" in foveated,
        "Controller has no engine-frame ownership guard")
require("cropConfig.hold = envelopeRejected || decisionsSuspended;" in foveated,
        "Crop actuator ignores rejected envelopes or suspended frames")
require("tuning.singlePassLadder && atlasResult != StereoAtlasResult::Applied" in renderer,
        "Strict atlas can silently substitute another route")
require("AtlasFeatureSlot(tuning.singlePassLadder ? 0u : tierIndex, passIndex)" in renderer,
        "Strict atlas does not share its compatible native feature")
require("preparedWriteback[eyeIndex] = writebackOutput;" in renderer,
        "Both eyes are not prepared before stereo writeback")
require('LatchFailure("stereo crop writeback", E_FAIL)' in renderer,
        "Stereo writeback failure is ignored")
for name in ("neuralRenderingLadderBudgetMs", "neuralRenderingLadderReserveMs", "neuralRenderingLadderHandoffMs"):
    require(f"X({name})" in foveated and name in header,
            f"Configuration does not serialize {name}")
require("gContinuousOrigin" not in gaze and "gDeadZonePercent" not in read(src / "GazeCropPolicy.h"),
        "Gaze policy still depends on global configuration")

require("NativeGuideMotionScale(inputs[0].motionVectorScaleX, modelWidth, colorWidth)" in renderer and
        "NativeGuideMotionScale(inputs[0].motionVectorScaleY, modelHeight, colorHeight)" in renderer,
        "Native atlas motion scale diverges from legacy guide-pixel contract")
ladder_shader = read(shaders / "NeuralRendering/LadderAtlasGuidesCS.hlsl")
require("unchanged ? raw" in ladder_shader and "!sourceValid ? raw" in ladder_shader,
        "Stationary/invalid atlas motion no longer preserves the source representation")
require("/ gModelPitch.xy : previousModel - currentModel" in ladder_shader,
        "Equal-layout crop motion still subtracts large model coordinates")
require("if (requested == 0.0f)" in read(src / "GazeCropPolicy.h"),
        "Zero gaze smoothing still adds hidden filtering")

tone = read(src / "NeuralRendering/OutsideTone.cpp")
tone_apply = read(shaders / "NeuralRendering/OutsideToneApplyCS.hlsl")
require('settings.outsideToneEnabled && (!fullEye || coverageCrop)' in integration,
        'Outside effect does not bypass full-eye/off routes')
require(integration.index('Renderer::Instance().ApplyOutsideTone(') < integration.index('context->CopyResource(Util::AsReal(total.texture), destination);'),
        'Outside effect runs after staged output was already committed')
require('CS_GPU_PASS("NeuralRendering::OutsideToneMap")' in tone and
        'CS_GPU_PASS("NeuralRendering::OutsideToneApply")' in tone,
        'New rendering pass lacks profiling')
require('CopyResource(' not in tone and 'ResetHistory' not in tone and 'LatchFailure' not in tone,
        'Outside effect adds a copy or changes native history/failure state')
require('if (radius <= 1.0) return;' in tone_apply and
        'if (all(local >= gInset) && all(local <= last)) return;' in tone_apply,
        'Outside shader can write the existing inside mask')
require('FrameIndex' not in tone_apply and 'source.a' in tone_apply,
        'Outside effect adds animated noise or changes alpha')
for name in ('Enabled', 'Brightness', 'Color', 'Width', 'Curve', 'Dither', 'BoundaryRamp', 'LimitStops', 'SampleInset', 'Mode', 'OffsetLimit', 'SampleWidth', 'Smoothing', 'EdgeProtection', 'Contrast', 'Nonlinear', 'Plateau', 'SampleFocus', 'ContrastReach'):
    require(f'X(outsideTone{name})' in foveated and f'outsideTone{name}' in header,
            f'Outside configuration does not serialize {name}')

require(renderer.count('outsideToneInputs[eyeIndex] =') == 3 and
        'outsideToneInputs = {};' in renderer,
        'Pre-feather tone source is stale or missing on a stereo output route')
require('writebackOutput == shapedOutput ? shapedOutputSRV : eye.handoff.color[eye.handoff.historyIndex].srv.Get()' in renderer,
        'Outside tone bypasses the actual adaptive handoff output')
require('gMode == 0u ?' in tone_apply and 'float3(uv,1)' in tone_apply,
        'Boundary estimator lost offset or legacy A/B behavior')
require('CS_GPU_PASS("NeuralRendering::OutsideToneSmooth")' in tone,
        'Correction-map smoothing lacks GPU profiling')
require('FrameIndex' not in read(shaders / 'NeuralRendering/OutsideToneMapCS.hlsl'),
        'Boundary fit adds animated sampling')

seam_apply = read(shaders / 'NeuralRendering/OutsideSeamApplyCS.hlsl')
require('if (radius <= 1.0) return;' in seam_apply and
        'if (all(local >= gInset) && all(local <= last)) return;' in seam_apply,
        'Targeted seam can modify the inside mask')
require('FrameIndex' not in seam_apply and 'source.a' in seam_apply and
        'gDestination[pixel]' in seam_apply and 'gDestination[' not in seam_apply.replace('gDestination[pixel]', ''),
        'Targeted seam changes alpha, animates noise or reads neighboring UAV pixels')
require('MakeRing(g, roi)' in tone and 'std::min(ring.totalPixels,16384u)' in tone,
        'Targeted outside dispatch is not compact')
require('td.ArraySize = 4' in tone and 'sizeof(SeamApplyConstants) == 160' in tone,
        'Targeted seam allocation contract missing')
for name in ('contrast', 'nonlinear', 'plateau', 'sampleFocus', 'contrastReach'):
    require(f'read("{name}"' in read(src.parent / 'Upscaling.cpp') and
            name in read(src.parent / 'RemoteControl/DevBenchBridge.cpp'),
            f'Targeted control lacks validated command/schema: {name}')

require('tuning.nearBlackProtection > 0.0f' in renderer,
        'Near-black protection depends on the ordinary shaping toggle')
for name in ('Protection', 'Threshold', 'LiftSoftness'):
    require(f'X(neuralRenderingNearBlack{name})' in foveated and f'neuralRenderingNearBlack{name}' in header,
            f'NR protection configuration not serialized: {name}')
result = read(shaders / 'NeuralRendering/ResultShapingCS.hlsl')
require(result.index('gHistoryOutput[pixel]') < result.index('gNearBlackProtection > 0.0'),
        'Black protection contaminates raw stabilization history')
require(result.index('delta = ShapeDelta') < result.index('gNearBlackProtection > 0.0'),
        'Black protection runs before user result shaping')
require('gBlackProtection' not in seam_apply and 'outsideToneBlackProtection' not in foveated + header + integration,
        'Retired outside black protection still active')
require('configureNeuralBlackProtection' in read(src.parent/'Upscaling.cpp') and
        'configureNeuralBlackProtection' in read(src.parent/'RemoteControl/DevBenchBridge.cpp'),
        'Inside protection lacks developer command/schema')

layout_cpp = ["#include <array>\n#include <cstdint>\nusing std::uint32_t;\n"]
contracts = [
    (src / "NeuralRendering/OutsideTone.cpp", "MapConstants", shaders / "NeuralRendering/OutsideToneMapCS.hlsl", 64),
    (src / "NeuralRendering/OutsideTone.cpp", "ApplyConstants", shaders / "NeuralRendering/OutsideToneApplyCS.hlsl", 96),
    (src / "NeuralRendering/OutsideTone.cpp", "MapConstants", shaders / "NeuralRendering/OutsideToneSmoothCS.hlsl", 64),
    (src / "NeuralRendering/OutsideTone.cpp", "MapConstants", shaders / "NeuralRendering/OutsideSeamMapCS.hlsl", 64),
    (src / "NeuralRendering/OutsideTone.cpp", "MapConstants", shaders / "NeuralRendering/OutsideSeamSmoothCS.hlsl", 64),
    (src / "NeuralRendering/OutsideTone.cpp", "SeamApplyConstants", shaders / "NeuralRendering/OutsideSeamApplyCS.hlsl", 160),
    (src / "CropMotion.cpp", "Constants", shaders / "FoveatedRender/CropMotionCS.hlsl", 32),
    (src / "NeuralRendering/Renderer.cpp", "ResultShapingConstants", shaders / "NeuralRendering/ResultShapingCS.hlsl", 160),
    (src / "NeuralRendering/Renderer.cpp", "LadderAtlasConstants", shaders / "NeuralRendering/LadderAtlasGuidesCS.hlsl", 160),
    (src / "NeuralRendering/Renderer.cpp", "ModelResolutionConstants", shaders / "NeuralRendering/ModelResolutionCS.hlsl", 64),
    (src / "NeuralRendering/Renderer.cpp", "GuideAlignmentConstants", shaders / "NeuralRendering/AlignGuidesCS.hlsl", 32),
    (src / "FoveatedRender/Core.cpp", "BlendCB", shaders / "FoveatedRender/SubrectBlendCS.hlsl", 80),
]
for cpp_path, name, hlsl_path, expected_bytes in contracts:
    cpp = read(cpp_path)
    match = re.search(r"struct\s+(?:alignas\([^)]*\)\s+)?" + name + r"\s*\{(.*?)\n\s*\};", cpp, re.S)
    require(match is not None, f"Missing CPU buffer {name}")
    body = match.group(1)
    cpu = []
    for field in re.finditer(r"(std::array<(float|std::uint32_t),\s*(\d+)>|float|std::uint32_t|uint32_t)\s+([^;]+);", body):
        kind = "float" if "float" in field.group(1) else "uint"
        count = int(field.group(3) or 1)
        declarations = re.sub(r"\{[^}]*\}", "", field.group(4)).split(",")
        cpu.extend([kind] * count * len(declarations))
    hlsl = re.sub(r"//[^\n]*", "", read(hlsl_path))
    hlsl_body = re.search(r"cbuffer\s+\w+[^\{]*\{(.*?)\};", hlsl, re.S).group(1)
    gpu = []
    for field in re.finditer(r"\b(float|uint)([1-4]?)\s+\w+\s*;", hlsl_body):
        count = int(field.group(2) or 1)
        if len(gpu) % 4 + count > 4:
            gpu.extend([None] * (4 - len(gpu) % 4))
        gpu.extend([field.group(1)] * count)
    require(cpu == gpu and len(cpu) * 4 == expected_bytes,
            f"CPU/HLSL component layout mismatch: {name}")
    layout_cpp.append(f"struct {name}_{len(layout_cpp)} {{ {body} }};\nstatic_assert(sizeof({name}_{len(layout_cpp)}) == {expected_bytes});\n")
rcas_header = read(src / "RCAS/RCAS.h")
map_function = re.search(r"static float MapSliderStrength\(float strength\)\s*\{(.*?)\n\t\}", rcas_header, re.S)
require(map_function is not None, "RCAS has no shared slider conversion")
for path in (src.parent / "Upscaling.cpp", src / "FoveatedRender/Postprocess.cpp"):
    require("RCAS::MapSliderStrength" in read(path), f"Sharpening path has independent mapping: {path}")
require("if (resetNeuralHistory) NeuralRendering::ResetHistory();" in read(src / "FoveatedRender/Core.cpp"),
        "SR-only renewal still forces NR history renewal")
require("Core::InvalidateTemporalState(!preserveAtlasHistory);" in read(src / "FoveatedRender/Modes.cpp"),
        "SR crop resource renewal does not respect atlas ownership")
layout_cpp.append("#include <algorithm>\n#include <cmath>\n#include <cassert>\n#include <limits>\n")
layout_cpp.append("float MapSliderStrength(float strength) {" + map_function.group(1) + "\n}\n")
layout_cpp.append("""int main() {
    assert(MapSliderStrength(0.0f) == 0.25f);
    assert(MapSliderStrength(1.0f) == 1.0f);
    assert(MapSliderStrength(2.0f) == 2.0f);
    assert(MapSliderStrength(3.0f) == 3.0f);
    assert(MapSliderStrength(100.0f) == 3.0f);
    assert(MapSliderStrength(-1.0f) == 0.25f);
    assert(MapSliderStrength(std::numeric_limits<float>::quiet_NaN()) == 0.25f);
}\n""")
if args.write_layout_cpp:
    args.write_layout_cpp.write_text("".join(layout_cpp), encoding="utf-8")
print("v6 integration contracts and twelve CPU/HLSL buffer layouts passed")
