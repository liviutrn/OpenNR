#!/usr/bin/env python3
"""UEVR Lua panel smoke test against real GENERATED script, not patch snippets.

Runs with Lua 5.4 and mocked UEVR/ImGui event bridge. Exercises both the
NR and Stereo menus with pass 1 and pass 2 enabled. No GPU/UEVR simulation
is claimed: only GUI execution and control registration are checked.
"""
from pathlib import Path
import sys
from lupa.lua54 import LuaRuntime

source = Path(sys.argv[1]) / "uevr/scripts/cheeky_foveated_dlss.lua"
if not source.is_file():
    raise RuntimeError(f"Missing generated script: {source}")
lua = LuaRuntime(unpack_returned_tuples=True)
lua.execute(r'''
__seen = {}
__cb = {}
fs = {
    read=function(path) return "disableMod=0" end,
    write=function(path,data) return true end
}
imgui = {
    ColumnFlags = nil,
    tree_node = function(label)
        return label == "Cheeky Foveated DLSS"
          or label == "DLSS-NR (experimental)"
          or label == "Stereo and gaze"
          or label == "Pass 2 settings"
    end,
    tree_pop = function() end,
    text = function(s) end,
    text_colored = function(...) end,
    separator = function() end,
    spacing = function() end,
    same_line = function() end,
    begin_disabled = function(...) end,
    end_disabled = function(...) end,
    is_item_active = function() return false end,
    checkbox = function(label,v) __seen[label]=true; return false,v end,
    slider_float = function(label,v) __seen[label]=true; return false,v end,
    slider_int = function(label,v) __seen[label]=true; return false,v end,
    combo = function(label,v,values) __seen[label]=true; return false,v end,
    button = function(label) __seen[label]=true;return false end,
    begin_table = function(...) return false end
}
uevr = {
    api = {dispatch_custom_event=function(...) end},
    sdk = {callbacks = {
        on_lua_event=function(f) __cb.event=f end,
        on_frame=function(f) __cb.frame=f end
    }},
    lua = {add_script_panel=function(label, f) __cb.panel=f end}
}
__snap = {
    protocol=1,request=0,applied_request=0,ready=true,renderer=1,
    version="0.6.3",message="Ready.",nr="Active",
    settings={
        NrEnabled=true,NrPasses=2,NrPass1Views=7,NrPass2Views=3,
        NrPass2Foveated=true,NrPass2Width=0.5,NrPass2Height=0.5,
        NrPass2Roundness=0,NrPass2TransitionWidth=0.1,
        NrFoveated=false,NrWorkingScale=1,NrProcessingOrder=1,
        EyeProcessingMode=3,CenterMode=0,AutoStereoAlignment=false,
        NrPreset=1,ManualStereoMapping=false,
        FgEnabled=false,D3D11D3D12Transport=false,
        NrPass2SameAsPass1=true, NrIntensity=1
    },
    nr_details={
        processing_width=1355,processing_height=1077,
        region_width=1355,region_height=1077,
        working_width=1355,working_height=1077,
        decoded_frames=1024,completed_two_pass_frames=512,
        before_sr_processed_frames=1024,
        view_a_id=1234,view_b_id=5678,view_a_frames=512,view_b_frames=512,
        active_passes=2
    },
    gpu_memory={["local"]={valid=true,headroom_bytes=1073741824}},
    afw_experiment={},apis={{},{}},frame={},fg={},gaze={},support={}
}
json = {load_string=function(s) return __snap end}
''')
lua.execute(source.read_text(encoding="utf-8-sig"))
cb = lua.globals().__cb
if cb.event is None or cb.panel is None:
    raise RuntimeError("Generated Lua did not register UEVR panel + snapshot callback")
cb.event("cheeky.foveated_dlss.load_state.v1", "enabled")
cb.event("cheeky.foveated_dlss.snapshot.v1", "{}")
cb.panel()
seen = lua.globals().__seen
expected = [
    "Pass 1 source views",
    "Pass 2 source views",
    "Crop pass 2 inside selected views",
    "Pass 2 crop width",
    "Pass 2 crop height",
    "Model passes",
]
absent = [name for name in expected if seen[name] is None]
if absent:
    raise RuntimeError(f"Generated UI did not expose all pass controls: {absent}")
print("PASS Lua 5.4 UI smoke: loaded enabled runtime, decoded snapshot, rendered real NR UI,"
      " validated both source masks, pass-2 crop and 2-pass controls")
