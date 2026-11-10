#!/usr/bin/env python3
"""CI release gate for generated Faithful NR codec and TriView safety.

This validates actual patched code and synthetic HDR math, not NVIDIA inference.
Actual NGX performance and in-game quality require a GPU/game validation later.
"""
from pathlib import Path
import math
import sys

root=Path(sys.argv[1]).resolve()
read=lambda p:(root/p).read_text(encoding="utf-8")

settings=read("src/settings.hpp")
state=read("src/settings.cpp")
decoder=read("src/nr_codec_shader.hpp")
nr=read("src/dlss_nr.cpp")
budget=read("uevr/nr_lite_budget_policy.hpp")
ui=read("uevr/scripts/cheeky_foveated_dlss.lua")

checks={
 "actual inference capped at two": "const auto requested_passes = std::clamp(settings.nr_passes, 1U, 2U);" in nr,
 "stored pass setting capped at two": "nr_passes = std::clamp(settings.nr_passes, 1U, 2U);" in state,
 "retire inactive features behind existing fences": "if ((mask & view.source_role) == 0U) view.retired = true;" in nr and "collect_retired_views();" in nr,
 "separate second-pass history": "pass_frame.view_id ^= (1ULL << 63U)" in nr,
 "budget checks pass two tuning": "old_tuning.nr_style != new_tuning.nr_style" in budget,
 "fovea pair survives 4-source layout": "if (n != 3U && n != 4U) return 0U;" in state,
 "ambiguous fourth source skipped": "if (n == 3U)" in state and "unknown whether this is desktop or periphery" in state,
 "all GPU root constants updated": "Num32BitValues = 48U;" in nr and "SetComputeRoot32BitConstants(2U, 48U" in nr,
 "codec root block shape": "48U * sizeof(std::uint32_t)" in decoder,
 "legacy decoder remains": "UpgradeToneMap(original, proxy, neural)" in decoder,
 "faithful decoder can be selected": "FaithfulUpgrade(original, proxy, neural, proxy_position)" in decoder,
 "HDR input soft shoulder": "FaithfulShoulder(linear_color)" in decoder,
 "shader-only controls exclude NR history": "settings.nr_hdr_transfer_strength," not in read("src/nr_parameters.hpp").split("inline NgxResult neural_scaling_ratio_callback")[1],
 "UI switches Legacy and Faithful": 'NrReconstructionMode' in ui and 'NrEditChroma' in ui,
 "no temporal cache in faithful reconstruction": "Reproject" not in decoder and "FrameCache" not in decoder,
 "exposure metadata logged": "[CheekyNR][Exposure]" in nr and "GPUwhiteFormula" in nr,
}
for name,ok in checks.items():
 print(("PASS" if ok else "FAIL"),name)
if not all(checks.values()):raise SystemExit("Faithful NR static contract failed")

w=(.2126,.7152,.0722)
def lum(v):return sum(a*b for a,b in zip(w,v))
def shoulder(c,k):
 y=lum(c)
 v=y if y<=k else k+(1-k)*(1-math.exp(-(y-k)/(1-k)))
 z=[x*v/max(y,1e-6) for x in c]
 mx=max(z)
 return [x/max(1,mx) for x in z]
for c in [(4,.8,.1),(.02,.7,.15),(10,10,10),(.00001,.001,.00001)]:
 out=shoulder(c,.75)
 assert all(math.isfinite(x) and 0<=x<=1.00001 for x in out)
 assert max(out)>0
 if c[0] and c[1]:
  assert abs((out[0]/out[1])-(c[0]/c[1]))<.00001
print("PASS HDR shoulder preserves positive RGB ratios without per-channel clipping")
print("PASS SOURCE PATCHES AND SYNTHETIC HDR FIXTURES (NOT NVIDIA GPU EVALUATION)")
