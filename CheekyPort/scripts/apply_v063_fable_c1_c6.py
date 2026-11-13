#!/usr/bin/env python3
"""Fable C1-C6 repair, applied last to generated Cheeky 0.6.3 source.

Source-aware retirement is performed on the normal GPU submission-collection
path OUTSIDE nr_mutex classification. Same-family transitions preserve foveal
NGX models. Old persisted pointer-based Duo source choices are deliberately
ignored in favor of a new size-based key.
"""
from pathlib import Path
import sys
root=Path(sys.argv[1]).resolve()
def patch(name,before,after):
    p=root/name; data=p.read_text(encoding="utf-8"); n=data.count(before)
    if n!=1: raise RuntimeError(f"{name}: expected one strict anchor, found {n}: {before[:115]!r}")
    p.write_text(data.replace(before,after,1),encoding="utf-8",newline="\n")
    print("FABLE-C1-C6",name)

# C1: changing only peripheral permission or the Duo size hint must NOT
# invalidate already-good foveal NGX model histories and force reallocation.
patch("uevr/runtime.cpp",
      """        const bool nr_sources_changed =
            configured_settings().nr_target_mode != settings.nr_target_mode ||
            configured_settings().nr_duo_fovea_source != settings.nr_duo_fovea_source;
        update_settings(settings);
        if (nr_sources_changed) release_dlss_nr_resources(); // GPU-fence-aware full mode switch""",
      """        const auto previous_nr_layout = configured_settings();
        const bool nr_family_changed =
            previous_nr_layout.nr_target_mode / 2U != settings.nr_target_mode / 2U;
        update_settings(settings);
        // A same-family 2<->3 or 0<->1 edit keeps the existing foveal models.
        // The normal GPU-fence-aware collector retires only deselected sources.
        // Different physical renderer families still require a full reset.
        if (nr_family_changed) release_dlss_nr_resources();""")

# C3: a pointer/handle-number selection is not durable across process launches.
# A NEW persisted key means old NrDuoFoveaSource=1/2 lines are ignored on
# migration and cannot silently select the wrong source on next launch.
patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrDuoFoveaSource", nr_duo_fovea_source)',
      'CHEEKY_SETTING("NrDuoFoveaSizeHint", nr_duo_fovea_source)')
# The previous patch's settings parser contains one string in the condition
# and one in two bounds/assignments. Convert all remaining exact key literals
# without touching the canonical C++ field name.
p=root/"uevr/settings_io.cpp"
data=p.read_text(encoding="utf-8")
count=data.count('"NrDuoFoveaSource"')
if count<1: raise RuntimeError("Could not find remaining old Duo parser key")
p.write_text(data.replace('"NrDuoFoveaSource"','"NrDuoFoveaSizeHint"'),
             encoding="utf-8",newline="\n")
print("FABLE-C3: parser migrated old pointer key to new size-based key")
patch("uevr/settings_io.cpp",
      '    candidate.nr_style = 0U; // Older files used the hardcoded Standard style.',
      '''    candidate.nr_style = 0U; // Older files used the hardcoded Standard style.
    candidate.nr_duo_fovea_source = 0U; // Ignore obsolete persisted pointer-based A/B''')
patch("uevr/runtime.cpp",
      'std::string_view(name) != "NrDuoFoveaSource"',
      'std::string_view(name) != "NrDuoFoveaSizeHint"')
patch("src/settings.hpp",
      'nr_duo_fovea_source{0U}; // 0=size auto;1=lower source ID;2=higher source ID',
      'nr_duo_fovea_source{0U}; // 0=auto (larger input);1=force larger input;2=force SMALLER input')

# Retain the 20%-separation guard for BOTH forced choices; no pointer order
# and no output-size-only inference. Output geometry can veto AUTO when it
# clearly contradicts input geometry. Forced choices intentionally override
# the output veto, not the minimum size separation.
p=root/"src/settings.cpp"; data=p.read_text(encoding="utf-8")
start=data.index('        int identified{};\n        if (settings.nr_duo_fovea_source) {')
stop=data.index('        if (!identified && settings.nr_target_mode == 1U) {',start)
new='''        const int input = compare_area(v[0]->evaluation_input_width,
            v[0]->evaluation_input_height, v[1]->evaluation_input_width,
            v[1]->evaluation_input_height);
        const int output = compare_area(v[0]->evaluation_output_width,
            v[0]->evaluation_output_height, v[1]->evaluation_output_width,
            v[1]->evaluation_output_height);
        int identified{};
        if (settings.nr_duo_fovea_source == 2U)
            identified = -input; // Explicit smaller *image*, not lower/higher handle
        else if (settings.nr_duo_fovea_source == 1U)
            identified = input; // Explicit larger *image*
        else
            identified = (input && output && input != output) ? 0 : input;
'''
data=data[:start]+new+data[stop:]
p.write_text(data,encoding="utf-8",newline="\n")
print("FABLE-C3: image-area-based Duo classifier, all cases fail closed on close sizes")

# C6: one geometry/role classification per NR evaluation, not two calls that
# can disagree while another thread registers or removes a source.
patch("src/settings.hpp",
      '[[nodiscard]] std::uint32_t cheeky_nr_source_role_for(const Settings&, std::uint64_t) noexcept;',
      '''struct CheekyNrSelection {
    std::uint32_t role{}, passes{};
};
[[nodiscard]] CheekyNrSelection cheeky_nr_selection(const Settings&, std::uint64_t) noexcept;
[[nodiscard]] std::uint32_t cheeky_nr_source_role_for(const Settings&, std::uint64_t) noexcept;''')
p=root/"src/settings.cpp";data=p.read_text(encoding="utf-8")
a=data.index('std::uint32_t cheeky_nr_selected_passes(')
b=data.index('bool cheeky_processing_allowed_for_view(',a)
old=data[a:b]
if old.count('return (run_first ? 1U : 0U) | (run_second ? 2U : 0U);')!=1:
    raise RuntimeError("Selection function changed since review")
new=old.replace('std::uint32_t cheeky_nr_selected_passes(', 'CheekyNrSelection cheeky_nr_selection(',1).replace(
    '    if (!settings.nr_enabled) return 0U;',
    '    if (!settings.nr_enabled) return {};').replace(
    '    return (run_first ? 1U : 0U) | (run_second ? 2U : 0U);',
    '    return {role, (run_first ? 1U : 0U) | (run_second ? 2U : 0U)};')
new+='''std::uint32_t cheeky_nr_selected_passes(const Settings& settings,
    const std::uint64_t view_id) noexcept {
    return cheeky_nr_selection(settings,view_id).passes;
}

'''
data=data[:a]+new+data[b:]
p.write_text(data,encoding="utf-8",newline="\n")
patch("src/dlss_nr.cpp",
      '''    const auto chosen = cheeky_nr_selected_passes(settings, frame.view_id);''',
      '''    const auto selection = cheeky_nr_selection(settings, frame.view_id);
    const auto chosen = selection.passes;''')
patch("src/dlss_nr.cpp",
      '''    const auto role = cheeky_nr_source_role(frame.view_id);''',
      '''    const auto role = selection.role;''')

# C6: one temporal-history skip on non-target native source, not a duplicate
# from both the new exclusion branch and old eye-independent failure branch.
patch("src/hooks.cpp",
      '''        if (!processed && settings.eye_independent_coverage) skip_dlss_nr_source_history(frame.view_id);''',
      '''        if (selected_passes && !processed && settings.eye_independent_coverage)
            skip_dlss_nr_source_history(frame.view_id);''')

# C2: routinely re-evaluate OWNED NR sources for stale roles and absent
# permission, including sources no longer submitting evaluations at all.
# Classify OUTSIDE nr_mutex to respect GPU/role/settings lock ordering; retire
# individual models and scratch resources only when identity/permission lost.
# This runs at existing submission-collection cadence, not on every skipped
# periphery evaluation. Exactly the same GPU-fence retire discipline is used.
p=root/"src/dlss_nr.cpp";data=p.read_text(encoding="utf-8")
start=data.index('void collect_dlss_nr_submissions() noexcept {')
stop=data.index('void skip_dlss_nr_history(',start)
old=data[start:stop]
if old.count('collect_retired_views();')!=1 or 'view.source_role' not in old:
    raise RuntimeError("Unexpected NR collector after safety patch")
collector='''void collect_dlss_nr_submissions() noexcept {
    std::lock_guard execution_lock(calibration12_execution_mutex());
    const auto live = current_settings();
    // Build an identity-only source snapshot while holding the owner mutex.
    // Never call stereo role classification while nr_mutex is held.
    constexpr auto pass2_bit = (1ULL << 63U);
    std::array<DlssViewId,64> physical_ids{};
    std::array<CheekyNrSelection,64> expected{};
    std::size_t source_count{};
    {
        std::lock_guard lock(nr_mutex);
        for (const auto& view : views) {
            if (view.retired || !view.source_role) continue;
            const auto physical = view.view_id & pass2_bit
                ? view.view_id ^ pass2_bit : view.view_id;
            bool found{};
            for (std::size_t i=0;i<source_count;++i)
                if (physical_ids[i]==physical) {found=true;break;}
            if (!found && source_count<physical_ids.size())
                physical_ids[source_count++]=physical;
        }
    }
    if (live.nr_enabled)
        for (std::size_t i=0;i<source_count;++i)
            expected[i]=cheeky_nr_selection(live,physical_ids[i]);

    std::array<DlssViewId,64> changed_inputs{};
    std::size_t changed_count{};
    {
        std::lock_guard lock(nr_mutex);
        for (auto& view : views) {
            if (view.retired) continue;
            if (!live.nr_enabled) {view.retired=true;continue;}
            if (!view.source_role) continue;
            const auto physical = view.view_id & pass2_bit
                ? view.view_id ^ pass2_bit : view.view_id;
            CheekyNrSelection selected{};
            for(std::size_t i=0;i<source_count;++i)
                if(physical_ids[i]==physical){selected=expected[i];break;}
            const auto pass_mask=view.logical_pass==2U?2U:1U;
            if (selected.role != view.source_role || !(selected.passes & pass_mask)) {
                view.retired=true;
                bool seen{};
                for(std::size_t i=0;i<changed_count;++i)
                    if(changed_inputs[i]==physical){seen=true;break;}
                if(!seen && changed_count<changed_inputs.size())
                    changed_inputs[changed_count++]=physical;
            }
        }
        collect_retired_views(); // release only after all recording/queue uses retire
        if (!live.nr_enabled) {
            diagnostics.state = DlssNrState::disabled;
            diagnostics.skip_reason = views.empty() ? nullptr :
                "NR disabled; waiting for recordings to retire";
            if (views.empty()) {
                diagnostics.region_width = diagnostics.region_height = 0U;
                diagnostics.working_width = diagnostics.working_height = 0U;
                diagnostics.intermediate_vram_bytes = 0U;
            }
        }
    }
    // Inputs have an independent mutex. Retire them AFTER nr_mutex is released
    // and under the already-held execution gate, preserving lock order.
    for (std::size_t i=0;i<changed_count;++i)
        release_dlss_nr_inputs(changed_inputs[i]);
}

'''
data=data[:start]+collector+data[stop:]
p.write_text(data,encoding="utf-8",newline="\n")
print("FABLE-C2: selective stale-source + pass-aware GPU-fenced retirement")

# C4: a family change is a fresh-model allocation (not arbitrary flat 2 GiB).
# Handle changed size hints and mask growth BEFORE old early-return tuning.
patch("uevr/nr_lite_budget_policy.hpp",
      '#include <cstdint>',
      '#include <cstdint>\n#include <algorithm>')
patch("uevr/nr_lite_budget_policy.hpp",
      '''    // Pass 2 has its own feature key. Changes here can allocate a new opaque''',
      '''    if (current.nr_enabled && requested.nr_enabled) {
        // A renderer-family switch creates new physical NGX models while the
        // prior family is still pending GPU retirement. Reserve no more than
        // enabling the REQUESTED set of features from scratch.
        if (current.nr_target_mode/2U != requested.nr_target_mode/2U) {
            auto fresh=current;
            fresh.nr_enabled=false;
            return nr_lite_required_headroom(fresh,requested);
        }
        const auto old_allow=cheeky_nr_target_mask(current);
        const auto new_allow=cheeky_nr_target_mask(requested);
        const auto added1=(requested.nr_pass1_views & new_allow) &
            ~(current.nr_pass1_views & old_allow);
        const auto added2=requested.nr_passes>=2U
            ? (requested.nr_pass2_views & new_allow) &
              ~(current.nr_passes>=2U ? (current.nr_pass2_views & old_allow):0U)
            : 0U;
        const auto mask_reserve=(added1 && added2 ? 3072ULL :
            added1 || added2 ? 2048ULL : 0ULL)*nr_lite_mib;
        const auto hint_reserve=current.nr_duo_fovea_source != requested.nr_duo_fovea_source
            ? 1536ULL*nr_lite_mib : 0ULL;
        if(mask_reserve || hint_reserve)
            return (std::max)(mask_reserve,hint_reserve);
    }
    // Pass 2 has its own feature key. Changes here can allocate a new opaque''')
# The old mask-growth/hint branches remain for crop/per-pass growth, but are
# unreachable for the new settings cases handled above. Their semantics are
# now deliberately constrained by the more complete preflight.

# C6: make the logged observer's source liveness exactly match the classifier.
patch("src/settings.cpp",
      '''        if (!view.evaluation_calls || view.graphics_api!=12U ||
            !view.evaluation_input_width || !view.evaluation_input_height ||
            !view.evaluation_output_width || !view.evaluation_output_height ||''',
      '''        if (!view.evaluation_calls || view.graphics_api!=12U ||
            !view.evaluation_output_width || !view.evaluation_output_height ||''')

print("PASS Fable C1-C4/C6 core patch: runtime, sources, policy, histories")
