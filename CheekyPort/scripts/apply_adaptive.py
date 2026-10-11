#!/usr/bin/env python3
"""Cheeky/UEVR adaptive crop stage controller, isolated from OpenNR stable."""
from pathlib import Path
import argparse
import re

ap=argparse.ArgumentParser()
ap.add_argument("root",type=Path)
args=ap.parse_args()
root=args.root.resolve()

def replace(path, old, new):
    file=root/path
    text=file.read_text(encoding="utf-8")
    n=text.count(old)
    if n!=1: raise RuntimeError(f"{path}: expected one occurrence, got {n}: {old[:90]!r}")
    file.write_text(text.replace(old,new),encoding="utf-8",newline="\n")
    print(f"ADAPTIVE {path}: applied")

replace("src/settings.hpp",
    "    float nr_color_strength{1.0F};",
    """    float nr_color_strength{1.0F};
    // OpenNR r10-inspired six-stage crop controller. Percentages are relative
    // to the user-selected NR rectangle, not to full-eye dimensions.
    bool nr_adaptive_enabled{false};
    std::uint32_t nr_adaptive_mode{}; // 0 Auto, 1..6 Force stage
    std::uint32_t nr_adaptive_stage2{90}, nr_adaptive_stage3{80};
    std::uint32_t nr_adaptive_stage4{70}, nr_adaptive_stage5{60};
    float nr_adaptive_budget_ms{20.0F};
    float nr_adaptive_headroom_ms{1.0F};
    float nr_adaptive_disable_ms{24.0F};
    float nr_adaptive_resume_ms{14.0F};
    float nr_adaptive_smoothing_ms{250.0F};
    float nr_adaptive_decrease_hold_ms{350.0F};
    float nr_adaptive_increase_hold_ms{1200.0F};
    float nr_adaptive_cooldown_ms{1000.0F};""")
replace("src/settings.hpp",
    "[[nodiscard]] Settings current_settings() noexcept;",
    """[[nodiscard]] Settings current_settings() noexcept;
void cheeky_adaptive_tick(float observed_frame_ms) noexcept;
[[nodiscard]] std::uint32_t cheeky_adaptive_stage() noexcept;
[[nodiscard]] float cheeky_adaptive_observed_ms() noexcept;""")
replace("uevr/settings_fields.inc",
    'CHEEKY_SETTING("NrMotionScaleYMultiplier", nr_motion_scale_y_multiplier)',
    """CHEEKY_SETTING("NrMotionScaleYMultiplier", nr_motion_scale_y_multiplier)
CHEEKY_SETTING("NrAdaptiveEnabled", nr_adaptive_enabled)
CHEEKY_SETTING("NrAdaptiveMode", nr_adaptive_mode)
CHEEKY_SETTING("NrAdaptiveStage2", nr_adaptive_stage2)
CHEEKY_SETTING("NrAdaptiveStage3", nr_adaptive_stage3)
CHEEKY_SETTING("NrAdaptiveStage4", nr_adaptive_stage4)
CHEEKY_SETTING("NrAdaptiveStage5", nr_adaptive_stage5)
CHEEKY_SETTING("NrAdaptiveBudgetMs", nr_adaptive_budget_ms)
CHEEKY_SETTING("NrAdaptiveHeadroomMs", nr_adaptive_headroom_ms)
CHEEKY_SETTING("NrAdaptiveDisableMs", nr_adaptive_disable_ms)
CHEEKY_SETTING("NrAdaptiveResumeMs", nr_adaptive_resume_ms)
CHEEKY_SETTING("NrAdaptiveSmoothingMs", nr_adaptive_smoothing_ms)
CHEEKY_SETTING("NrAdaptiveDecreaseHoldMs", nr_adaptive_decrease_hold_ms)
CHEEKY_SETTING("NrAdaptiveIncreaseHoldMs", nr_adaptive_increase_hold_ms)
CHEEKY_SETTING("NrAdaptiveCooldownMs", nr_adaptive_cooldown_ms)""")

replace("src/settings.cpp",
    "std::mutex settings_mutex;",
    """std::mutex settings_mutex;
Settings adaptive_configuration{};
std::atomic<std::uint32_t> adaptive_active_stage{1};
std::atomic<float> adaptive_last_ms{0.0F};
std::mutex adaptive_mutex;
float adaptive_filtered_ms{};
ULONGLONG adaptive_outside_since{}, adaptive_last_commit{};
bool adaptive_has_sample{};""")
replace("src/settings.cpp",
    "    settings.nr_motion_scale_y_multiplier = load_float(nr_motion_scale_y_bits);\n    return settings;",
    """    settings.nr_motion_scale_y_multiplier = load_float(nr_motion_scale_y_bits);
    settings.nr_adaptive_enabled = adaptive_configuration.nr_adaptive_enabled;
    settings.nr_adaptive_mode = adaptive_configuration.nr_adaptive_mode;
    settings.nr_adaptive_stage2 = adaptive_configuration.nr_adaptive_stage2;
    settings.nr_adaptive_stage3 = adaptive_configuration.nr_adaptive_stage3;
    settings.nr_adaptive_stage4 = adaptive_configuration.nr_adaptive_stage4;
    settings.nr_adaptive_stage5 = adaptive_configuration.nr_adaptive_stage5;
    settings.nr_adaptive_budget_ms = adaptive_configuration.nr_adaptive_budget_ms;
    settings.nr_adaptive_headroom_ms = adaptive_configuration.nr_adaptive_headroom_ms;
    settings.nr_adaptive_disable_ms = adaptive_configuration.nr_adaptive_disable_ms;
    settings.nr_adaptive_resume_ms = adaptive_configuration.nr_adaptive_resume_ms;
    settings.nr_adaptive_smoothing_ms = adaptive_configuration.nr_adaptive_smoothing_ms;
    settings.nr_adaptive_decrease_hold_ms = adaptive_configuration.nr_adaptive_decrease_hold_ms;
    settings.nr_adaptive_increase_hold_ms = adaptive_configuration.nr_adaptive_increase_hold_ms;
    settings.nr_adaptive_cooldown_ms = adaptive_configuration.nr_adaptive_cooldown_ms;
    return settings;""")
replace("src/settings.cpp",
    """Settings current_settings() noexcept {
    auto settings = configured_settings();
    if (!processing_allowed.load(std::memory_order_acquire)) {
        settings.enabled = false;
        settings.nr_enabled = false;
    }
    return settings;
}""",
    """Settings current_settings() noexcept {
    auto settings = configured_settings();
    if (!processing_allowed.load(std::memory_order_acquire)) {
        settings.enabled = false;
        settings.nr_enabled = false;
    }
    if (settings.nr_adaptive_enabled && settings.nr_enabled) {
        const auto stage = settings.nr_adaptive_mode != 0U
            ? std::clamp(settings.nr_adaptive_mode, 1U, 6U)
            : adaptive_active_stage.load(std::memory_order_acquire);
        if (stage == 6U) {
            settings.nr_enabled = false; // stage 6: original selected crop retained
        } else {
            const std::uint32_t percentages[]{
                100U, settings.nr_adaptive_stage2, settings.nr_adaptive_stage3,
                settings.nr_adaptive_stage4, settings.nr_adaptive_stage5};
            const float scale = float(percentages[(std::min)(stage,5U)-1U]) / 100.0F;
            const auto user_width = settings.nr_use_sr_foveation ? settings.width : settings.nr_width;
            const auto user_height = settings.nr_use_sr_foveation ? settings.height : settings.nr_height;
            settings.nr_use_sr_foveation = false; // keep SR dimensions independent
            settings.nr_width = std::clamp(user_width * scale, 0.08F, 1.0F);
            settings.nr_height = std::clamp(user_height * scale, 0.08F, 1.0F);
            settings.nr_working_scale = 1.0F; // r10: never reduce neural resolution
        }
    }
    return settings;
}""")
replace("src/settings.cpp",
    "void set_processing_allowed(bool allowed) noexcept {",
    """std::uint32_t cheeky_adaptive_stage() noexcept {
    const auto s = configured_settings();
    if (!s.nr_adaptive_enabled || !s.nr_enabled) return 1U;
    return s.nr_adaptive_mode
        ? std::clamp(s.nr_adaptive_mode, 1U, 6U)
        : adaptive_active_stage.load(std::memory_order_acquire);
}
float cheeky_adaptive_observed_ms() noexcept {
    return adaptive_last_ms.load(std::memory_order_acquire);
}
void cheeky_adaptive_tick(float observed_frame_ms) noexcept {
    const auto s = configured_settings();
    if (!s.nr_adaptive_enabled || !s.nr_enabled) {
        adaptive_active_stage.store(1, std::memory_order_release);
        return;
    }
    if (s.nr_adaptive_mode != 0) {
        adaptive_active_stage.store(std::clamp(s.nr_adaptive_mode, 1U, 6U), std::memory_order_release);
        return;
    }
    if (!std::isfinite(observed_frame_ms) || observed_frame_ms < 2.0F || observed_frame_ms > 100.0F) return;
    std::lock_guard lock(adaptive_mutex);
    // This is a UEVR present-interval controller. Unlike Skyrim OpenNR's
    // SteamVR GPU sample, present interval is a proxy and is labelled as such.
    const float ms = s.nr_adaptive_smoothing_ms;
    const float alpha = ms < 1.F ? 1.F : 1.F - std::exp(-std::clamp(observed_frame_ms/ms, 0.F, 1.F));
    adaptive_filtered_ms = adaptive_has_sample ? adaptive_filtered_ms +
        alpha*(observed_frame_ms-adaptive_filtered_ms) : observed_frame_ms;
    adaptive_has_sample = true;
    adaptive_last_ms.store(adaptive_filtered_ms, std::memory_order_release);
    const auto now = GetTickCount64();
    const auto stage = adaptive_active_stage.load(std::memory_order_acquire);
    if (now - adaptive_last_commit < (ULONGLONG)s.nr_adaptive_cooldown_ms) return;
    std::uint32_t next=stage;
    float hold{};
    if (stage == 6U) {
        if (adaptive_filtered_ms <= s.nr_adaptive_resume_ms) {
            next=5U; hold=s.nr_adaptive_increase_hold_ms;
        }
    } else if (stage == 5U && adaptive_filtered_ms >= s.nr_adaptive_disable_ms) {
        next=6U; hold=s.nr_adaptive_decrease_hold_ms;
    } else if (adaptive_filtered_ms >= s.nr_adaptive_budget_ms && stage < 5U) {
        next=stage+1U; hold=s.nr_adaptive_decrease_hold_ms;
    } else if (adaptive_filtered_ms <= s.nr_adaptive_budget_ms-s.nr_adaptive_headroom_ms && stage > 1U) {
        next=stage-1U; hold=s.nr_adaptive_increase_hold_ms;
    }
    if (next == stage) { adaptive_outside_since=0; return; }
    if (!adaptive_outside_since) adaptive_outside_since=now;
    if (now-adaptive_outside_since < (ULONGLONG)hold) return;
    adaptive_active_stage.store(next, std::memory_order_release);
    adaptive_last_commit=now;
    adaptive_outside_since=0;
}
void set_processing_allowed(bool allowed) noexcept {""")
replace("src/settings.cpp",
    """    nr_depth_convention.store(
        (std::min)(settings.nr_depth_convention, 2U),
        std::memory_order_release
    );""",
    """    // Stage settings are clamped as one transaction: the controller must
    // never use an unordered crop ladder from partially applied Lua edits.
    adaptive_configuration.nr_adaptive_enabled = settings.nr_adaptive_enabled;
    adaptive_configuration.nr_adaptive_mode = std::min(settings.nr_adaptive_mode, 6U);
    auto clamp_pct=[](unsigned v){ return std::clamp(v/5U*5U,60U,100U); };
    adaptive_configuration.nr_adaptive_stage2 = clamp_pct(settings.nr_adaptive_stage2);
    adaptive_configuration.nr_adaptive_stage3 = std::min(adaptive_configuration.nr_adaptive_stage2,clamp_pct(settings.nr_adaptive_stage3));
    adaptive_configuration.nr_adaptive_stage4 = std::min(adaptive_configuration.nr_adaptive_stage3,clamp_pct(settings.nr_adaptive_stage4));
    adaptive_configuration.nr_adaptive_stage5 = std::min(adaptive_configuration.nr_adaptive_stage4,clamp_pct(settings.nr_adaptive_stage5));
    auto finite=[](float v,float lo,float hi,float def){return std::isfinite(v)?std::clamp(v,lo,hi):def;};
    adaptive_configuration.nr_adaptive_budget_ms=finite(settings.nr_adaptive_budget_ms,10,30,20);
    adaptive_configuration.nr_adaptive_headroom_ms=finite(settings.nr_adaptive_headroom_ms,0.5F,5,1);
    adaptive_configuration.nr_adaptive_disable_ms=finite(settings.nr_adaptive_disable_ms,10,50,24);
    adaptive_configuration.nr_adaptive_resume_ms=std::min(finite(settings.nr_adaptive_resume_ms,1,50,14),
        adaptive_configuration.nr_adaptive_disable_ms-1.F);
    adaptive_configuration.nr_adaptive_smoothing_ms=finite(settings.nr_adaptive_smoothing_ms,0,1000,250);
    adaptive_configuration.nr_adaptive_decrease_hold_ms=finite(settings.nr_adaptive_decrease_hold_ms,0,2500,350);
    adaptive_configuration.nr_adaptive_increase_hold_ms=finite(settings.nr_adaptive_increase_hold_ms,0,5000,1200);
    adaptive_configuration.nr_adaptive_cooldown_ms=finite(settings.nr_adaptive_cooldown_ms,0,5000,1000);
    nr_depth_convention.store(
        (std::min)(settings.nr_depth_convention, 2U),
        std::memory_order_release
    );""")
replace("uevr/runtime.cpp",
    """            if (ms > 0) diagnostic_note_frame_rate(static_cast<float>(1000.0 / ms), enabled);""",
    """            if (ms > 0) {
                diagnostic_note_frame_rate(static_cast<float>(1000.0 / ms), enabled);
                cheeky_adaptive_tick(static_cast<float>(ms));
            }""")
replace("uevr/runtime.cpp",
    """        << ",\\\"processing\\\":" << current_settings().enabled""",
    """        << ",\\\"adaptive\\\":{\\\"stage\\\":" << cheeky_adaptive_stage()
        << ",\\\"present_interval_ms\\\":" << cheeky_adaptive_observed_ms()
        << ",\\\"sample_type\\\":\\\"UEVR present interval (not GPU frametime)\\\"}"
        << ",\\\"processing\\\":" << current_settings().enabled""")
replace("uevr/scripts/cheeky_foveated_dlss.lua",
    """                slider("NR working scale", "NrWorkingScale", 0.1, 1)""",
    """                if imgui.tree_node("OpenNR six-stage adaptive crop") then
                    check("Adaptive crop controller", "NrAdaptiveEnabled")
                    if draft.NrAdaptiveEnabled then
                        combo("Mode", "NrAdaptiveMode", {[0]="Auto", [1]="Force stage 1", [2]="Force stage 2",
                            [3]="Force stage 3", [4]="Force stage 4", [5]="Force stage 5", [6]="Force stage 6 (NR off)"})
                        local a = status.adaptive or {}
                        text(string.format("Active stage: %s | Present interval: %.2f ms",
                            tostring(a.stage or 1), a.present_interval_ms or 0))
                        text("Auto currently follows UEVR PRESENT interval, not true GPU frametime.")
                        combo("Stage 2 relative crop", "NrAdaptiveStage2",
                            {[60]="60%",[65]="65%",[70]="70%",[75]="75%",[80]="80%",[85]="85%",
                            [90]="90%",[95]="95%",[100]="100%"})
                        combo("Stage 3 relative crop", "NrAdaptiveStage3",
                            {[60]="60%",[65]="65%",[70]="70%",[75]="75%",[80]="80%",[85]="85%",
                            [90]="90%",[95]="95%",[100]="100%"})
                        combo("Stage 4 relative crop", "NrAdaptiveStage4",
                            {[60]="60%",[65]="65%",[70]="70%",[75]="75%",[80]="80%",[85]="85%",
                            [90]="90%",[95]="95%",[100]="100%"})
                        combo("Stage 5 relative crop", "NrAdaptiveStage5",
                            {[60]="60%",[65]="65%",[70]="70%",[75]="75%",[80]="80%",[85]="85%",
                            [90]="90%",[95]="95%",[100]="100%"})
                        slider("Budget (ms)", "NrAdaptiveBudgetMs", 10, 30)
                        slider("Recovery headroom (ms)", "NrAdaptiveHeadroomMs", 0.5, 5)
                        slider("Disable NR above (stage 5)", "NrAdaptiveDisableMs", 10, 50)
                        slider("Re-enable NR below (stage 6)", "NrAdaptiveResumeMs", 1, 50)
                        slider("Frametime smoothing ms", "NrAdaptiveSmoothingMs", 0, 1000)
                        slider("Decrease hold ms", "NrAdaptiveDecreaseHoldMs", 0, 2500)
                        slider("Increase hold ms", "NrAdaptiveIncreaseHoldMs", 0, 5000)
                        slider("Cooldown ms", "NrAdaptiveCooldownMs", 0, 5000)
                    end
                    imgui.tree_pop()
                end
                slider("NR working scale", "NrWorkingScale", 0.1, 1)""")
print("Six-stage Cheeky Mono adaptive crop revision applied")
