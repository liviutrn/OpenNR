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
    bool direct_xr_output{};
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
// Resolve persisted UI controls field by field. Unlike the strict ConfigLatch,
// one bad slider must not veto eye tracking, shading, position, or other sliders.
// Retain each rejected *field* so the UI can explain it; never silently resize
// Native sources or reinterpret a failed input as a successful renderer change.
enum UiReject : uint32_t {
    reject_width=1u<<0, reject_height=1u<<1, reject_periphery=1u<<2,
    reject_density=1u<<3, reject_feather=1u<<4, reject_fovea_view=1u<<5,
    reject_diagnostic=1u<<6, reject_guard=1u<<7, reject_quant=1u<<8,
    reject_hold=1u<<9, reject_reacquire=1u<<10, reject_offset_u=1u<<11,
    reject_offset_v=1u<<12, reject_micro=1u<<13,
    reject_breakout=1u<<14, reject_still=1u<<15, reject_relock=1u<<16
};
struct UiReconciled {
    Settings settings{};
    uint32_t rejected{};
};
inline UiReconciled reconcile_ui_settings(const Settings& requested,
                                         const Settings& current) {
    UiReconciled result{current, 0};
    auto& out=result.settings;
    const auto valid=[](float x,float lo,float hi) {
        return std::isfinite(x) && x>=lo && x<=hi;
    };
    const auto valid_quality=[](const Settings& x) {
        // Both UE Native source textures are at full output-eye dimensions.
        // A cropped view must fit the existing source, not just the atlas.
        return x.crop_width*x.foveal_density<=1.f &&
               x.crop_height*x.foveal_density<=1.f &&
               make_layout(1024,1024,x.crop_width,x.crop_height,
                           x.peripheral_scale,x.foveal_density).has_value();
    };
    // When multiple quality sliders change together, honor the full valid tuple
    // first (such as reducing density while increasing crop width).
    if (valid_quality(requested)) {
        out.crop_width=requested.crop_width;
        out.crop_height=requested.crop_height;
        out.foveal_density=requested.foveal_density;
        out.peripheral_scale=requested.peripheral_scale;
    } else {
        // Otherwise isolate invalid fields. A failed density must not prevent
        // a valid width, height, peripheral or gaze/visual setting from applying.
        const auto quality_field=[&](float value, float lo, float hi,
                                     uint32_t mask, float Settings::* field) {
            Settings attempt=out;
            attempt.*field=value;
            if (valid(value,lo,hi) && valid_quality(attempt)) {
                out.*field=value;
            } else {
                result.rejected|=mask;
            }
        };
        quality_field(requested.crop_width,.05f,1.f,reject_width,&Settings::crop_width);
        quality_field(requested.crop_height,.05f,1.f,reject_height,&Settings::crop_height);
        quality_field(requested.foveal_density,.25f,4.f,reject_density,&Settings::foveal_density);
        quality_field(requested.peripheral_scale,.05f,.50f,reject_periphery,&Settings::peripheral_scale);
    }
    // Boolean controls are inherently valid and must always apply.
    out.debug_border=requested.debug_border;
    out.eye_tracked=requested.eye_tracked;
    out.gpu_timing=requested.gpu_timing;
    out.direct_xr_output=requested.direct_xr_output;
    out.stabilize_crop=requested.stabilize_crop;
    out.independent_shading=requested.independent_shading;
    out.native_fix_same_pass=requested.native_fix_same_pass;
    const auto scalar=[&](float value,float lo,float hi,uint32_t mask,
                          float Settings::* field) {
        if (valid(value,lo,hi)) out.*field=value;
        else result.rejected|=mask;
    };
    const auto integer=[&](int32_t value,int32_t lo,int32_t hi,uint32_t mask,
                           int32_t Settings::* field) {
        if (value>=lo&&value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    const auto unsigned_int=[&](uint32_t value,uint32_t lo,uint32_t hi,
                                uint32_t mask,uint32_t Settings::* field) {
        if (value>=lo&&value<=hi) out.*field=value;
        else result.rejected|=mask;
    };
    scalar(requested.feather_fraction,0.f,.45f,reject_feather,&Settings::feather_fraction);
    scalar(requested.guard_fraction,0.f,.05f,reject_guard,&Settings::guard_fraction);
    scalar(requested.gaze_offset_u,-.25f,.25f,reject_offset_u,&Settings::gaze_offset_u);
    scalar(requested.gaze_offset_v,-.25f,.25f,reject_offset_v,&Settings::gaze_offset_v);
    scalar(requested.gaze_micro_gain,0.f,1.f,reject_micro,&Settings::gaze_micro_gain);
    unsigned_int(requested.fovea_view,0u,1u,reject_fovea_view,&Settings::fovea_view);
    unsigned_int(requested.diagnostic_view,0u,2u,reject_diagnostic,&Settings::diagnostic_view);
    unsigned_int(requested.gaze_quant_pixels,0u,16u,reject_quant,&Settings::gaze_quant_pixels);
    unsigned_int(requested.gaze_relock_samples,1u,10u,reject_relock,&Settings::gaze_relock_samples);
    integer(requested.gaze_hold_ms,50,2000,reject_hold,&Settings::gaze_hold_ms);
    integer(requested.gaze_reacquire_samples,1,4,reject_reacquire,&Settings::gaze_reacquire_samples);
    // Breakout/stillness form one inequality. Accept the pair atomically when
    // possible; when not, keep independent controls live and mark the conflict.
    const bool good_breakout=valid(requested.gaze_breakout_radius,.005f,.25f);
    const bool good_still=valid(requested.gaze_still_radius,0.f,.05f);
    if (good_breakout && good_still &&
        requested.gaze_still_radius<requested.gaze_breakout_radius) {
        out.gaze_breakout_radius=requested.gaze_breakout_radius;
        out.gaze_still_radius=requested.gaze_still_radius;
    } else {
        if (good_breakout &&
            out.gaze_still_radius<requested.gaze_breakout_radius) {
            out.gaze_breakout_radius=requested.gaze_breakout_radius;
        } else result.rejected|=reject_breakout;
        if (good_still &&
            requested.gaze_still_radius<out.gaze_breakout_radius) {
            out.gaze_still_radius=requested.gaze_still_radius;
        } else result.rejected|=reject_still;
    }
    return result;
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
