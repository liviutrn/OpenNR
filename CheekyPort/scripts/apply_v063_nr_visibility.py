#!/usr/bin/env python3
"""NR Lite full-fovea defaults and applied-state diagnostics.
Runs after apply_v063_nr_view.py and apply_v063_nr_lite.py.
Strict anchors: fail CI if upstream changes, rather than silently making a bad build.
"""
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()

def edit(name, old, new):
    p = root / name
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected exactly one anchor, found {count}: {old[:90]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print(f"NR-TRACE patched: {name}: {old[:68]!r}")

# New installations use full source-fovea NR, before STALKER 2's native DLSS SR.
# Existing saved settings remain unchanged and can be switched via the UI,
# subject to the VRAM admission guard.
edit("src/settings.hpp", "NrProcessingOrder nr_processing_order{NrProcessingOrder::after_upscaling};",
     "NrProcessingOrder nr_processing_order{NrProcessingOrder::before_upscaling};")
edit("src/settings.hpp", "bool nr_foveated{true};", "bool nr_foveated{false};")
# TriView defaults to stereo foveas only (explicit All mode is still available).
edit("src/settings.hpp", "std::uint32_t eye_processing_mode{0U}; // All=0",
     "std::uint32_t eye_processing_mode{3U}; // All=0")
edit("src/settings.cpp", "std::atomic<std::uint32_t> eye_processing_mode{0U};",
     "std::atomic<std::uint32_t> eye_processing_mode{3U};")
edit("src/settings.cpp", "std::atomic<NrProcessingOrder> nr_order{NrProcessingOrder::after_upscaling};",
     "std::atomic<NrProcessingOrder> nr_order{NrProcessingOrder::before_upscaling};")
edit("src/settings.cpp", "std::atomic<bool> nr_foveated{true};",
     "std::atomic<bool> nr_foveated{false};")

# Model and codec resources already allocate region.width/height and scaled working
# sizes, NOT the full resolution, when cropped. The separate BEFORE-SR *input*
# texture is source-sized by design because native game DLSS consumes that
# complete texture; do not risk invalid SR subrect/base semantics by shrinking it.
edit("src/dlss_nr.hpp",
     "    std::uint32_t requested_passes{1U}, active_passes{};",
     """    std::uint32_t requested_passes{1U}, active_passes{};
    // Diagnostics updated under nr_mutex; counters refer to successful
    // model+codec output, not merely a requested setting or created feature.
    std::uint64_t decoded_frames{}, completed_two_pass_frames{}, before_sr_processed_frames{};
    std::uint64_t view_a_id{}, view_a_frames{}, view_b_id{}, view_b_frames{};""")
edit("src/dlss_nr.cpp",
     "    ++diagnostics.evaluation_calls;\n    view.history = history;",
     """    ++diagnostics.evaluation_calls;
    ++diagnostics.decoded_frames;
    if (pass_count >= 2U) ++diagnostics.completed_two_pass_frames;
    if (before) ++diagnostics.before_sr_processed_frames;
    const auto id = static_cast<std::uint64_t>(frame.view_id);
    if (id == diagnostics.view_a_id) ++diagnostics.view_a_frames;
    else if (id == diagnostics.view_b_id) ++diagnostics.view_b_frames;
    else if (!diagnostics.view_a_id) {
        diagnostics.view_a_id = id; ++diagnostics.view_a_frames;
    } else {
        // View B can change after a runtime reload; keep view A stable.
        diagnostics.view_b_id = id; diagnostics.view_b_frames = 1U;
    }
    view.history = history;""")

# Runtime JSON reports applied configuration, actual output coverage and actual
# successful passes. It does not mistake an NR evaluation for verified SR output.
edit("uevr/runtime.cpp",
     r'        << ",\"vram_bytes\":" << nr.intermediate_vram_bytes << "}"',
     r'''        << ",\"vram_bytes\":" << nr.intermediate_vram_bytes
        << ",\"requested_passes\":" << nr.requested_passes
        << ",\"active_passes\":" << nr.active_passes
        << ",\"decoded_frames\":" << nr.decoded_frames
        << ",\"completed_two_pass_frames\":" << nr.completed_two_pass_frames
        << ",\"before_sr_processed_frames\":" << nr.before_sr_processed_frames
        << ",\"view_a_id\":" << nr.view_a_id << ",\"view_a_frames\":" << nr.view_a_frames
        << ",\"view_b_id\":" << nr.view_b_id << ",\"view_b_frames\":" << nr.view_b_frames << "}"''')

# Rejection message survives frequent snapshots until a successful transaction
# or an explicit Discard, so a user cannot mistake a requested change for one
# that the VRAM guard refused.
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     "local error_text = nil",
     "local error_text = nil\nlocal last_apply_error = nil")
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     "    error_text = nil\nend\n\nlocal function set_enabled",
     "    error_text, last_apply_error = nil, nil\nend\n\nlocal function set_enabled")
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     """        if value.applied_request == pending_apply.id then
            for key, sent in pairs(pending_apply.values) do
                if dirty[key] == sent then dirty[key] = nil end
            end
        end
        pending_apply = nil""",
     """        if value.applied_request == pending_apply.id then
            last_apply_error = nil
            for key, sent in pairs(pending_apply.values) do
                if dirty[key] == sent then dirty[key] = nil end
            end
        else
            last_apply_error = "NOT APPLIED: " .. tostring(value.message or "Settings rejected")
        end
        pending_apply = nil""")
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     '        if status then for k, v in pairs(status.settings) do draft[k] = v end end',
     '        if status then for k, v in pairs(status.settings) do draft[k] = v end end\n        last_apply_error = nil')
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     '    text("NR status: " .. tostring(status.nr or "Waiting"))',
     '''    text("NR status: " .. tostring(status.nr or "Waiting"))
    if last_apply_error then text(last_apply_error) end
    local applied = status.settings or {}
    local nd = status.nr_details or {}
    text("APPLIED: NR " .. (applied.NrEnabled and "ON" or "OFF")
        .. " | views " .. tostring(applied.EyeProcessingMode or "?")
        .. " | crop " .. (applied.NrFoveated and "ON" or "OFF")
        .. " | passes " .. tostring(applied.NrPasses or "?")
        .. " | " .. (applied.NrProcessingOrder == 1 and "before SR" or "after SR"))
    if draft.NrFoveated ~= applied.NrFoveated or draft.NrPasses ~= applied.NrPasses
        or draft.EyeProcessingMode ~= applied.EyeProcessingMode then
        text("PENDING/REJECTED EDITS DIFFER FROM THE APPLIED VALUES ABOVE")
    end
    local pw, ph = tonumber(nd.processing_width) or 0, tonumber(nd.processing_height) or 0
    local rw, rh = tonumber(nd.region_width) or 0, tonumber(nd.region_height) or 0
    if pw > 0 and ph > 0 and rw > 0 and rh > 0 then
        text(string.format("Actual NR region: %dx%d of %dx%d (%.1f%% source pixels), working %dx%d",
            rw, rh, pw, ph, 100.0 * rw * rh / (pw * ph),
            tonumber(nd.working_width) or 0, tonumber(nd.working_height) or 0))
    end
    text(string.format("Output decoded: %d | completed 2-pass frames: %d | NR-before-SR processed: %d",
        tonumber(nd.decoded_frames) or 0, tonumber(nd.completed_two_pass_frames) or 0,
        tonumber(nd.before_sr_processed_frames) or 0))
    text(string.format("Source A: %.0f (%d frames) | Source B: %.0f (%d frames)",
        tonumber(nd.view_a_id) or 0, tonumber(nd.view_a_frames) or 0,
        tonumber(nd.view_b_id) or 0, tonumber(nd.view_b_frames) or 0))
    local mem = status.gpu_memory and status.gpu_memory.local
    if mem and mem.valid then
        text(string.format("Current DXGI VRAM headroom: %.0f MiB (excludes future model allocations)",
            (tonumber(mem.headroom_bytes) or 0) / 1048576))
    end
    if applied.NrEnabled and (tonumber(nd.decoded_frames) or 0) == 0 then
        text("NR enabled but no successful output decoded yet; inspect route/skip reason.")
    end
    if applied.NrPasses == 2 and (tonumber(nd.active_passes) or 0) < 2 then
        text("2 passes requested but most recent NR evaluation did NOT execute two passes.")
    end
    text("NR crop allocates crop-sized model/codec working surfaces; before-SR input handoff stays source-sized.")''')
edit("uevr/scripts/cheeky_foveated_dlss.lua",
     '        check("Enable NR subregion", "NrFoveated")',
     '''        check("Crop NR inside each source fovea (OFF = full fovea)", "NrFoveated")
        if not draft.NrFoveated then
            text("Full-source NR requires more VRAM. If refused, reduce TriView resolution first.")
        end''')

# Local safety assertions: ensure the build did not accidentally enable FG or
# replace native SR, and check that the new visibility contract was applied.
test = (root / "uevr/scripts/cheeky_foveated_dlss.lua").read_text(encoding="utf-8")
runtime = (root / "uevr/runtime.cpp").read_text(encoding="utf-8")
nr = (root / "src/dlss_nr.cpp").read_text(encoding="utf-8")
assert "last_apply_error" in test and "APPLIED: NR " in test
assert "completed_two_pass_frames" in runtime and "before_sr_processed_frames" in nr
assert 'fg_settings.enabled = false' in (root / "src/settings.cpp").read_text(encoding="utf-8")
assert "NR-LITE: game-native DLSS SR is always authoritative" in (root / "src/hooks.cpp").read_text(encoding="utf-8")
print("NR-TRACE PASS: full-fovea defaults, rejection acknowledgement and real pass/output counters")
