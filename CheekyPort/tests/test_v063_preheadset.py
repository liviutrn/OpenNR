#!/usr/bin/env python3
"""Post-generated source gates + CPU reference properties for opt-in preheadset probes."""
from pathlib import Path
import math,sys
r=Path(sys.argv[1]).resolve()
read=lambda p:(r/p).read_text(encoding="utf-8")
settings=read("src/settings.hpp")
shader=read("src/nr_codec_shader.hpp")
runtime=read("uevr/runtime.cpp")
dll=read("src/dlss_nr.cpp")
history=read("src/nr_parameters.hpp")
io=read("uevr/settings_io.cpp")
fields=read("uevr/settings_fields.inc")
ui=read("uevr/scripts/cheeky_foveated_dlss.lua")
policy=read("uevr/nr_lite_budget_policy.hpp")
checks={
 "all new settings have zero/off defaults":
    "nr_debug_view{0U}" in settings and "nr_dark_pedestal{0.0F}" in settings
    and "nr_create_flags_mode{0U}" in settings,
 "session-only debug is excluded from saved INIs":
    'std::string_view(name) != "NrDebugView"' in io
    and 'if (key == "NrDebugView") continue;' in io
    and 'candidate.nr_debug_view = 0U' in io,
 "no root-layout growth":
    "48U * sizeof(std::uint32_t)" in shader
    and "constants.padding[1] = settings.nr_debug_view;" in dll,
 "zero debug preserves ordinary decode":
    "DebugView == 0U ? final_color" in shader and "DebugView == 0U" in shader,
 "zero pedestal preserves faithful decode":
    "if (DarkPedestal > 0.0)" in shader
    and "result *= exp2(stops); // DEFAULT" in shader,
 "model gets NR-only effective flags":
    "settings.nr_create_flags_mode == 1U" in dll
    and 'parameters->Set("DLSS.Feature.Create.Flags", nr_flags)' in dll
    and "nr_flags," in dll,
 "flag experiment charged by existing admission policy":
    "requested.nr_create_flags_mode != current.nr_create_flags_mode" in policy,
 "scale-one encode matches previous path":
    "float4 proxy_source = LoadSource0Bilinear" in shader
    and "if (any(ProxySize < SourceSize))" in shader,
 "template look-only edits retain history":
    "if (needs_model_reset) reset_dlss_nr();" in runtime,
 "geometry feather not part of model history":
    "region.roundness," not in history and "region.transition," not in history
    and "region.width);" in history and "region.height);" in history,
 "runtime DLL logs path/version":
    "[CheekyNR][Runtime] path=" in dll and "VerQueryValueW" in dll,
 "new opt-ins visible in UI":
    "NrDebugView" in ui and "NrDarkPedestal" in ui
    and "NrCreateFlagsMode" in ui,
}
for k,v in checks.items():print(("PASS " if v else "FAIL ")+k)
if not all(checks.values()):raise SystemExit("Preheadset code contracts failed")

# CPU reference of pedestal branch ONLY; matches HLSL equations for luminance.
def stop_ratio(oy,py,ny,c,bright=1.0,dark=1.0,hi=0.0):
    assert c>0
    yt=max((oy+c)*(ny+c)/max(py+c,1e-6)-c,0.0)
    ss=math.log2(max(yt+c,1e-6)/max(oy+c,1e-6))
    weight=bright if ss>=0 else dark*(1-0.5*hi)
    ss=max(-2.,min(2.,ss*weight))
    return max((oy+c)*(2**ss)-c,0.)
for o in (0,1e-4,0.01,0.5,4,50):
    result=stop_ratio(o,o,o,0.015)
    assert abs(result-o)<=max(1e-9,abs(o)*1e-5),(o,result)
r_dark=stop_ratio(.003,.003,.006,.015)
assert abs(r_dark-.006)<=1e-6,r_dark
for c in (.000001,.015,.05):
    for o in (0,.003,.1,4,50):
        for n in (0,.006,.01,1,20,100):
            assert stop_ratio(o,max(o,1e-5),n,c)>=0
print("PASS pedestal CPU reference neutral identity, dark +1 stop, nonnegative")
print("PASS pre-headset source and CPU reference gates")
