#!/usr/bin/env python3
"""TriView independent per-pass view masks and optional pass-2 crop.
Apply strictly after view, Lite and visibility scripts against pinned Cheeky 0.6.3.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(path, before, after):
    file=root/path; text=file.read_text(encoding="utf-8")
    count=text.count(before)
    if count!=1: raise RuntimeError(f"{path}: strict anchor count={count}: {before[:110]!r}")
    file.write_text(text.replace(before,after,1),encoding="utf-8",newline="\n")
    print("NR-PASS patched",path)

patch("src/settings.hpp",
    "    std::array<NrExtraPass, max_nr_passes - 1U> nr_extra_passes{};",
    """    std::array<NrExtraPass, max_nr_passes - 1U> nr_extra_passes{};
    // Source mask: 1=fovea A, 2=fovea B, 4=mono periphery.
    // A/B are stable sorted source IDs, not unverified anatomical left/right.
    // 7=all, 3=both foveas, 4=periphery, 0=none.
    std::uint32_t nr_pass1_views{3U};
    std::uint32_t nr_pass2_views{3U};
    bool nr_pass2_foveated{false};
    float nr_pass2_width{0.56F}, nr_pass2_height{0.56F};
    float nr_pass2_roundness{}, nr_pass2_transition_width{0.08F};""")

patch("src/settings.hpp",
    "[[nodiscard]] bool cheeky_triview_fovea(std::uint64_t) noexcept;",
    """[[nodiscard]] bool cheeky_triview_fovea(std::uint64_t) noexcept;
[[nodiscard]] std::uint32_t cheeky_nr_source_role(std::uint64_t) noexcept;
[[nodiscard]] std::uint32_t cheeky_nr_selected_passes(const Settings&, std::uint64_t) noexcept;
[[nodiscard]] bool evaluate_nr_selected_passes(const DlssNrFrame&, const Settings&) noexcept;""".replace(
    '[[nodiscard]] bool evaluate_nr_selected_passes(const DlssNrFrame&, const Settings&) noexcept;', ''))
# API for evaluator is in dlss_nr.hpp (Settings header cannot depend on DlssNrFrame).
patch("src/settings.cpp",
    "std::array<NrExtraPass, max_nr_passes - 1U> nr_extra_passes{}; // settings_mutex",
    """std::array<NrExtraPass, max_nr_passes - 1U> nr_extra_passes{}; // settings_mutex
std::uint32_t nr_pass1_views{3U}, nr_pass2_views{3U};
bool nr_pass2_foveated{};
float nr_pass2_width{0.56F}, nr_pass2_height{0.56F};
float nr_pass2_roundness{}, nr_pass2_transition_width{0.08F};""")
patch("src/settings.cpp",
    "    settings.nr_extra_passes = nr_extra_passes;",
    """    settings.nr_extra_passes = nr_extra_passes;
    settings.nr_pass1_views = nr_pass1_views;
    settings.nr_pass2_views = nr_pass2_views;
    settings.nr_pass2_foveated = nr_pass2_foveated;
    settings.nr_pass2_width = nr_pass2_width;
    settings.nr_pass2_height = nr_pass2_height;
    settings.nr_pass2_roundness = nr_pass2_roundness;
    settings.nr_pass2_transition_width = nr_pass2_transition_width;""")
patch("src/settings.cpp",
    "    nr_passes = std::clamp(settings.nr_passes, 1U, max_nr_passes);",
    """    nr_passes = std::clamp(settings.nr_passes, 1U, 2U);
    nr_pass1_views = settings.nr_pass1_views & 7U;
    nr_pass2_views = settings.nr_pass2_views & 7U;
    nr_pass2_foveated = settings.nr_pass2_foveated;
    nr_pass2_width = std::clamp(settings.nr_pass2_width, 0.2F, 1.0F);
    nr_pass2_height = std::clamp(settings.nr_pass2_height, 0.2F, 1.0F);
    nr_pass2_roundness = std::clamp(settings.nr_pass2_roundness, 0.0F, 1.0F);
    nr_pass2_transition_width = std::clamp(settings.nr_pass2_transition_width, 0.0F, 0.3F);""")

patch("uevr/settings_fields.inc",
    'CHEEKY_SETTING("NrPasses", nr_passes)',
    '''CHEEKY_SETTING("NrPasses", nr_passes)
CHEEKY_SETTING("NrPass1Views", nr_pass1_views)
CHEEKY_SETTING("NrPass2Views", nr_pass2_views)
CHEEKY_SETTING("NrPass2Foveated", nr_pass2_foveated)
CHEEKY_SETTING("NrPass2Width", nr_pass2_width)
CHEEKY_SETTING("NrPass2Height", nr_pass2_height)
CHEEKY_SETTING("NrPass2Roundness", nr_pass2_roundness)
CHEEKY_SETTING("NrPass2TransitionWidth", nr_pass2_transition_width)''')
patch("uevr/settings_io.cpp",
    '    if(key=="FgDlssgPreset")',
    '''    if(key=="NrPass1Views" || key=="NrPass2Views"){
        unsigned mask{}; if(!parse(value, mask) || mask > 7U)return false;
        (key=="NrPass1Views" ? s.nr_pass1_views : s.nr_pass2_views)=mask;return true;
    }
    if(key=="FgDlssgPreset")''')

# Independent masks require classifying the full 3-source TriView set. A mask
# of 7 can be applied before classification; partial masks fail closed.
patch("src/settings.cpp",
    "bool cheeky_processing_allowed_for_view(const Settings& settings,",
    """std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {
    if (!id) return 0U;
    const auto quad = quad_view_snapshot();
    if (quad.active) {
        if (quad.status != 2) return 0U;
        const auto* role = quad_view_assignment(quad,id,stereo_view_generation(id));
        if (!role) return 0U;
        return role->focus ? (role->eye_index == 0 ? 1U : 2U) : 4U;
    }
    std::lock_guard lock(stereo_views_mutex);
    const auto now = GetTickCount64();
    const StereoView* v[3]{};
    unsigned n{};
    for (const auto& src : stereo_views) {
        if (!src.evaluation_calls || src.graphics_api != 12U ||
            !src.evaluation_output_width || !src.evaluation_output_height ||
            src.last_evaluation_ms > now ||
            now-src.last_evaluation_ms > 2000U) continue;
        if (n==3U) return 0U;
        v[n++]=&src;
    }
    if(n!=3U) return 0U;
    const auto same=[](const StereoView* a,const StereoView* b) noexcept {
        return a->evaluation_output_width==b->evaluation_output_width &&
               a->evaluation_output_height==b->evaluation_output_height;
    };
    const bool ab=same(v[0],v[1]),ac=same(v[0],v[2]),bc=same(v[1],v[2]);
    const StereoView *a{}, *b{}, *p{};
    if (ab&&!ac&&!bc) {a=v[0];b=v[1];p=v[2];}
    else if(ac&&!ab&&!bc){a=v[0];b=v[2];p=v[1];}
    else if(bc&&!ab&&!ac){a=v[1];b=v[2];p=v[0];}
    else return 0U;
    if(a->view_id > b->view_id)std::swap(a,b);
    if(id==a->view_id)return 1U;
    if(id==b->view_id)return 2U;
    if(id==p->view_id)return 4U;
    return 0U;
}

std::uint32_t cheeky_nr_selected_passes(const Settings& settings,
    const std::uint64_t view_id) noexcept {
    if (!settings.nr_enabled) return 0U;
    const auto first = settings.nr_pass1_views & 7U;
    const auto second = settings.nr_passes >= 2U
        ? (settings.nr_pass2_views & 7U) : 0U;
    const auto role = cheeky_nr_source_role(view_id);
    // Even mask=7 targets only the three VERIFIED TriView source IDs.
    // Unknown/desktop sources never allocate an extra NVIDIA NR feature.
    const bool run_first = role != 0U && (first & role)!=0U;
    const bool run_second = role != 0U && (second & role)!=0U;
    return (run_first ? 1U : 0U) | (run_second ? 2U : 0U);
}

bool cheeky_processing_allowed_for_view(const Settings& settings,""")
# Keep native game SR intact, even when NR is disabled. Only NR-selected calls
# need Cheeky's intermediate preparation.
patch("src/settings.cpp",
    "    if (settings.eye_processing_mode == 0U) return true;",
    """    if (settings.nr_enabled) return cheeky_nr_selected_passes(settings, view_id) != 0U;
    // Preserve legacy routing behavior while NR is disabled (existing regressions).
    if (settings.eye_processing_mode == 0U) return true;""")
# Quad role used to suppress periphery NR; honor independent pass masks instead.
patch("src/settings.cpp",
    "        result.nr_enabled=settings.nr_enabled&&role&&role->focus;",
    "        result.nr_enabled=settings.nr_enabled&&role&&cheeky_nr_selected_passes(settings,view_id)!=0U;")

patch("src/dlss_nr.hpp",
    "    std::uint32_t view_output_base_x{}, view_output_base_y{}; // Retained when Before NR switches color to input space.",
    """    std::uint32_t view_output_base_x{}, view_output_base_y{}; // Retained when Before NR switches color to input space.
    // Appended to preserve layout of existing aggregate DlssNrFrame initializers.
    std::uint32_t logical_pass{1U};
    std::uint32_t source_role{};""")
patch("src/dlss_nr.hpp",
    '[[nodiscard]] bool evaluate_dlss_nr(',
    '''[[nodiscard]] bool evaluate_nr_selected_passes(const DlssNrFrame&, const Settings&) noexcept;
[[nodiscard]] bool evaluate_dlss_nr(''')
# Evaluate actual NR twice, each time with independently configured region and
# distinct view ID/history. Deliberately do not reuse NVIDIA's temporal feature.
patch("src/dlss_nr.cpp",
    "void draw_dlss_nr_border(const DlssNrFrame& input_frame,",
    """bool evaluate_nr_selected_passes(const DlssNrFrame& frame,
    const Settings& settings) noexcept {
    const auto chosen = cheeky_nr_selected_passes(settings, frame.view_id);
    if (!chosen) {
        skip_dlss_nr_history(frame.view_id);
        skip_dlss_nr_history(frame.view_id ^ (1ULL << 63U));
        return false;
    }
    const auto role = cheeky_nr_source_role(frame.view_id);
    // Same region: reuse the upstream optimized single-codec two-pass chain.
    // The two model features/histories remain independent (view.pass=0 and 1).
    // Different pass crops still require two distinct codec evaluations.
    const bool same_region = settings.nr_foveated == settings.nr_pass2_foveated &&
        (!settings.nr_foveated ||
         (!settings.nr_use_sr_foveation &&
          settings.nr_width==settings.nr_pass2_width &&
          settings.nr_height==settings.nr_pass2_height &&
          settings.nr_roundness==settings.nr_pass2_roundness &&
          settings.nr_transition_width==settings.nr_pass2_transition_width));
    if (chosen==3U && same_region) {
        auto shared_frame=frame;
        shared_frame.logical_pass=1U;
        shared_frame.source_role=role;
        return evaluate_dlss_nr(shared_frame,settings);
    }
    bool first_ok = false;
    bool second_ok = false;
    if (chosen & 1U) {
        auto first = settings;
        first.nr_passes = 1U;
        auto pass_frame = frame;
        pass_frame.logical_pass = 1U;
        pass_frame.source_role = role;
        first_ok = evaluate_dlss_nr(pass_frame, first);
    } else {
        skip_dlss_nr_history(frame.view_id);
    }
    if ((chosen & 2U) && (!(chosen & 1U) || first_ok)) {
        auto second = nr_pass_settings(settings, 1U);
        second.nr_passes = 1U;
        second.nr_foveated = settings.nr_pass2_foveated;
        second.nr_use_sr_foveation = false;
        second.nr_width = settings.nr_pass2_width;
        second.nr_height = settings.nr_pass2_height;
        second.nr_roundness = settings.nr_pass2_roundness;
        second.nr_transition_width = settings.nr_pass2_transition_width;
        auto pass_frame = frame;
        pass_frame.view_id ^= (1ULL << 63U); // Second NR history separate from source and pass 1.
        pass_frame.logical_pass = 2U;
        pass_frame.source_role = role;
        second_ok = evaluate_dlss_nr(pass_frame, second);
    } else {
        skip_dlss_nr_history(frame.view_id ^ (1ULL << 63U));
    }
    static std::atomic<std::uint64_t> trace_counter{};
    const auto count = trace_counter.fetch_add(1U,std::memory_order_relaxed)+1U;
    if (count <= 12U || count % 300U == 0U)
        trace_event("[CheekyNR][PerPass] source=%llu role=%u selected=%u first=%u second=%u pass2Crop=%u model=%u area=%ux%u",
            static_cast<unsigned long long>(frame.view_id), role, chosen,
            first_ok?1U:0U, second_ok?1U:0U, settings.nr_pass2_foveated?1U:0U,
            settings.nr_preset, frame.processing_width, frame.processing_height);
    return first_ok || second_ok;
}

void draw_dlss_nr_border(const DlssNrFrame& input_frame,""")
# Correct success reporting for logical pass 2, even though the helper runs
# one model evaluation per invocation.
patch("src/dlss_nr.cpp",
    '    diagnostics.active_passes = pass_count;',
    '''    diagnostics.active_passes = frame.logical_pass == 2U ? 2U : pass_count;''')
patch("src/dlss_nr.cpp",
    '    if (pass_count >= 2U) ++diagnostics.completed_two_pass_frames;',
    '''    if (pass_count >= 2U || frame.logical_pass == 2U)
        ++diagnostics.completed_two_pass_frames;''')

patch("src/dlss_nr_input.cpp",
    '    return evaluate_dlss_nr(frame, processing_settings) ? private_color : nullptr;',
    '    return evaluate_nr_selected_passes(frame, processing_settings) ? private_color : nullptr;')
patch("src/hooks.cpp",
    '    const bool evaluated = evaluate_dlss_nr(frame, evaluation.settings);',
    '    const bool evaluated = evaluate_nr_selected_passes(frame, evaluation.settings);')
patch("src/hooks.cpp",
    '    const bool evaluated = evaluate_dlss_nr(\n        frame,\n        view_settings\n    );',
    '    const bool evaluated = evaluate_nr_selected_passes(\n        frame,\n        view_settings\n    );')

# Independent source masks can instantiate additional opaque NVIDIA NR features.
# Preserve the existing conservative guard on every expanding setting change.
patch("uevr/nr_lite_budget_policy.hpp",
    "    // Enabling NR instantiates model histories and is always budget-gated.",
    """    // Guard reconfiguration that adds any new per-source model feature.
    // Reducing the source set is always a memory-recovery operation.
    const auto first_new = requested.nr_pass1_views & ~(current.nr_pass1_views);
    const auto second_new = requested.nr_passes>=2U
        ? requested.nr_pass2_views &
            ~(current.nr_passes>=2U ? current.nr_pass2_views : 0U) : 0U;
    const bool pass2_grows = current.nr_pass2_foveated && !requested.nr_pass2_foveated;
    const bool pass2_region_grows = requested.nr_pass2_foveated && current.nr_pass2_foveated &&
        (requested.nr_pass2_width > current.nr_pass2_width + 0.0001F ||
         requested.nr_pass2_height > current.nr_pass2_height + 0.0001F);
    if (current.nr_enabled && (first_new || second_new || pass2_grows || pass2_region_grows))
        return (first_new && second_new ? 3072ULL : 2048ULL) * nr_lite_mib;
    // Enabling NR instantiates model histories and is always budget-gated.""")
patch("uevr/nr_lite_budget_policy.hpp",
    """    if (!current.nr_enabled)
        return (requested.nr_foveated
            ? (requested.eye_processing_mode == 0U ? 2048ULL : 1024ULL)
            : (requested.eye_processing_mode == 0U ? 3072ULL : 2304ULL)) * nr_lite_mib;""",
    """    if (!current.nr_enabled) {
        const auto source_count=[](unsigned m) noexcept {
            return (m&1U?1U:0U)+(m&2U?1U:0U)+(m&4U?1U:0U);
        };
        const auto features=source_count(requested.nr_pass1_views) +
            (requested.nr_passes>=2U ? source_count(requested.nr_pass2_views) : 0U);
        // Admission headroom is deliberately larger than measured resource
        // bytes: NVIDIA's internal NGX allocations are not observable.
        return (features>=5U ? 4096ULL : features==4U ? 3072ULL :
            features==3U ? 2304ULL : features>=1U ? 1536ULL : 0ULL) * nr_lite_mib;
    }""")

# Execute against the actual runtime source-view observation code, not mocks.
patch("tests/gaze_tests.cpp",
    '''        note_stereo_view_evaluation(99004,12U,1000U,600U,4000U,2000U);
        expect(cheeky_processing_allowed_for_view(s,99001) &&''',
    '''        note_stereo_view_evaluation(99004,12U,1000U,600U,4000U,2000U);
        s.nr_enabled=true; s.nr_passes=2U;
        s.nr_pass1_views=7U; s.nr_pass2_views=3U;
        expect(cheeky_nr_selected_passes(s,99001)==3U &&
               cheeky_nr_selected_passes(s,99002)==3U &&
               cheeky_nr_selected_passes(s,99004)==1U,
               "Pass1 all, pass2 foveas excludes peripheral pass2");
        s.nr_pass1_views=4U; s.nr_pass2_views=3U;
        expect(cheeky_nr_selected_passes(s,99001)==2U &&
               cheeky_nr_selected_passes(s,99002)==2U &&
               cheeky_nr_selected_passes(s,99004)==1U,
               "Independent pass mask routing");
        s.nr_pass1_views=0U; s.nr_pass2_views=4U;
        expect(cheeky_nr_selected_passes(s,99001)==0U &&
               cheeky_nr_selected_passes(s,99004)==2U,
               "Pass2-only peripheral routing");
        s.nr_enabled=false; s.nr_pass1_views=3U; s.nr_pass2_views=3U;
        expect(cheeky_processing_allowed_for_view(s,99001) &&''')

# The previous build had intentionally changed defaults to Before SR, and this
# test was still asserting upstream's After SR default. Update only that check.
patch("tests/nr_processing_tests.cpp",
    'require(settings.nr_processing_order == NrProcessingOrder::after_upscaling,\n            "Default order changed");',
    'require(settings.nr_processing_order == NrProcessingOrder::before_upscaling,\n            "TriView NR Lite must default to Before SR");')

# Editor: each pass has an independent source mask. Old global source selector
# is hidden (but retained on disk for backwards compatibility).
p=root/"uevr/scripts/cheeky_foveated_dlss.lua"
s=p.read_text(encoding="utf-8")
start=s.index('    if draft.EyeProcessingMode ~= nil then',s.index('Cheeky TriView NR Lite'))
end=s.index('    if draft.NrProcessingOrder ~= nil then', start)
s=s[:start]+'''    text("Each model pass has independent source coverage. A/B are stable source IDs, not verified left/right eyes.")
    local mask_labels = {[0]="None", [1]="Fovea A", [2]="Fovea B", [3]="Both foveas",
        [4]="Periphery only", [5]="Fovea A + periphery",
        [6]="Fovea B + periphery", [7]="All three views"}
    combo("Pass 1 source views", "NrPass1Views", mask_labels, {3,7,4,1,2,5,6,0})
    text("Pass 1 crop is configured below. OFF processes each selected source in full.")
    if (draft.NrPasses or 1) >= 2 then
        combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,7,4,1,2,5,6,0})
        check("Crop pass 2 inside selected views", "NrPass2Foveated")
        if draft.NrPass2Foveated then
            slider("Pass 2 crop width", "NrPass2Width", 0.2, 1)
            slider("Pass 2 crop height", "NrPass2Height", 0.2, 1)
            slider("Pass 2 roundness", "NrPass2Roundness", 0, 1)
            slider("Pass 2 transition", "NrPass2TransitionWidth", 0, 0.3)
        end
        text("Passes run sequentially per source, with separate NVIDIA histories.")
        text("If pass 1 does not target a source, pass 2 runs alone there.")
    end
''' + s[end:]
s=s.replace('    text("APPLIED: NR " .. (applied.NrEnabled and "ON" or "OFF")',
'''    text("ACTIVE TARGETS pass 1=" .. tostring(applied.NrPass1Views or 0)
       .. " pass 2=" .. tostring(applied.NrPass2Views or 0)
       .. " | pass 2 crop=" .. (applied.NrPass2Foveated and "ON" or "OFF"))
    text("APPLIED: NR " .. (applied.NrEnabled and "ON" or "OFF")''',1)
s=s.replace('    if draft.NrFoveated ~= applied.NrFoveated or draft.NrPasses ~= applied.NrPasses',
'''    if draft.NrPass1Views ~= applied.NrPass1Views or draft.NrPass2Views ~= applied.NrPass2Views
       or draft.NrPass2Foveated ~= applied.NrPass2Foveated
       or draft.NrFoveated ~= applied.NrFoveated or draft.NrPasses ~= applied.NrPasses''',1)
p.write_text(s,encoding="utf-8",newline="\n")

print("PASS NR independent view selection, separate logical histories, per-pass crops, persisted UI")
