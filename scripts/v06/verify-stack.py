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

layout_cpp = ["#include <array>\n#include <cstdint>\n"]
contracts = [
    (src / "CropMotion.cpp", "Constants", shaders / "FoveatedRender/CropMotionCS.hlsl", 32),
    (src / "NeuralRendering/Renderer.cpp", "ResultShapingConstants", shaders / "NeuralRendering/ResultShapingCS.hlsl", 160),
    (src / "NeuralRendering/Renderer.cpp", "LadderAtlasConstants", shaders / "NeuralRendering/LadderAtlasGuidesCS.hlsl", 112),
]
for cpp_path, name, hlsl_path, expected_bytes in contracts:
    cpp = read(cpp_path)
    match = re.search(r"struct\s+(?:alignas\([^)]*\)\s+)?" + name + r"\s*\{(.*?)\n\s*\};", cpp, re.S)
    require(match is not None, f"Missing CPU buffer {name}")
    body = match.group(1)
    cpu = []
    for field in re.finditer(r"(std::array<(float|std::uint32_t),\s*(\d+)>|float|std::uint32_t)\s+([^;]+);", body):
        kind = "float" if "float" in field.group(1) else "uint"
        count = int(field.group(3) or 1)
        declarations = field.group(4).split(",")
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
    layout_cpp.append(f"struct {name} {{ {body} }};\nstatic_assert(sizeof({name}) == {expected_bytes});\n")
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
print("v6 integration contracts and three CPU/HLSL buffer layouts passed")
