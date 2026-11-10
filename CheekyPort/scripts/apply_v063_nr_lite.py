#!/usr/bin/env python3
"""Apply the STALKER 2 / TriView NR-only and lifetime-safe VRAM pass.

Run AFTER apply_v063_nr_view.py against pinned upstream Cheeky 0.6.3.
No game SR, frame generation, eye-tracking or TriView B42 files are patched.
"""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()

def edit(path, before, after, expected=1):
    target = root / path
    source = target.read_text(encoding="utf-8")
    count = source.count(before)
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} copies, got {count} of {before[:95]!r}")
    target.write_text(source.replace(before, after), encoding="utf-8", newline="\n")
    print("NR-LITE", path, count)

# Native SR must remain game-owned. Cheeky's private SR pipeline is never
# entered, but its interception/fallback still runs the Before-NR substitution.
p = root / "src/hooks.cpp"
s = p.read_text(encoding="utf-8")
first = s.index("[[nodiscard]] bool evaluate_native_d3d12_canonical(")
last = s.index("\n[[nodiscard]] D3D12BackendCallbacks d3d12_backend_callbacks(", first)
if s[first:last].count("private_attempted = true;") != 1:
    raise RuntimeError("Upstream private SR function changed; review the bypass")
s = s[:first] + """// NR-LITE: game-native DLSS SR is always authoritative. The caller has
// already prepared the optional NR-before-SR color substitution. Returning
// false here drives the existing, lifetime-aware native SR fallback.
[[nodiscard]] bool evaluate_native_d3d12_canonical(
    ID3D12GraphicsCommandList*,
    const NgxHandle*,
    const NgxParameters*,
    const Settings&,
    const D3D12BackendCallbacks&,
    NgxResult&,
    bool& private_attempted
) noexcept {
    private_attempted = false;
    return false;
}
""" + s[last:]
p.write_text(s, encoding="utf-8", newline="\n")

# CPU-side order/identity probe. Not an atlas enable switch: knowing a
# second eye was presented does NOT prove its pre-SR resource was written
# before the first NR dispatch. The real contract requires a render hook.
edit("src/hooks.cpp",
    '        original_color = get_d3d12_parameter_resource(params, "Color");\n        auto* processed = prepare(list, params, settings);',
    '''        original_color = get_d3d12_parameter_resource(params, "Color");
        static std::atomic<std::uint64_t> atlas_probe_counter{};
        const auto probe = atlas_probe_counter.fetch_add(1U, std::memory_order_relaxed) + 1U;
        if (probe <= 32U || probe % 256U == 0U) {
            const auto input_desc = original_color ? original_color->GetDesc() : D3D12_RESOURCE_DESC{};
            trace_event("[CheekyNR][AtlasProbe] seq=%llu view=%llu list=%p color=%p depth=%p mv=%p source=%llux%u input=%ux%u output=%ux%u offset=%u,%u",
                static_cast<unsigned long long>(probe),
                static_cast<unsigned long long>(frame.view_id),
                static_cast<void*>(list), static_cast<void*>(original_color),
                static_cast<void*>(frame.depth), static_cast<void*>(frame.motion_vectors),
                static_cast<unsigned long long>(input_desc.Width), input_desc.Height,
                frame.input_width, frame.input_height, frame.output_width, frame.output_height,
                frame.color_base_x, frame.color_base_y);
        }
        auto* processed = prepare(list, params, settings);''')

# A previous Cheeky profile may have FG enabled even though this reduced UI
# no longer shows FG controls. Force Cheeky's own FG completely OFF and do not
# let old saved profiles disable Reflex on the user's behalf. VectorXR remains
# a separate product and is not altered by these settings.
edit("src/settings.cpp",
    '''    fg_settings = settings.fg;
    nr_passes = std::clamp(settings.nr_passes, 1U, max_nr_passes);''',
    '''    fg_settings = settings.fg;
    fg_settings.enabled = false; // NR Lite must not run Cheeky FG
    fg_settings.force_reflex_off = false; // NR Lite does not override Reflex
    nr_passes = std::clamp(settings.nr_passes, 1U, 2U);''')
edit("src/settings.cpp",
    '''    reflex_override::requested.store(settings.fg.force_reflex_off,std::memory_order_release);''',
    '''    reflex_override::requested.store(false,std::memory_order_release);''')

# The current pool keeps full-sized private Before-NR inputs. Report committed
# allocation size (not raw width*height) and whether a GPU recording still owns
# each resource. Never free until NrLifetime observes recording+queue retirement.
edit("src/dlss_nr_input.hpp",
    "[[nodiscard]] ID3D12Resource* prepare_dlss_nr_input(",
    '''struct NrInputMemoryStats {
    std::uint64_t bytes{}, busy_bytes{};
    std::uint32_t resources{}, busy_resources{}, retired_resources{};
};
[[nodiscard]] NrInputMemoryStats dlss_nr_input_memory_stats() noexcept;
[[nodiscard]] ID3D12Resource* prepare_dlss_nr_input(''')
edit("src/dlss_nr_input.cpp",
    "void collect_dlss_nr_input_submissions() noexcept {",
    '''NrInputMemoryStats dlss_nr_input_memory_stats() noexcept {
    std::lock_guard lock(mutex);
    NrInputMemoryStats stats{};
    for (auto& input : inputs) {
        if (!input.color || !input.device) continue;
        ++stats.resources;
        if (input.retired) ++stats.retired_resources;
        const auto desc = input.color->GetDesc();
        const auto info = input.device->GetResourceAllocationInfo(0U, 1U, &desc);
        const auto bytes = info.SizeInBytes < (1ULL << 40U) ? info.SizeInBytes : 0ULL;
        stats.bytes += bytes;
        if (!complete(input)) {
            ++stats.busy_resources;
            stats.busy_bytes += bytes;
        }
    }
    return stats;
}
void collect_dlss_nr_input_submissions() noexcept {''')

# No 2-pass scratch when using just one pass: retire the pass_output texture
# only if the entire GPU recording lifetime is complete. Subsequent pass-2
# switches recreate it on demand, with no changes to model quality/settings.
edit("src/dlss_nr.cpp",
    "    std::uint64_t last_use{};\n    ID3D12Resource* game_output{};",
    "    std::uint64_t last_use{};\n    std::uint64_t last_use_tick_ms{};\n    ID3D12Resource* game_output{};")
edit("src/dlss_nr.cpp",
    "    const bool border_only = false\n) noexcept {\n    auto* exposure",
    '''    const bool border_only = false,
    const bool need_second_pass = false
) noexcept {
    // Do not retain a spare second-pass output after switching to one pass.
    // The resources are still owned by any incomplete command-list recording.
    if (!border_only && !need_second_pass) {
        for (auto& cached : view.gpu_resources) {
            if (!cached.pass_output) continue;
            cached.uses.collect();
            if (cached.uses.empty()) release(cached.pass_output);
        }
    }
    auto* exposure''')
edit("src/dlss_nr.cpp",
    "    gpu.last_use = ++view.gpu_use_sequence;\n            return &gpu;",
    "    gpu.last_use = ++view.gpu_use_sequence;\n            gpu.last_use_tick_ms = GetTickCount64();\n            return &gpu;",
    expected=1)
edit("src/dlss_nr.cpp",
    "        gpu.last_use = ++view.gpu_use_sequence;\n        return &gpu;",
    "        gpu.last_use = ++view.gpu_use_sequence;\n        gpu.last_use_tick_ms = GetTickCount64();\n        return &gpu;")
edit("src/dlss_nr.cpp",
    "    gpu.last_use = ++view.gpu_use_sequence;\n    if (border_only)",
    "    gpu.last_use = ++view.gpu_use_sequence;\n    gpu.last_use_tick_ms = GetTickCount64();\n    if (border_only)")
edit("src/dlss_nr.cpp",
    '''        codec_region,
        working_width,
        working_height
    );
    if (gpu == nullptr) return false;''',
    '''        codec_region,
        working_width,
        working_height,
        false,
        settings.nr_passes > 1U
    );
    if (gpu == nullptr) return false;''')

# A second-pass NGX feature can retain much more opaque NVIDIA memory than
# the pass_output texture. Retire pass-2/3 handles when switching down to one
# pass. The normal NrLifetime collector decides when release is safe.
edit("src/dlss_nr.cpp",
    '''    ++diagnostics.candidate_calls;
    auto& view = find_or_create_view(frame.view_id);''',
    '''    ++diagnostics.candidate_calls;
    const auto wanted_passes = std::clamp(settings.nr_passes, 1U, max_nr_passes);
    for (auto& stale_pass : views) {
        if (stale_pass.view_id == frame.view_id && stale_pass.pass >= wanted_passes)
            stale_pass.retired = true;
    }
    collect_retired_views(); // no GPU wait; incomplete recordings stay alive
    auto& view = find_or_create_view(frame.view_id);''')

# Conserve truly abandoned scratch sets, but NOT the live rotating pool.
# A GPU-finished idle slot with no use for >3 seconds is releasable provided
# another idle slot of the same class remains warm. Never wait on a fence.
edit("src/dlss_nr.cpp",
    '''    for (auto& gpu : view.gpu_resources) {
        if (gpu.exposure.Get() != exposure) continue;''',
    '''    if (!border_only) {
        const auto now = GetTickCount64();
        unsigned warm_idle{};
        for (auto& cached : view.gpu_resources) {
            if (cached.border_only || cached.width != region.width ||
                cached.height != region.height ||
                cached.working_width != working_width ||
                cached.working_height != working_height) continue;
            cached.uses.collect();
            if (cached.uses.empty()) ++warm_idle;
        }
        for (auto it = view.gpu_resources.begin(); it != view.gpu_resources.end();) {
            if (warm_idle <= 1U) break;
            if (it->border_only || it->width != region.width || it->height != region.height ||
                it->working_width != working_width || it->working_height != working_height ||
                now < it->last_use_tick_ms ||
                now - it->last_use_tick_ms < 3000U) { ++it; continue; }
            it->uses.collect();
            if (!it->uses.empty()) { ++it; continue; }
            release_gpu(*it);
            it = view.gpu_resources.erase(it);
            --warm_idle;
        }
    }
    for (auto& gpu : view.gpu_resources) {
        if (gpu.exposure.Get() != exposure) continue;''')

# Sparse allocation accounting; opaque NGX model allocations cannot be inferred
# from textures. Log counts separately to compare budget telemetry externally.
edit("src/dlss_nr.cpp",
    "void evict_retired_features(ViewState& view) noexcept {",
    '''std::uint64_t nr_tracked_allocation(ID3D12Device* device, ID3D12Resource* resource) noexcept {
    if (!device || !resource) return 0U;
    const auto desc = resource->GetDesc();
    const auto info = device->GetResourceAllocationInfo(0U, 1U, &desc);
    return info.SizeInBytes < (1ULL << 40U) ? info.SizeInBytes : 0ULL;
}
void log_nr_lite_memory() noexcept {
    static ULONGLONG next_log_ms{};
    const auto now = GetTickCount64();
    if (now < next_log_ms) return;
    next_log_ms = now + 2000U;
    std::uint64_t scratch_bytes{}, busy_bytes{};
    std::uint32_t scratch_sets{}, busy_sets{}, live_features{}, retired_features{}, second_pass_outputs{};
    for (auto& view : views) {
        if (view.handle) ++live_features;
        retired_features += static_cast<std::uint32_t>(view.retired_features.size());
        for (auto& gpu : view.gpu_resources) {
            auto* resource = gpu.original_output ? gpu.original_output : gpu.neural_output;
            if (!resource) continue;
            Microsoft::WRL::ComPtr<ID3D12Device> device;
            if (FAILED(resource->GetDevice(IID_PPV_ARGS(&device)))) continue;
            const auto size = nr_tracked_allocation(device.Get(), gpu.original_output) +
                nr_tracked_allocation(device.Get(), gpu.color_proxy) +
                nr_tracked_allocation(device.Get(), gpu.neural_output) +
                nr_tracked_allocation(device.Get(), gpu.pass_output) +
                nr_tracked_allocation(device.Get(), gpu.guides.motion.Get()) +
                nr_tracked_allocation(device.Get(), gpu.guides.depth.Get());
            scratch_bytes += size;
            ++scratch_sets;
            if (gpu.pass_output) ++second_pass_outputs;
            gpu.uses.collect();
            if (!gpu.uses.empty()) { busy_bytes += size; ++busy_sets; }
        }
    }
    const auto inputs = dlss_nr_input_memory_stats();
    trace_event("[CheekyNR][VRAM] scratchMiB=%.1f scratchSets=%u busyMiB=%.1f busySets=%u beforeMiB=%.1f beforeSlots=%u beforeBusyMiB=%.1f beforeBusy=%u beforeRetired=%u ngxFeatures=%u ngxRetired=%u pass2Outputs=%u (NGX opaque allocations excluded)",
        static_cast<double>(scratch_bytes) / 1048576.0, scratch_sets,
        static_cast<double>(busy_bytes) / 1048576.0, busy_sets,
        static_cast<double>(inputs.bytes) / 1048576.0, inputs.resources,
        static_cast<double>(inputs.busy_bytes) / 1048576.0, inputs.busy_resources,
        inputs.retired_resources, live_features, retired_features, second_pass_outputs);
}
void evict_retired_features(ViewState& view) noexcept {''')
edit("src/dlss_nr.cpp",
    '''    collect_retired_views();
    diagnostics.skip_reason = nullptr;''',
    '''    collect_retired_views();
    log_nr_lite_memory();
    diagnostics.skip_reason = nullptr;''')

# Remove every unused feature panel. Keep only the NR controls, the two saved
# templates, and direct diagnosis of the native SR/NR route. We intentionally
# leave the backend configuration/persistence machinery intact for this build.
p = root / "uevr/scripts/cheeky_foveated_dlss.lua"
s = p.read_text(encoding="utf-8")
start = s.index('local function fg_optical(method)')
donate_start = s.index('local function donate_button()', start)
apply_start = s.index('local function apply_buttons(id)', donate_start)
section_start = s.index('local function section(label)', apply_start)
rows_start = s.index('local function rows(id, entries)', section_start)
reset_start = s.index('local function reset_group(label, group)', rows_start)
next_start = s.index('local alignment = ', reset_start)
panel_start = s.index('uevr.lua.add_script_panel(', next_start)
common = (
    s[:start]
    + s[donate_start:section_start]  # Includes original donation UI + apply buttons.
    + s[section_start:rows_start]
    + s[reset_start:next_start]
)
panel = """uevr.lua.add_script_panel("Cheeky TriView NR Lite", function()
    local changed, value = imgui.checkbox("Enable DLSS-NR plugin for this game", enabled)
    if changed then set_enabled(value) end
    if loader_error then text(loader_error) end
    if not enabled then return end
    if loader_state ~= "enabled" then
        text("NR runtime: " .. tostring(loader_state or "waiting"))
        return
    end
    if not status then
        text("Waiting for NR settings from the plugin")
        if imgui.button("Reconnect") then send("get") end
        return
    end
    if not imgui.tree_node("DLSS 5 NR — game-native SR") then return end
    donate_button()
    text("Only NVIDIA NR is applied by this plugin. STALKER 2 retains its own DLSS SR.")
    text("Atlas batching requires verified two-eye inputs; this build collects routing diagnostics.")
    text("NR status: " .. tostring(status.nr or "Waiting"))
    if status.ready == false then text("Processing is paused") end
    imgui.begin_disabled(pending_apply ~= nil and pending_apply.reset_group ~= nil)
    check("Enable DLSS-NR", "NrEnabled")
    if draft.EyeProcessingMode ~= nil then
        combo("NR source views", "EyeProcessingMode",
            {[0]="All DLSS views", [1]="Duo view 0", [2]="Duo view 1",
             [3]="TriView: both stereo foveas"}, {3,0,1,2})
        text("Mode 3 fails closed when the live TriView geometry is ambiguous.")
    end
    if draft.NrProcessingOrder ~= nil then
        combo("NR placement", "NrProcessingOrder",
            {[0]="After SR", [1]="Before SR (recommended)"})
    end
    if draft.NrEnabled then
        check("Enable NR subregion", "NrFoveated")
        if draft.NrFoveated then
            check("Match original SR crop", "NrUseSrFoveation")
            if not draft.NrUseSrFoveation then
                slider("NR width", "NrWidth", 0.2, 1)
                slider("NR height", "NrHeight", 0.2, 1)
                slider("NR roundness", "NrRoundness", 0, 1)
                slider("NR transition", "NrTransitionWidth", 0, 0.3)
            end
            check("NR border debug", "NrAlignmentBorder")
        end
        section("Neural rendering")
        slider("NR working scale", "NrWorkingScale", 0.1, 1)
        if draft.NrPreset ~= nil then
            combo("NVIDIA NR model", "NrPreset",
                {[0]="Runtime default", [1]="Original NR", [2]="Faster NR"}, {0,1,2})
        end
        combo("Style", "NrStyle", {[0]="Standard", [1]="Natural", [2]="Cinematic"})
        slider("Intensity", "NrIntensity", 0, 1)
        slider("Local tone", "NrLocalToneStrength", 0, 2)
        slider("Local structure", "NrLocalStructureStrength", 0, 2)
        check("Automatic mask", "NrAutomaticMask")
        if draft.NrAutomaticMask then slider("Skin structure", "NrSkinStructureStrength", 0, 2) end
        slider("Paper white", "NrPaperWhiteScale", 0.01, 8)
        slider("HDR transfer", "NrHdrTransferStrength", 0, 2)
        slider("Color strength", "NrColorStrength", 0, 2)
        combo("Depth convention", "NrDepthConvention",
            {[0]="Game/default", [1]="Normal", [2]="Reversed"})
        slider("Motion scale X", "NrMotionScaleXMultiplier", -4, 4)
        slider("Motion scale Y", "NrMotionScaleYMultiplier", -4, 4)
        if draft.NrPasses ~= nil then
            section("Model passes — one or two")
            combo("Model passes", "NrPasses", {[1]="1", [2]="2"}, {1,2})
            if (draft.NrPasses or 1) >= 2 then nr_extra_pass(2) end
        end
    end
    section("Saved NR templates")
    if draft.NrTemplateActive ~= nil then
        text("Active template: " .. tostring(draft.NrTemplateActive))
    end
    local blocked = next(dirty) ~= nil or pending_apply ~= nil
    imgui.begin_disabled(blocked)
    if imgui.button("Save Template 1") then send("nr_template_save_1") end
    imgui.same_line()
    if imgui.button("Load Template 1") then send("nr_template_load_1") end
    if imgui.button("Save Template 2") then send("nr_template_save_2") end
    imgui.same_line()
    if imgui.button("Load Template 2") then send("nr_template_load_2") end
    if imgui.button("Toggle Template 1 / 2") then send("nr_template_toggle") end
    imgui.end_disabled()
    if next(dirty) or pending_apply then apply_buttons("nr") end
    if imgui.button("Reset NR history") then send("reset_nr") end
    imgui.same_line()
    if imgui.button("Refresh status") then send("get") end
    text("VRAM and atlas-routing diagnostics appear in the plugin log every 2 s.")
    imgui.end_disabled()
    imgui.tree_pop()
    flush_edits()
end)
"""
if 'nr_template_save_1' not in s or 'EyeProcessingMode' not in s:
    raise RuntimeError("Existing user templates / TriView view routing missing")
p.write_text(common + "\n" + panel, encoding="utf-8", newline="\n")
print("NR-LITE UI: removed FG, eye tracking and private SR panels")

# Static generation tests do not pretend the atlas is scheduled. Failure to
# intercept the native fallback is a fatal integration regression.
hook = (root / "src/hooks.cpp").read_text(encoding="utf-8")
assert "NativeNrInputScope nr_input{" in hook
assert "result = original(" in hook
assert "[CheekyNR][AtlasProbe]" in hook
assert "private_attempted = false;\n    return false;" in hook
assert "[CheekyNR][VRAM]" in (root / "src/dlss_nr.cpp").read_text(encoding="utf-8")
print("NR-LITE static checks passed")
