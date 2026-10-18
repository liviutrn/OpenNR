#pragma once
// Stage 8 — latch all DuoView settings/gaze exactly once per render frame.
// This header deliberately has no UEVR/UESDK/D3D/OpenXR dependency.
// Changes from ImGui/config reload cannot split the two UE views or the
// subsequent shader blend into different crop positions or densities.
#include "DuoViewFrame.hpp"
#include "DuoViewGaze.hpp"
#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::duoview {

struct Settings {
    float crop_width{.50f}, crop_height{.50f};
    float peripheral_scale{.20f};
    float foveal_density{1.f};
    float feather_fraction{.08f};
    bool debug_border{};
    bool eye_tracked{true};
    uint32_t fovea_view{};
    uint32_t diagnostic_view{}; // 0 composite, 1 periphery, 2 fovea
    bool gpu_timing{};
    bool stabilize_crop{};
    float guard_fraction{.05f};
    bool independent_shading{};
    // Keep DuoView's proven Native two-target capture in both modes.
    // OFF retains the stock UE SECONDARY shading pass instead of relabeling PRIMARY.
    bool native_fix_same_pass{true};
    uint32_t gaze_quant_pixels{2}; // 0 disables snapping; other values step in fovea pixels.
    int32_t gaze_hold_ms{350};
    int32_t gaze_reacquire_samples{2};
    float gaze_offset_u{}, gaze_offset_v{};
    // Nonlinear gaze response: hold or slowly follow small motion, but follow
    // genuine saccades 1:1. All distances are fractions of the full view.
    float gaze_micro_gain{0.f};        // 0=locked, 1=full follow below breakout
    float gaze_breakout_radius{.035f}; // when farther from locked crop, go 1:1
    float gaze_still_radius{.008f};    // per-sample motion treated as stationary
    uint32_t gaze_relock_samples{3};  // quiet samples before leaving fast tracking
};
// Unlike the immutable GPU source dimensions, menu sliders may request
// incompatible combinations while the user drags them. Prefer the explicitly
// chosen fovea WIDTH/HEIGHT and reduce density to fit each Native capture
// target. This policy is intentionally separate from ConfigLatch validation:
// external code cannot bypass layout validation by submitting bad settings.
struct NativeQualityAdjustment {
    bool changed{};
    bool density_capped{};
    bool invalid_input{};
};
inline NativeQualityAdjustment reconcile_native_quality(Settings& desired,
                                                         const Settings& previous) {
    NativeQualityAdjustment out{};
    const auto within=[](float x, float lo, float hi) {
        return std::isfinite(x) && x >= lo && x <= hi;
    };
    if (!within(desired.crop_width,.05f,1.f)) {
        desired.crop_width=previous.crop_width; out.changed=out.invalid_input=true;
    }
    if (!within(desired.crop_height,.05f,1.f)) {
        desired.crop_height=previous.crop_height; out.changed=out.invalid_input=true;
    }
    if (!within(desired.peripheral_scale,.05f,.5f)) {
        desired.peripheral_scale=previous.peripheral_scale; out.changed=out.invalid_input=true;
    }
    if (!within(desired.foveal_density,.25f,4.f)) {
        desired.foveal_density=previous.foveal_density; out.changed=out.invalid_input=true;
    }
    // Floating-point edge cases must not accidentally select a source rectangle
    // one pixel wider than the actual underlying Native render target.
    const float max_extent=(std::max)(desired.crop_width,desired.crop_height);
    const float capacity=std::nextafter(1.f/max_extent,0.f);
    if (desired.foveal_density > capacity) {
        desired.foveal_density=capacity;
        out.changed=out.density_capped=true;
    }
    if (!make_layout(1024,1024,desired.crop_width,desired.crop_height,
                     desired.peripheral_scale,desired.foveal_density)) {
        // Never commit unusable geometry. Do not roll back other settings.
        desired.crop_width=previous.crop_width;
        desired.crop_height=previous.crop_height;
        desired.peripheral_scale=previous.peripheral_scale;
        desired.foveal_density=previous.foveal_density;
        out.changed=out.invalid_input=true;
    }
    return out;
}

struct FrameConfig {
    FrameKey key{};
    Layout layout{};
    UV gaze{};
    Settings settings{};
    uint64_t settings_revision{};
};
class ConfigLatch {
public:
    bool set_settings(Settings proposed) {
        std::scoped_lock lock{mutex_};
        if (!std::isfinite(proposed.feather_fraction) ||
            proposed.feather_fraction < 0.f || proposed.feather_fraction > .45f ||
            proposed.fovea_view > 1 || proposed.diagnostic_view > 2 ||
            !std::isfinite(proposed.guard_fraction) || proposed.guard_fraction<0.f || proposed.guard_fraction>.05f ||
            proposed.gaze_quant_pixels>16 || proposed.gaze_hold_ms<50 || proposed.gaze_hold_ms>2000 ||
            proposed.gaze_reacquire_samples<1 || proposed.gaze_reacquire_samples>4 ||
            !std::isfinite(proposed.gaze_offset_u) || !std::isfinite(proposed.gaze_offset_v) ||
            proposed.gaze_offset_u<-.25f || proposed.gaze_offset_u>.25f ||
            proposed.gaze_offset_v<-.25f || proposed.gaze_offset_v>.25f ||
            !std::isfinite(proposed.gaze_micro_gain) || proposed.gaze_micro_gain<0.f ||
            proposed.gaze_micro_gain>1.f ||
            !std::isfinite(proposed.gaze_breakout_radius) || proposed.gaze_breakout_radius<.005f ||
            proposed.gaze_breakout_radius>.25f ||
            !std::isfinite(proposed.gaze_still_radius) || proposed.gaze_still_radius<0.f ||
            proposed.gaze_still_radius>.05f ||
            proposed.gaze_still_radius>=proposed.gaze_breakout_radius ||
            proposed.gaze_relock_samples<1 || proposed.gaze_relock_samples>10)
            return false;
        // Validate without trusting in-game UI, config files or Lua requests.
        if (!make_layout(1024,1024,proposed.crop_width,proposed.crop_height,
                         proposed.peripheral_scale,proposed.foveal_density)) return false;
        settings_ = proposed;
        ++revision_;
        return true;
    }

    Settings current_settings() const {
        std::scoped_lock lock{mutex_};
        return settings_;
    }

    // Same frame always gets *exactly* the same immutable parameters.
    // A different generation retires the old snapshot. Stale/duplicate
    // generation-frame keys are rejected rather than reusing a prior frame.
    std::optional<FrameConfig> for_frame(
        FrameKey key, uint32_t output_width, uint32_t output_height, UV gaze)
    {
        std::scoped_lock lock{mutex_};
        if (!key.generation || !key.frame) return {};
        if (cached_ && cached_->key == key) return cached_;
        if (key.generation < last_key_.generation ||
            (key.generation == last_key_.generation && key.frame <= last_key_.frame)) return {};
        if (!std::isfinite(gaze.u) || !std::isfinite(gaze.v) ||
            gaze.u < 0.f || gaze.u > 1.f || gaze.v < 0.f || gaze.v > 1.f) return {};
        auto layout=make_layout(output_width,output_height,
                                settings_.crop_width,settings_.crop_height,
                                settings_.peripheral_scale,settings_.foveal_density,
                                gaze.u,gaze.v);
        if (!layout || !layout_valid(*layout)) return {};
        FrameConfig next{key,*layout,gaze,settings_,revision_};
        cached_=next;
        last_key_=key;
        return next;
    }

    // On device reset / runtime recreation, caller increments generation.
    void retire() {
        std::scoped_lock lock{mutex_};
        cached_.reset();
    }
private:
    mutable std::mutex mutex_{};
    Settings settings_{};
    uint64_t revision_{1};
    FrameKey last_key_{};
    std::optional<FrameConfig> cached_{};
};
} // namespace uevr::duoview
