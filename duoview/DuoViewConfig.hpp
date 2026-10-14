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
};
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
            proposed.fovea_view > 1 || proposed.diagnostic_view > 2)
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
