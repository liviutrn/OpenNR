#!/usr/bin/env python3
"""Fable C5 UI and runtime snapshot: observed roles, EFFECTIVE masks, warnings.

Run after apply_v063_fable_c1_c6.py; never alter NR evaluation paths.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(path,old,new):
    f=root/path; txt=f.read_text(encoding="utf-8")
    n=txt.count(old)
    if n!=1: raise RuntimeError(f"{path} strict anchor expected 1, found {n}: {old[:100]!r}")
    f.write_text(txt.replace(old,new,1),encoding="utf-8",newline="\n")
    print("FABLE-STATUS",path)

# Export true role source count, per-view pass selection and the effective
# (mode-intersected) masks from the C++ runtime, not a Lua-side guess.
patch("uevr/runtime.cpp",
      '        << ",\\\"setting_groups\\\":" << setting_groups_json();',
      '''        << ",\\\"setting_groups\\\":" << setting_groups_json();
    const auto nr_layout = configured_settings();
    const auto observed_nr = cheeky_nr_observed_sources();
    const auto allowed_nr = cheeky_nr_target_mask(nr_layout);
    const auto effective1 = nr_layout.nr_pass1_views & allowed_nr;
    const auto effective2 = nr_layout.nr_passes >= 2U
        ? nr_layout.nr_pass2_views & allowed_nr : 0U;
    unsigned selected_sources{};
    out << ",\\\"nr_routing\\\":{\\\"observed_count\\\":" << observed_nr.count
        << ",\\\"mode\\\":" << nr_layout.nr_target_mode
        << ",\\\"effective_pass1\\\":" << effective1
        << ",\\\"effective_pass2\\\":" << effective2
        << ",\\\"quad_active\\\":" << bool(quad.active)
        << ",\\\"quad_status\\\":" << quad.status
        << ",\\\"sources\\\":[";
    for (unsigned i=0;i<(std::min)(observed_nr.count,4U);++i) {
        const auto& source=observed_nr.sources[i];
        const auto route=cheeky_nr_selection(nr_layout,source.view_id);
        selected_sources += route.passes != 0U ? 1U : 0U;
        if (i) out << ',';
        out << "{\\\"id\\\":\\\"" << source.view_id
            << "\\\",\\\"input_width\\\":" << source.width << ",\\\"input_height\\\":" << source.height
            << ",\\\"output_width\\\":" << source.output_width
            << ",\\\"output_height\\\":" << source.output_height
            << ",\\\"role\\\":" << route.role << ",\\\"passes\\\":" << route.passes
            << "}";
    }
    const bool layout_mismatch = nr_layout.nr_enabled && observed_nr.count>=2U &&
        selected_sources==0U;
    out << "],\\\"selected_sources\\\":" << selected_sources
        << ",\\\"layout_mismatch\\\":" << layout_mismatch << "}";''')

# New size-hint setting key prevents all legacy A/B handle selections from
# being misinterpreted as permanent larger/smaller-image choices.
p=root/"uevr/scripts/cheeky_foveated_dlss.lua"
s=p.read_text(encoding="utf-8")
if s.count('NrDuoFoveaSource')<1: raise RuntimeError("Duo A/B UI not found")
s=s.replace('NrDuoFoveaSource','NrDuoFoveaSizeHint')
s=s.replace('combo("Duo mono fovea source", "NrDuoFoveaSizeHint",\n            {[0]="Auto by input resolution", [1]="Source A (lower DLSS handle ID)",\n             [2]="Source B (higher DLSS handle ID)"}, {0,1,2})',
            'combo("Duo mono fovea rule", "NrDuoFoveaSizeHint",\n            {[0]="Auto (larger image)", [1]="Fovea is LARGER input image",\n             [2]="Fovea is SMALLER input image"}, {0,1,2})')
s=s.replace('text("After a runtime reset, verify A/B again: IDs can change.")',
            'text("Only input images differing by 20%+ can be identified; otherwise NR skips.")')
s=s.replace('text("Duo Auto: larger observed DLSS INPUT is fovea if at least 20% larger;")',
            'text("Auto: larger DLSS input is fovea when 20%+ larger;")')
s=s.replace('text("conflicting output geometry or equal inputs => skip unless manual.")',
            'text("Select SMALLER explicitly if your actual fovea source is smaller.")')
# Identify exact generated layout selector (after Fable patch).
needle='    combo("NR target layout", "NrTargetMode", target_labels, {0,1,2,3})'
if s.count(needle)!=1: raise RuntimeError("NR layout selector not found")
extra='''    local route = status.nr_routing or {}
    local rc = tonumber(route.observed_count) or 0
    local ec = tonumber(route.selected_sources) or 0
    if rc > 0 then
        text(string.format("Live DLSS sources: %d | NR-selected: %d | quad bridge active: %s status: %s",
            rc, ec, tostring(route.quad_active), tostring(route.quad_status or "?")))
        for index, source in ipairs(route.sources or {}) do
            text(string.format("Source %d: %sx%s -> %sx%s role=%s passes=%s",
                index, tostring(source.input_width), tostring(source.input_height),
                tostring(source.output_width), tostring(source.output_height),
                tostring(source.role), tostring(source.passes)))
        end
    else
        text("Waiting for live DLSS source observations.")
    end
    text("EFFECTIVE running masks: pass 1=" .. tostring(route.effective_pass1 or "?")
        .. ", pass 2=" .. tostring(route.effective_pass2 or "?")
        .. " (after mode restriction; not raw saved values)")
    if route.layout_mismatch then
        if imgui.text_colored then
            imgui.text_colored("LAYOUT MISMATCH: NR IS OFF for all observed sources. Check selected mode.", 0xFF4444FF)
        else
            text("LAYOUT MISMATCH: NR IS OFF for all observed sources.")
        end
    end
    local refusal = tostring(status.message or "")
    if refusal:find("NR change refused", 1, true) then
        if imgui.text_colored then
            imgui.text_colored("VRAM GUARD: " .. refusal, 0xFF4444FF)
        else text("VRAM GUARD: " .. refusal) end
    end
    if last_apply_error then text(last_apply_error) end
'''
s=s.replace(needle,needle+"\n"+extra,1)
s=s.replace(' | ACTIVE TARGETS pass 1=', ' | SAVED MASK pass 1=')
p.write_text(s,encoding="utf-8",newline="\n")
print("PASS Fable C5: effective-source mode diagnostics / budget warning in UI")
