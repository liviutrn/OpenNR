#!/usr/bin/env python3
"""Reviewed four-mode NR source routing, with geometry-first DuoView and manual fallback.

Apply strictly AFTER apply_v063_duo_tri_foveas.py. Keeps the proven TriView
3/4-source classifier, independent pass settings and native game SR.
No hooks added to UEVR and no unverified NGX-output-atlas assumption.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def patch(path, before, after, count=1):
    p = root / path
    s = p.read_text(encoding="utf-8")
    found = s.count(before)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} strict anchor(s), got {found}: {before[:100]!r}")
    p.write_text(s.replace(before, after), encoding="utf-8", newline="\n")
    print("NR-TARGET:", path)

# The mode is explicit: old profiles default to proven TriView foveas only.
# A second setting exists only for ambiguous 2-source DuoView where NGX exposes
# neither distinct input nor output dimensions. Manual A/B refers to SORTED
# CURRENT source IDs, not physical eye or guaranteed registration order.
patch("src/settings.hpp",
      "    std::uint32_t nr_pass2_views{3U};",
      """    std::uint32_t nr_pass2_views{3U};
    std::uint32_t nr_target_mode{2U}; // 0=duo fovea,1=duo both,2=tri foveas,3=tri all
    std::uint32_t nr_duo_fovea_source{0U}; // 0=size auto;1=lower source ID;2=higher source ID""")
patch("src/settings.cpp",
      "std::uint32_t nr_pass1_views{3U}, nr_pass2_views{3U};",
      """std::uint32_t nr_pass1_views{3U}, nr_pass2_views{3U};
std::uint32_t nr_target_mode{2U}, nr_duo_fovea_source{0U};""")
patch("src/settings.cpp",
      "    settings.nr_pass2_views = nr_pass2_views;",
      """    settings.nr_pass2_views = nr_pass2_views;
    settings.nr_target_mode = nr_target_mode;
    settings.nr_duo_fovea_source = nr_duo_fovea_source;""")
patch("src/settings.cpp",
      "    nr_pass2_views = settings.nr_pass2_views & 3U;",
      """    nr_pass2_views = settings.nr_pass2_views & 7U;
    nr_target_mode = (std::min)(settings.nr_target_mode, 3U);
    nr_duo_fovea_source = (std::min)(settings.nr_duo_fovea_source, 2U);""")
patch("src/settings.cpp",
      "    nr_pass1_views = settings.nr_pass1_views & 3U;",
      "    nr_pass1_views = settings.nr_pass1_views & 7U;")
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrPass2Views", nr_pass2_views)',
      '''CHEEKY_SETTING("NrPass2Views", nr_pass2_views)
CHEEKY_SETTING("NrTargetMode", nr_target_mode)
CHEEKY_SETTING("NrDuoFoveaSource", nr_duo_fovea_source)''')
patch("uevr/settings_io.cpp",
      '(key=="NrPass1Views" ? s.nr_pass1_views : s.nr_pass2_views)=(mask & 3U);return true;',
      '(key=="NrPass1Views" ? s.nr_pass1_views : s.nr_pass2_views)=(mask & 7U);return true;')
patch("uevr/settings_io.cpp",
      '    if(key=="FgDlssgPreset")',
      '''    if (key=="NrTargetMode" || key=="NrDuoFoveaSource") {
        unsigned value{}; if (!parse(text, value) ||
            value > (key=="NrTargetMode" ? 3U : 2U)) return false;
        (key=="NrTargetMode" ? s.nr_target_mode : s.nr_duo_fovea_source)=value;
        return true;
    }
    if(key=="FgDlssgPreset")'''.replace("parse(text, value)", "parse(value, value)"))
# Correct the overloaded local: parse(string_view value, unsigned& parsed).
patch("uevr/settings_io.cpp",
      '''        unsigned value{}; if (!parse(value, value) ||
            value > (key=="NrTargetMode" ? 3U : 2U)) return false;
        (key=="NrTargetMode" ? s.nr_target_mode : s.nr_duo_fovea_source)=value;''',
      '''        unsigned parsed{}; if (!parse(value, parsed) ||
            parsed > (key=="NrTargetMode" ? 3U : 2U)) return false;
        (key=="NrTargetMode" ? s.nr_target_mode : s.nr_duo_fovea_source)=parsed;''')

# One authoritative policy used by evaluator, retirement and memory admission.
patch("src/settings.hpp",
      "[[nodiscard]] std::uint32_t cheeky_nr_source_role(std::uint64_t) noexcept;",
      """[[nodiscard]] inline std::uint32_t cheeky_nr_target_mask(const Settings& settings) noexcept {
    switch (settings.nr_target_mode) {
        case 0U: return 1U; // DuoView fovea only
        case 1U: return 5U; // DuoView fovea + periphery (roles 1,4)
        case 2U: return 3U; // TriView pair of foveas
        case 3U: return 7U; // TriView all three sources
        default: return 0U;
    }
}
[[nodiscard]] std::uint32_t cheeky_nr_source_role_for(const Settings&, std::uint64_t) noexcept;
[[nodiscard]] std::uint32_t cheeky_nr_source_role(std::uint64_t) noexcept;""")

# Old classifier assumed NGX output subrects were the DuoView compositor atlas.
# The compositor does NOT establish that invariant. Drop it entirely for roles.
p = root / "src/settings.cpp"
source = p.read_text(encoding="utf-8")
start = source.index("std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {")
end = source.index("std::uint32_t cheeky_nr_selected_passes(", start)
old = source[start:end]
if old.count("    if (n == 2U) {") != 1:
    raise RuntimeError("Unexpected old DuoView classifier")
first = old.index("    if (n == 2U) {")
last = old.index("    if (n != 3U && n != 4U) return 0U;", first)
old = old[:first] + """    if (n == 2U) {
        if (settings.nr_target_mode >= 2U) return 0U; // Must explicitly select DuoView
        // NGX input subrect dimensions can differ even when Native Fix uses
        // two full-eye output textures. Prefer those dimensions; output extent
        // is only corroboration, NEVER an atlas-position assumption.
        const auto compare_area = [](const std::uint32_t aw, const std::uint32_t ah,
            const std::uint32_t bw, const std::uint32_t bh) noexcept -> int {
            const auto a = std::uint64_t(aw) * ah, b = std::uint64_t(bw) * bh;
            if (!a || !b) return 0;
            // Require a real 20% area separation; similar-size sources are
            // ambiguous and cannot safely identify periphery automatically.
            if (a * 5U >= b * 6U) return +1;
            if (b * 5U >= a * 6U) return -1;
            return 0;
        };
        int identified{};
        if (settings.nr_duo_fovea_source) {
            const bool first_is_low = v[0]->view_id < v[1]->view_id;
            identified = settings.nr_duo_fovea_source == 1U
                ? (first_is_low ? +1 : -1) : (first_is_low ? -1 : +1);
        } else {
            const int input = compare_area(v[0]->evaluation_input_width,
                v[0]->evaluation_input_height, v[1]->evaluation_input_width,
                v[1]->evaluation_input_height);
            const int output = compare_area(v[0]->evaluation_output_width,
                v[0]->evaluation_output_height, v[1]->evaluation_output_width,
                v[1]->evaluation_output_height);
            // Conflicting input/output observations must never choose a target.
            // A contradictory signal cannot identify a *single* fovea, but
            // the fully selected Duo BOTH layout can still process both.
            identified = (input && output && input != output)
                ? 0 : (input ? input : output);
        }
        if (!identified && settings.nr_target_mode == 1U) {
            // When BOTH sources are explicitly targeted by every active pass,
            // we do not need to know which is the fovea. Give them temporary
            // deterministic roles solely to let both pass-masks select both.
            // Partial per-source masks still fail closed until A/B is supplied.
            const auto full_or_none = [](const std::uint32_t m) noexcept {
                const auto selected = m & 5U;
                return selected == 0U || selected == 5U;
            };
            if (full_or_none(settings.nr_pass1_views) &&
                (settings.nr_passes < 2U || full_or_none(settings.nr_pass2_views)))
                identified = v[0]->view_id < v[1]->view_id ? +1 : -1;
        }
        if (!identified) return 0U; // Ambiguous: manual A/B override is available
        const StereoView* fovea = identified > 0 ? v[0] : v[1];
        const StereoView* periphery = identified > 0 ? v[1] : v[0];
        return id == fovea->view_id ? 1U :
               id == periphery->view_id ? 4U : 0U;
    }
""" + old[last:]
old = old.replace(
    "std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {",
    "std::uint32_t cheeky_nr_source_role_for(const Settings& settings, const std::uint64_t id) noexcept {", 1)
old = old.replace("    if (quad.active) {\n        if (quad.status != 2)",
                  "    if (quad.active) {\n        if (settings.nr_target_mode < 2U) return 0U;\n        if (quad.status != 2)", 1)
old = old.replace("    if (n != 3U && n != 4U) return 0U;",
                  "    if (settings.nr_target_mode < 2U || (n != 3U && n != 4U)) return 0U;", 1)
old += """std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {
    return cheeky_nr_source_role_for(current_settings(), id);
}

"""
source = source[:start] + old + source[end:]
p.write_text(source, encoding="utf-8", newline="\n")
print("NR-TARGET: geometry-first DuoView, verified TriView classifier preserved")

patch("src/settings.cpp",
      "const auto first = settings.nr_pass1_views & 3U; // periphery is NEVER an NR target",
      """const auto allowed = cheeky_nr_target_mask(settings);
    const auto first = settings.nr_pass1_views & allowed;""")
patch("src/settings.cpp",
      "settings.nr_pass2_views & 3U",
      "settings.nr_pass2_views & allowed")
patch("src/settings.cpp",
      "const auto role = cheeky_nr_source_role(view_id);",
      "const auto role = cheeky_nr_source_role_for(settings, view_id);")
patch("src/dlss_nr.cpp",
      "const auto role = cheeky_nr_source_role(frame.view_id);",
      "const auto role = cheeky_nr_source_role_for(settings, frame.view_id);")

# Filter the actual NATIVE NGX hook before calling generic Before-SR input
# preparation. The low-level input allocator remains untouched, preserving the
# WARP recording/allocator/replay tests and invalid-frame diagnostic contract.
# Only live game evaluations use the source-role policy before scratch allocation.
patch("src/hooks.cpp",
      """        auto* processed = prepare(list, params, settings);
        if (!processed && settings.eye_independent_coverage) skip_dlss_nr_history(frame.view_id);""",
      """        const auto selected_passes = cheeky_nr_selected_passes(settings, frame.view_id);
        if (!selected_passes) {
            skip_dlss_nr_history(frame.view_id);
            skip_dlss_nr_history(frame.view_id ^ (1ULL << 63U));
        }
        auto* processed = selected_passes ? prepare(list, params, settings) : nullptr;
        if (!processed && settings.eye_independent_coverage) skip_dlss_nr_history(frame.view_id);""")

# Source-role switches must not let old NGX model allocations survive as valid
# histories. Existing collect_retired_views remains GPU-fence aware.
patch("src/dlss_nr.cpp",
      "if (view.source_role == 4U || (mask & view.source_role) == 0U) view.retired = true;",
      """if (((cheeky_nr_target_mask(live) & mask) & view.source_role) == 0U)
                view.retired = true;""")
patch("uevr/runtime.cpp",
      '''        update_settings(settings);
        if (was_manual_mapping != settings.manual_stereo_mapping)''',
      '''        const bool nr_sources_changed =
            configured_settings().nr_target_mode != settings.nr_target_mode ||
            configured_settings().nr_duo_fovea_source != settings.nr_duo_fovea_source;
        update_settings(settings);
        if (nr_sources_changed) release_dlss_nr_resources(); // GPU-fence-aware full mode switch
        if (was_manual_mapping != settings.manual_stereo_mapping)''')

# NR templates are model/settings presets, not a hidden renderer-mode switch.
# The prior template loader deliberately excluded the old EyeProcessingMode;
# preserve that guarantee for the new mode and manual source selection.
patch("uevr/runtime.cpp",
      '#define CHEEKY_SETTING(name, field) if (std::string_view(name).starts_with("Nr") && std::string_view(name) != "NrTemplateActive") settings.field = stored.field;',
      '#define CHEEKY_SETTING(name, field) if (std::string_view(name).starts_with("Nr") && std::string_view(name) != "NrTemplateActive" && std::string_view(name) != "NrTargetMode" && std::string_view(name) != "NrDuoFoveaSource") settings.field = stored.field;')

# Admission policy must consider the EFFECTIVE mode, not assume 2 fixed foveas.
patch("uevr/nr_lite_budget_policy.hpp",
      """    const auto first_new = requested.nr_pass1_views & ~(current.nr_pass1_views);
    const auto second_new = requested.nr_passes>=2U
        ? requested.nr_pass2_views &
            ~(current.nr_passes>=2U ? current.nr_pass2_views : 0U) : 0U;""",
      """    const auto old_allowed = cheeky_nr_target_mask(current);
    const auto new_allowed = cheeky_nr_target_mask(requested);
    const auto first_new = (requested.nr_pass1_views & new_allowed) &
        ~(current.nr_pass1_views & old_allowed);
    const auto second_new = requested.nr_passes>=2U
        ? (requested.nr_pass2_views & new_allowed) &
            ~(current.nr_passes>=2U ? (current.nr_pass2_views & old_allowed) : 0U) : 0U;
    // Manual reassignment changes the physical NVIDIA feature target; reserve
    // headroom before instantiating its replacement even without a new mask.
    if (current.nr_enabled && requested.nr_enabled &&
        current.nr_duo_fovea_source != requested.nr_duo_fovea_source)
        return 1536ULL * nr_lite_mib;
    if (current.nr_enabled && requested.nr_enabled &&
        current.nr_target_mode != requested.nr_target_mode &&
        (current.nr_target_mode / 2U != requested.nr_target_mode / 2U))
        return 2048ULL * nr_lite_mib; // Duo <-> Tri can create entirely new NGX features""")
patch("uevr/nr_lite_budget_policy.hpp",
      """const auto features=source_count(requested.nr_pass1_views) +
            (requested.nr_passes>=2U ? source_count(requested.nr_pass2_views) : 0U);""",
      """const auto eligible=cheeky_nr_target_mask(requested);
        const auto features=source_count(requested.nr_pass1_views & eligible) +
            (requested.nr_passes>=2U ? source_count(requested.nr_pass2_views & eligible) : 0U);""")
# The negative safety case now allows periphery ONLY if an explicit mode and
# individual pass mask both grant it. Do not sanitize old masks on read.
patch("src/settings.cpp",
      "nr_pass1_views = settings.nr_pass1_views & 7U;",
      "nr_pass1_views = settings.nr_pass1_views & 7U;", count=1) if False else None

# UI: one explicit 4-choice mode selector, independent masks per pass, optional
# manual Duo source A/B ONLY if actual input/output sizes cannot identify role.
p = root / "uevr/scripts/cheeky_foveated_dlss.lua"
ui = p.read_text(encoding="utf-8")
start = ui.index('    text("Auto source routing: TriView = both foveas; DuoView Mono = one fovea.")')
end = ui.index('    text("Pass 1 crop is configured below.', start)
panel = """    text("Select exactly the renderer layout in UEVR. No NR source is guessed from NGX atlas X.")
    local target_labels = {[0]="DuoView Mono: fovea only", [1]="DuoView Mono: fovea + periphery",
        [2]="TriView Stereo: both foveas", [3]="TriView Stereo: all three"}
    local before_mode = draft.NrTargetMode or 2
    combo("NR target layout", "NrTargetMode", target_labels, {0,1,2,3})
    if draft.NrTargetMode ~= before_mode then
        -- Switching layout selects all permitted sources as sensible defaults.
        -- Both model passes remain independently editable afterwards.
        local defaults = ({[0]=1,[1]=5,[2]=3,[3]=7})[draft.NrTargetMode] or 3
        for _,key in ipairs({"NrPass1Views","NrPass2Views"}) do
            draft[key], dirty[key], ready_edits[key] = defaults, defaults, defaults
        end
    end
    if (draft.NrTargetMode or 2) < 2 then
        text("Duo auto: larger observed DLSS input region is the fovea (20% confidence gap).")
        text("If both sources have equal sizes, Duo BOTH works with full-source masks;")
        text("for per-source targeting choose A/B manually.")
        combo("Duo mono fovea source", "NrDuoFoveaSource",
            {[0]="Auto by input resolution", [1]="Source A (lower DLSS handle ID)",
             [2]="Source B (higher DLSS handle ID)"}, {0,1,2})
        text("After a runtime reset, verify A/B again: IDs can change.")
    end
    text("Each pass can process any subset of the selected mode's sources.")
    local mask_labels = {[0]="None", [1]="Fovea A / Duo fovea",
        [2]="TriView fovea B", [3]="Both foveas",
        [4]="Periphery only", [5]="Fovea A + periphery",
        [6]="Fovea B + periphery", [7]="All three views"}
    combo("Pass 1 source views", "NrPass1Views", mask_labels, {3,7,5,4,1,2,6,0})
"""
ui = ui[:start] + panel + ui[end:]
# Need expose all masks for second pass too; previously fovea-only options.
ui = ui.replace('combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,1,2,0})',
                'combo("Pass 2 source views", "NrPass2Views", mask_labels, {3,7,5,4,1,2,6,0})')
ui = ui.replace('    text("ACTIVE TARGETS pass 1="',
                '    text("MODE " .. tostring(applied.NrTargetMode or "?") .. " | ACTIVE TARGETS pass 1="', 1)
p.write_text(ui, encoding="utf-8", newline="\n")
print("NR-TARGET: explicit UEVR 4-mode UI, Duo source fallback, both independent passes")

# Replace the obsolete tests that asserted NGX atlas positions were source IDs.
p = root / "tests/gaze_tests.cpp"
tests = p.read_text(encoding="utf-8")
a = tests.index("        // A single CHEEKY binary must handle DuoView Mono's fovea")
b = tests.index("        update_settings(old);", a)
fixture = """        // The selected layout is authoritative; source roles are established
        // by reliable observed resolution separation or an explicit A/B choice.
        register_stereo_view(99110);
        register_stereo_view(99111);
        note_stereo_view_evaluation(99110,12U,1200U,800U,2400U,1600U);
        note_stereo_view_evaluation(99111,12U,400U,260U,800U,520U);
        note_stereo_view_output_subrect(99110,true,999U,12U); // NGX base is irrelevant
        note_stereo_view_output_subrect(99111,true,0U,0U);
        s.nr_enabled=true; s.nr_passes=2U;
        s.nr_pass1_views=7U; s.nr_pass2_views=7U;
        s.nr_duo_fovea_source=0U;
        s.nr_target_mode=0U;
        expect(cheeky_nr_selected_passes(s,99110)==3U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Duo fovea-only routes by actual region resolution");
        s.nr_target_mode=1U;
        expect(cheeky_nr_selected_passes(s,99110)==3U &&
               cheeky_nr_selected_passes(s,99111)==3U,
               "Duo fovea plus periphery enables both sources intentionally");
        s.nr_pass1_views=3U; s.nr_pass2_views=3U;
        expect(cheeky_nr_selected_passes(s,99111)==0U,
               "Duo periphery requires individual pass-mask authorization");
        s.nr_pass1_views=7U; s.nr_pass2_views=7U;
        s.nr_target_mode=2U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "TriView mode refuses an ordinary two-source layout");
        s.nr_target_mode=0U;
        note_stereo_view_evaluation(99111,12U,1200U,800U,2400U,1600U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Identical source dimensions fail closed in fovea-only mode");
        s.nr_target_mode=1U; s.nr_pass1_views=5U; s.nr_pass2_views=5U;
        expect(cheeky_nr_selected_passes(s,99110)==3U &&
               cheeky_nr_selected_passes(s,99111)==3U,
               "Duo all-sources mode works even when both input areas are equal");
        s.nr_pass1_views=1U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Ambiguous Duo source identity never guesses a partial pass mask");
        s.nr_target_mode=0U; s.nr_pass1_views=7U; s.nr_pass2_views=7U;
        s.nr_duo_fovea_source=1U;
        expect(cheeky_nr_selected_passes(s,99110)==3U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Explicit Duo source A can identify equal-size resources");
        s.nr_duo_fovea_source=2U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==3U,
               "Explicit Duo source B can identify equal-size resources");
        s.nr_duo_fovea_source=0U;
        note_stereo_view_evaluation(99110,12U,400U,260U,800U,520U);
        note_stereo_view_evaluation(99111,12U,1200U,800U,2400U,1600U);
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==3U,
               "Duo physical source order and role can reverse");
        // Source-role changes never enable disallowed peripheral inference.
        s.nr_pass1_views=4U; s.nr_pass2_views=4U;
        expect(cheeky_nr_selected_passes(s,99110)==0U &&
               cheeky_nr_selected_passes(s,99111)==0U,
               "Duo fovea-only forbids periphery-only masks");
        unregister_stereo_view(99110);
        unregister_stereo_view(99111);
"""
tests = tests[:a] + fixture + tests[b:]
# Add all-three TriView test to the existing three-source source-mask fixture.
anchor = """               "Pass1 all saved mask still bypasses periphery");"""
if tests.count(anchor)!=1: raise RuntimeError("TriView fixture changed")
tests = tests.replace(anchor, anchor + """
        s.nr_target_mode=3U; s.nr_pass1_views=7U; s.nr_pass2_views=7U;
        expect(cheeky_nr_selected_passes(s,99001)==3U &&
               cheeky_nr_selected_passes(s,99002)==3U &&
               cheeky_nr_selected_passes(s,99004)==3U,
               "TriView all-three opt-in runs both passes on peripheral source");
        s.nr_target_mode=2U; s.nr_pass1_views=7U; s.nr_pass2_views=3U;""")
p.write_text(tests, encoding="utf-8", newline="\n")
print("NR-TARGET: real source-fixture tests for four modes, source inversion, masks")
print("PASS NR targeting source patch prepared")
