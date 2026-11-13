#!/usr/bin/env python3
"""Configurable headroom cap (1536 MiB default) for Cheeky 0.6.3 Duo/Tri NR.

Apply after Fable C1-C6 patches, before CI C++ compilation. Existing
per-transaction estimates decide WHETHER admission is needed; user-configured
cap limits HOW MUCH spare DXGI local-memory budget they require.

This is a cap (min) rather than a blanket floor: 768 MiB rekeys stay at 768,
reduction/disable stays at zero, and 2048/2560/4096 estimates default to 1536.
NGX opaque allocations remain unknown and OOM is still possible.
"""
from pathlib import Path
import sys
root = Path(sys.argv[1]).resolve()

def patch(path, before, after):
    file = root / path
    source = file.read_text(encoding="utf-8")
    count = source.count(before)
    if count != 1:
        raise RuntimeError(f"{path}: strict anchor must occur once, got {count}: {before[:100]!r}")
    file.write_text(source.replace(before, after, 1), encoding="utf-8", newline="\n")
    print("NR-GUARD-1536", path)

# Independent new persisted key; older INIs get Settings{}'s 1536 MiB default.
patch("src/settings.hpp",
      "    bool nr_enabled{false};",
      """    bool nr_enabled{false};
    // Max policy-requested free DXGI local budget for an NR expansion.
    // 1536 MiB default; no impact on edits that need no new model allocation.
    std::uint32_t nr_vram_guard_mib{1536U};""")

patch("src/settings.cpp",
      "std::atomic<bool> nr_enabled{false};",
      """std::atomic<bool> nr_enabled{false};
std::atomic<std::uint32_t> nr_vram_guard_mib{1536U};""")

patch("src/settings.cpp",
      "    settings.nr_enabled = nr_enabled.load(std::memory_order_acquire);",
      """    settings.nr_enabled = nr_enabled.load(std::memory_order_acquire);
    settings.nr_vram_guard_mib = nr_vram_guard_mib.load(std::memory_order_acquire);""")

patch("src/settings.cpp",
      "    nr_enabled.store(settings.nr_enabled, std::memory_order_release);",
      """    nr_enabled.store(settings.nr_enabled, std::memory_order_release);
    nr_vram_guard_mib.store((std::clamp)(settings.nr_vram_guard_mib, 512U, 4096U),
        std::memory_order_release);""")

patch("uevr/settings_fields.inc",
      'CHEEKY_SETTING("NrEnabled", nr_enabled)',
      '''CHEEKY_SETTING("NrEnabled", nr_enabled)
CHEEKY_SETTING("NrVramGuardMiB", nr_vram_guard_mib)''')

patch("uevr/settings_io.cpp",
      '    if (key == "FgPacingClock") {',
      '''    if (key == "NrVramGuardMiB") {
        std::uint32_t limit{};
        if (!parse(value, limit) || limit < 512U || limit > 4096U) return false;
        s.nr_vram_guard_mib = limit;
        return true;
    }
    if (key == "FgPacingClock") {''')

# Don't let an NR appearance template secretly change a user's safety
# preference. NR "reset defaults" does reset it explicitly to 1536.
patch("uevr/runtime.cpp",
      'std::string_view(name) != "NrDuoFoveaSizeHint") settings.field = stored.field;',
      'std::string_view(name) != "NrDuoFoveaSizeHint" && std::string_view(name) != "NrVramGuardMiB") settings.field = stored.field;')

patch("uevr/nr_lite_budget_policy.hpp",
      '''[[nodiscard]] inline bool nr_lite_has_headroom(''',
      '''// User-adjustable cap on admission policy. Not an allocation reservation:
 // DXGI reports live local budget; the NGX driver owns opaque model memory.
[[nodiscard]] inline std::uint64_t nr_lite_effective_headroom(
    const Settings& current, const Settings& requested) noexcept {
    const auto policy = nr_lite_required_headroom(current, requested);
    if (!policy) return 0ULL; // Reductions and non-allocating edits stay free.
    const auto limit = (std::clamp)(requested.nr_vram_guard_mib, 512U, 4096U);
    const auto cap = static_cast<std::uint64_t>(limit) * nr_lite_mib;
    return (std::min)(policy, cap);
}

[[nodiscard]] inline bool nr_lite_has_headroom(''')

patch("uevr/runtime.cpp",
      '    const auto required = nr_lite_required_headroom(previous, next);',
      '''    const auto policy_required = nr_lite_required_headroom(previous, next);
    const auto required = nr_lite_effective_headroom(previous, next);''')

patch("uevr/runtime.cpp",
      '''    const auto required_mib = required >> 20U;''',
      '''    const auto required_mib = required >> 20U;
    const auto policy_mib = policy_required >> 20U;''')

patch("uevr/runtime.cpp",
      '''        trace_event("[CheekyNR][VRAMGuard] approved action=%s freeMiB=%llu reserveMiB=%llu nrFoveated=%u passes=%u",
            reason, static_cast<unsigned long long>(free_mib),
            static_cast<unsigned long long>(required_mib),
            next.nr_foveated ? 1U : 0U, next.nr_passes);''',
      '''        trace_event("[CheekyNR][VRAMGuard] approved action=%s freeMiB=%llu reserveMiB=%llu policyMiB=%llu capMiB=%u nrFoveated=%u passes=%u",
            reason, static_cast<unsigned long long>(free_mib),
            static_cast<unsigned long long>(required_mib),
            static_cast<unsigned long long>(policy_mib), next.nr_vram_guard_mib,
            next.nr_foveated ? 1U : 0U, next.nr_passes);''')

patch("uevr/runtime.cpp",
      '''    s.message = "NR change refused: insufficient free VRAM for safe model reallocation. "
                "Keep NR foveation enabled or lower the TriView resolution first.";''',
      '''    s.message = "NR change refused: DXGI free VRAM below the required headroom. "
                "Reduce NR work or adjust the NR VRAM guard cap (increases OOM risk).";''')

patch("uevr/runtime.cpp",
      '''    trace_event("[CheekyNR][VRAMGuard] REJECTED action=%s valid=%u usedMiB=%llu budgetMiB=%llu freeMiB=%llu reserveMiB=%llu nrFoveated=%u passes=%u",
        reason, valid ? 1U : 0U,
        static_cast<unsigned long long>(usage >> 20U),
        static_cast<unsigned long long>(budget >> 20U),
        static_cast<unsigned long long>(free_mib),
        static_cast<unsigned long long>(required_mib),
        next.nr_foveated ? 1U : 0U, next.nr_passes);''',
      '''    trace_event("[CheekyNR][VRAMGuard] REJECTED action=%s valid=%u usedMiB=%llu budgetMiB=%llu freeMiB=%llu reserveMiB=%llu policyMiB=%llu capMiB=%u nrFoveated=%u passes=%u",
        reason, valid ? 1U : 0U,
        static_cast<unsigned long long>(usage >> 20U),
        static_cast<unsigned long long>(budget >> 20U),
        static_cast<unsigned long long>(free_mib),
        static_cast<unsigned long long>(required_mib),
        static_cast<unsigned long long>(policy_mib), next.nr_vram_guard_mib,
        next.nr_foveated ? 1U : 0U, next.nr_passes);''')

# Live menu setting (explicit control and persistent key), plus truthful
# "policy vs effective" explanation and current DXGI headroom.
patch("uevr/scripts/cheeky_foveated_dlss.lua",
      '    combo("NR target layout", "NrTargetMode", target_labels, {0,1,2,3})',
      '''    combo("NR target layout", "NrTargetMode", target_labels, {0,1,2,3})
    if draft.NrVramGuardMiB ~= nil then
        slider("Max VRAM admission reserve (MiB)", "NrVramGuardMiB", 512, 4096, true)
        text("Default 1536 MiB. Caps the NR allocation guard; does not reserve VRAM.")
        text("Changes needing 0 MiB remain allowed; changes needing less than this")
        text("limit keep their smaller policy threshold. NVIDIA model VRAM is opaque.")
        local applied_cap = tonumber((status.settings or {}).NrVramGuardMiB) or 1536
        local current_mem = status.gpu_memory and status.gpu_memory["local"]
        if current_mem and current_mem.valid then
            text(string.format("Applied guard cap: %d MiB | DXGI free: %.0f MiB",
                applied_cap, (tonumber(current_mem.headroom_bytes) or 0) / 1048576))
        else
            text("Applied guard cap: " .. tostring(applied_cap) .. " MiB | DXGI headroom unknown")
        end
        if (draft.NrVramGuardMiB or 1536) < 1024 then
            text("CAUTION: a low cap raises the risk of driver OOM or GPU device loss.")
        end
    end''')

# Log analysis corroborated the guard refusal pattern without making changes
# to the feature cache, per-eye routes, FG or native game DLSS SR.
print("PASS adjustable VRAM admission cap: 1536 default, persisted in UEVR and Lua")
