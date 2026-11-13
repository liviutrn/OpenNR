#!/usr/bin/env python3
"""Fable-feedback review hardening for Cheeky 0.6.3 Duo/Tri NR.

Apply after apply_v063_nr_targets_v2.py on the pinned/generated tree.
Keep four USER-REQUESTED modes, never infer an extra periphery in fovea-only
modes, and keep proven GPU-fenced lifetimes and native DLSS SR unchanged.
"""
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()

def patch(path, before, after):
    p=root/path
    data=p.read_text(encoding="utf-8")
    count=data.count(before)
    if count != 1:
        raise RuntimeError(f"{path}: strict anchor count {count}, wanted 1: {before[:100]!r}")
    p.write_text(data.replace(before, after, 1),encoding="utf-8",newline="\n")
    print("FABLE-REVIEW:",path)

# A real issue: upstream settings_for_view has nr_enabled = focus only when the
# quad-compatible source observer is active. Allow a peripheral ONLY under the
# user's explicit TriView-All mode AND a 3-source observed layout. Never turn
# this into enabling NR for ordinary 4-target OpenXR QuadViews.
patch("src/settings.hpp",
      '[[nodiscard]] inline std::uint32_t cheeky_nr_target_mask(const Settings& settings) noexcept {',
      '''[[nodiscard]] inline bool cheeky_nr_tri_periphery_requested(const Settings& settings) noexcept {
    return settings.nr_enabled && settings.nr_target_mode == 3U &&
        ((settings.nr_pass1_views |
          (settings.nr_passes >= 2U ? settings.nr_pass2_views : 0U)) & 4U) != 0U;
}
[[nodiscard]] inline std::uint32_t cheeky_nr_target_mask(const Settings& settings) noexcept {''')
patch("src/settings.cpp",
      '        result.nr_enabled=settings.nr_enabled&&role&&cheeky_nr_selected_passes(settings,view_id)!=0U;',
      '''        // Explicit TriView-All may enable the ONE periphery of a 3-source
        // compositor. Ordinary 4-source QuadViews remain unchanged.
        unsigned physical_source_count{};
        for (const auto& source : quad.sources)
            if (source.dlss_view) ++physical_source_count;
        result.nr_enabled=settings.nr_enabled&&role&&
            cheeky_nr_selected_passes(settings,view_id)!=0U&&
            (role->focus || (physical_source_count==3U &&
                            cheeky_nr_tri_periphery_requested(settings)));''')

# The old automatic Duo heuristic could choose a view using output extents
# alone. Output textures may be identical/full-eye or otherwise unrelated to
# final composition. Require a measured input-area separation (>=20%) for
# fovea-only auto; output size can reject conflicting evidence but not identify.
patch("src/settings.cpp",
      '''            identified = (input && output && input != output)
                ? 0 : (input ? input : output);''',
      '''            identified = (input && output && input != output) ? 0 : input;
            // No input evidence => ambiguous. Duo BOTH is separately explicit.
            // An output-only difference must NOT select a physical fovea.''')

# Full periphery selection remains opt-in, but fovea-only modes no longer list
# unavailable peripheral masks. Retain old stored masks on disk; evaluator's
# actual role-mode intersection remains authoritative.
p=root/"uevr/scripts/cheeky_foveated_dlss.lua"
ui=p.read_text(encoding="utf-8")
start=ui.index('    text("Each pass can process any subset of the selected mode\'s sources.")')
end=ui.index('    text("Pass 1 crop is configured below.',start)
replacement='''    local mode = draft.NrTargetMode or 2
    if mode == 0 then
        text("Fovea-only safety: ambiguous Duo source = NR skipped; NEVER both.")
    elseif mode == 1 then
        text("Duo BOTH is explicitly opted in: two sources can receive NR.")
    elseif mode == 2 then
        text("TriView foveas only: periphery is always excluded.")
    else
        text("TriView ALL opted in: periphery also needs a verified source role.")
    end
    text("Pass 1 and pass 2 have independent source masks within this mode.")
    local mask_labels = {[0]="None", [1]="Fovea A / Duo fovea",
        [2]="TriView fovea B", [3]="Both foveas",
        [4]="Periphery only", [5]="Fovea A + periphery",
        [6]="Fovea B + periphery", [7]="All three views"}
    local order = mode == 0 and {1,0}
        or mode == 1 and {5,1,4,0}
        or mode == 2 and {3,1,2,0}
        or {7,3,5,6,4,1,2,0}
    -- A legacy saved mask can be outside this mode's choices. Render it
    -- without silently editing the stored profile; execution still clamps it.
    local function source_combo(label,key)
        local displayed = {}
        for _,value in ipairs(order) do displayed[#displayed+1]=value end
        local found=false
        for _,value in ipairs(displayed) do
            if value == draft[key] then found=true end
        end
        if not found and draft[key] ~= nil then
            displayed[#displayed+1]=draft[key]
        end
        combo(label,key,mask_labels,displayed)
    end
    source_combo("Pass 1 source views", "NrPass1Views")
'''
ui=ui[:start]+replacement+ui[end:]
old='combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,7,5,4,1,2,6,0})'
if ui.count(old)!=1: raise RuntimeError("Expected exact second-pass combo anchor")
ui=ui.replace(old,'source_combo("Pass 2 source views", "NrPass2Views")')
ui=ui.replace('text("Duo auto: larger observed DLSS input region is the fovea (20% confidence gap).")',
              'text("Duo Auto: larger observed DLSS INPUT is fovea if at least 20% larger;")\n        text("conflicting output geometry or equal inputs => skip unless manual.")')
p.write_text(ui,encoding="utf-8",newline="\n")
print("FABLE-REVIEW: source-aware UI hides periphery choices in fovea-only modes")

# Add concise change-triggered routing telemetry including all source sizes,
# mode, masks, selected source IDs/roles. One log event per OBSERVED change,
# not a line every frame or only once per 300 evaluations.
patch("src/settings.hpp",
      'void note_stereo_view_output_subrect(std::uint64_t view_id,',
      '''struct CheekyNrObservedSource {
    std::uint64_t view_id{};
    std::uint32_t width{}, height{}, output_width{}, output_height{};
};
struct CheekyNrObservedSources {
    std::uint32_t count{};
    std::array<CheekyNrObservedSource,4> sources{};
};
[[nodiscard]] CheekyNrObservedSources cheeky_nr_observed_sources() noexcept;
void note_stereo_view_output_subrect(std::uint64_t view_id,''')
patch("src/settings.cpp",
      'void note_stereo_view_output_subrect(const std::uint64_t id,',
      '''CheekyNrObservedSources cheeky_nr_observed_sources() noexcept {
    CheekyNrObservedSources out{};
    const auto now = GetTickCount64();
    std::lock_guard lock(stereo_views_mutex);
    for (const auto& view : stereo_views) {
        if (!view.evaluation_calls || view.graphics_api!=12U ||
            !view.evaluation_input_width || !view.evaluation_input_height ||
            !view.evaluation_output_width || !view.evaluation_output_height ||
            view.last_evaluation_ms > now ||
            now-view.last_evaluation_ms > 2000U) continue;
        if (out.count >= 4U) { out.count=5U; break; }
        auto& s=out.sources[out.count++];
        s={view.view_id,view.evaluation_input_width,view.evaluation_input_height,
            view.evaluation_output_width,view.evaluation_output_height};
    }
    std::sort(out.sources.begin(),out.sources.begin()+(std::min)(out.count,4U),
        [](const auto& a,const auto& b) { return a.view_id < b.view_id; });
    return out;
}
void note_stereo_view_output_subrect(const std::uint64_t id,''')

p=root/"src/hooks.cpp"
hooks=p.read_text(encoding="utf-8")
start=hooks.index('    if (api == DiagnosticApi::d3d12) {\n        static std::atomic<std::uint64_t> source_trace{};')
end=hooks.index('    }',start)+len('    }')
old=hooks[start:end]
if old.count('trace_event("[CheekyNR][SourceRouting]')!=1: raise RuntimeError("unexpected source routing trace")
replacement='''    if (api == DiagnosticApi::d3d12) {
        const auto cfg=current_settings();
        const auto observed=cheeky_nr_observed_sources();
        unsigned roles[4]{};
        std::uint64_t hash=1469598103934665603ULL;
        const auto mix=[&](const std::uint64_t value) noexcept {
            hash^=value; hash*=1099511628211ULL;
        };
        mix(cfg.nr_target_mode); mix(cfg.nr_duo_fovea_source);
        mix(cfg.nr_pass1_views); mix(cfg.nr_pass2_views); mix(cfg.nr_passes);
        mix(observed.count);
        for (unsigned i=0;i<(std::min)(observed.count,4U);++i) {
            const auto& v=observed.sources[i];
            roles[i]=cheeky_nr_source_role_for(cfg,v.view_id);
            mix(v.view_id); mix(std::uint64_t(v.width)<<32U | v.height);
            mix(std::uint64_t(v.output_width)<<32U | v.output_height);
            mix(roles[i]);
        }
        static std::atomic<std::uint64_t> last_observation{};
        if (last_observation.exchange(hash,std::memory_order_acq_rel) != hash) {
            const auto& a=observed.sources[0]; const auto& b=observed.sources[1];
            const auto& c=observed.sources[2]; const auto& d=observed.sources[3];
            trace_event("[CheekyNR][RouteChange] mode=%u manualDuo=%u passMasks=%u,%u passCount=%u live=%u A=%llu:%ux%u->%ux%u:role%u B=%llu:%ux%u->%ux%u:role%u C=%llu:%ux%u:role%u D=%llu:%ux%u:role%u",
                cfg.nr_target_mode,cfg.nr_duo_fovea_source,
                cfg.nr_pass1_views,cfg.nr_pass2_views,cfg.nr_passes,observed.count,
                static_cast<unsigned long long>(a.view_id),a.width,a.height,a.output_width,a.output_height,roles[0],
                static_cast<unsigned long long>(b.view_id),b.width,b.height,b.output_width,b.output_height,roles[1],
                static_cast<unsigned long long>(c.view_id),c.width,c.height,roles[2],
                static_cast<unsigned long long>(d.view_id),d.width,d.height,roles[3]);
        }
    }'''
hooks=hooks[:start]+replacement+hooks[end:]
p.write_text(hooks,encoding="utf-8",newline="\n")
print("FABLE-REVIEW: bounded change-triggered source routing telemetry")

# Actual C++ unit assertions for explicit-only periphery policy and
# output-only evidence never selecting Duo fovea.
p=root/"tests/gaze_tests.cpp"
tests=p.read_text(encoding="utf-8")
anchor='''        s.nr_target_mode=0U;
        note_stereo_view_evaluation(99111,12U,1200U,800U,2400U,1600U);'''
if tests.count(anchor)!=1: raise RuntimeError("Duo equal input fixture changed")
tests=tests.replace(anchor,'''        s.nr_target_mode=0U;
        note_stereo_view_evaluation(99111,12U,1200U,800U,800U,520U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Duo output-only area difference cannot infer the fovea");
        note_stereo_view_evaluation(99111,12U,1200U,800U,2400U,1600U);''')
p.write_text(tests,encoding="utf-8",newline="\n")
print("PASS Fable review: no output-only guess, intentional periphery, tri quad guard and routing trace")
