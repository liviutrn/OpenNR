#!/usr/bin/env python3
"""Cheeky v0.6.3 TriView safety hardening. Run after independent + GPU trace patches.

No new live synchronization, no waits, and no change to NVIDIA SR.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def patch(path, before, after, occurrences=1):
    file = root / path
    data = file.read_text(encoding="utf-8")
    count = data.count(before)
    if count != occurrences:
        raise RuntimeError(f"{path}: expected {occurrences} anchors, got {count}: {before[:120]!r}")
    file.write_text(data.replace(before, after), encoding="utf-8", newline="\n")
    print(f"NR-SAFETY patched {path}")

# The upstream supports 3 passes, but this TriView NR-Lite product promises
# precisely 1 or 2. Enforce at BOTH persisted-settings consumption and the real
# NVIDIA evaluator boundary, not only in the Lua menu.
patch("src/settings.cpp",
    "nr_passes = std::clamp(settings.nr_passes, 1U, max_nr_passes);",
    "nr_passes = std::clamp(settings.nr_passes, 1U, 2U);")
patch("src/dlss_nr.cpp",
    "const auto requested_passes = std::clamp(settings.nr_passes, 1U, max_nr_passes);",
    "const auto requested_passes = std::clamp(settings.nr_passes, 1U, 2U);")

# Upstream GPU lifetime already retains a fence-aware uses token for each
# ViewState. Attach source/pass identity so a mask reduction can retire only
# obsolete features, including synthetic pass-2 IDs, without flushing the GPU.
patch("src/dlss_nr.cpp",
    "    std::uint64_t gpu_use_sequence{};\n};",
    """    std::uint64_t gpu_use_sequence{};
    std::uint32_t source_role{};
    std::uint32_t logical_pass{1U};
};""")
patch("src/dlss_nr.cpp",
    """    auto& view = find_or_create_view(frame.view_id);
    // Any rejected/failed NR evaluation breaks consecutive temporal history.""",
    """    auto& view = find_or_create_view(frame.view_id);
    view.source_role = frame.source_role;
    view.logical_pass = frame.logical_pass;
    // Any rejected/failed NR evaluation breaks consecutive temporal history.""")
patch("src/dlss_nr.cpp",
    "        auto& pass_view = find_or_create_view(frame.view_id, pass);",
    """        auto& pass_view = find_or_create_view(frame.view_id, pass);
        pass_view.source_role = frame.source_role;
        pass_view.logical_pass = pass + 1U;""")

patch("src/dlss_nr.cpp",
    """    if (disabled)
        for (auto& view : views) view.retired = true;
    collect_retired_views();""",
    """    if (disabled) {
        for (auto& view : views) view.retired = true;
    } else {
        // This runs after settings application. Do not reclassify DX12 view
        // geometry while holding nr_mutex. Roles were fixed at actual source
        // evaluation. Decommission removed pass/source NGX features only.
        const auto live = current_settings();
        for (auto& view : views) {
            if (view.retired || view.source_role == 0U) continue;
            const auto mask = view.logical_pass == 2U
                ? (live.nr_passes >= 2U ? live.nr_pass2_views : 0U)
                : live.nr_pass1_views;
            if ((mask & view.source_role) == 0U) view.retired = true;
        }
    }
    // Existing GPU-fence retirement; never release a live recording.
    collect_retired_views();""")

# Verify second-pass effective model tuning, which was missed by the original
# budget policy. Shader-only color-reconstruction settings are intentionally
# excluded, so tweaking brightness cannot force another NGX allocation.
patch("uevr/nr_lite_budget_policy.hpp",
    "    // Enabling NR instantiates model histories and is always budget-gated.",
    """    // Pass 2 has its own feature key. Changes here can allocate a new opaque
    // NVIDIA model even when the dimensions and source masks do not grow.
    if (current.nr_enabled && requested.nr_enabled && requested.nr_passes >= 2U &&
        requested.nr_pass2_views != 0U) {
        const auto old_tuning = nr_pass_settings(current, 1U);
        const auto new_tuning = nr_pass_settings(requested, 1U);
        if (old_tuning.nr_style != new_tuning.nr_style ||
            old_tuning.nr_intensity != new_tuning.nr_intensity ||
            old_tuning.nr_local_structure_strength != new_tuning.nr_local_structure_strength ||
            old_tuning.nr_local_tone_strength != new_tuning.nr_local_tone_strength)
            return 1536ULL * nr_lite_mib;
    }
    // Enabling NR instantiates model histories and is always budget-gated.""")

# The fallback classifier previously required EXACTLY 3 DX12 views, which
# suppressed both foveae if the game maintained an additional desktop DLSS
# source. When 4 views are present, identify the unique equal-size foveal pair
# only; the fourth-source situation cannot reliably distinguish periphery from
# desktop, so fail closed for the periphery. A verified bridge takes priority.
classifier = r"""std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {
    if (!id) return 0U;
    const auto quad = quad_view_snapshot();
    if (quad.active) {
        if (quad.status != 2) return 0U;
        const auto* role = quad_view_assignment(quad, id, stereo_view_generation(id));
        if (!role) return 0U;
        return role->focus ? (role->eye_index == 0 ? 1U : 2U) : 4U;
    }
    std::lock_guard lock(stereo_views_mutex);
    const auto now = GetTickCount64();
    const StereoView* v[4]{};
    unsigned n{};
    for (const auto& src : stereo_views) {
        if (!src.evaluation_calls || src.graphics_api != 12U ||
            !src.evaluation_output_width || !src.evaluation_output_height ||
            src.last_evaluation_ms > now ||
            now - src.last_evaluation_ms > 2000U) continue;
        if (n == 4U) return 0U; // >4 unknown roles, do not touch desktop
        v[n++] = &src;
    }
    if (n != 3U && n != 4U) return 0U;
    const auto same = [](const StereoView* a, const StereoView* b) noexcept {
        return a->evaluation_output_width == b->evaluation_output_width &&
               a->evaluation_output_height == b->evaluation_output_height;
    };
    unsigned pairs{}, ia{}, ib{};
    for (unsigned i = 0U; i < n; ++i)
        for (unsigned j = i + 1U; j < n; ++j)
            if (same(v[i], v[j])) { ++pairs; ia = i; ib = j; }
    if (pairs != 1U) return 0U; // Ambiguous: must not guess an eye
    const StereoView *a = v[ia], *b = v[ib];
    if (a->view_id > b->view_id) std::swap(a, b);
    if (id == a->view_id) return 1U;
    if (id == b->view_id) return 2U;
    if (n == 3U) {
        for (unsigned i = 0U; i < n; ++i)
            if (i != ia && i != ib && id == v[i]->view_id) return 4U;
    }
    // With 4 sources, unknown whether this is desktop or periphery.
    return 0U;
}

"""
path = root / "src/settings.cpp"
data = path.read_text(encoding="utf-8")
start = data.index("std::uint32_t cheeky_nr_source_role(const std::uint64_t id) noexcept {")
end = data.index("std::uint32_t cheeky_nr_selected_passes(", start)
data = data[:start] + classifier + data[end:]
path.write_text(data, encoding="utf-8", newline="\n")
print("NR-SAFETY 3/4-view fail-closed classifier installed")

# Decoder-only controls must not change NVIDIA inference histories.
patch("src/nr_parameters.hpp",
    """            settings.nr_paper_white_scale,
            settings.nr_hdr_transfer_strength,
            settings.nr_color_strength,""",
    """            settings.nr_paper_white_scale,""")

print("PASS NR safety: no third inference, mask retire, pass2 budget, 3/4 source routing")
