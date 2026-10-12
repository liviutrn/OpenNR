#pragma once
// Stage 4: gaze-to-Mono-frustum mapping and asynchronous validity policy.
// The caller must first convert the PSVR2 Toolkit combined calibrated ray
// from device/OpenXR coordinates into Joey's shared left-optical Mono basis.
// This module is a renderer-independent testable component, NOT a PSVR2 reader.
#include "DuoViewGeometry.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::duoview {

struct Ray {
    float right{}, up{}, forward{}; // +forward = looking through the Mono plane
};
struct UV {
    float u{.5f}, v{.5f};
};

// Input: eye ray in the *shared calibrated Mono optical basis*.
// Output: normalized full-frustum tangent-plane coordinates (not angles).
inline std::optional<UV> ray_to_uv(Ray gaze, const Tans& full) {
    if (!std::isfinite(gaze.right) || !std::isfinite(gaze.up) ||
        !std::isfinite(gaze.forward) || gaze.forward <= .1f ||
        !std::isfinite(full.left) || !std::isfinite(full.right) ||
        !std::isfinite(full.top) || !std::isfinite(full.bottom) ||
        full.right <= full.left || full.top <= full.bottom)
        return {};
    const float horizontal = gaze.right / gaze.forward;
    const float vertical = gaze.up / gaze.forward;
    if (!std::isfinite(horizontal) || !std::isfinite(vertical)) return {};
    return UV {
        std::clamp((horizontal - full.left) / (full.right - full.left), 0.f, 1.f),
        std::clamp((full.top - vertical) / (full.top - full.bottom), 0.f, 1.f)
    };
}

class GazeCache {
public:
    void invalidate() { sample_.reset(); }
    // Based on the already-tested PSVR2 Toolkit CAPI behavior: a false read
    // often means "no new frame", not "tracking invalid". Reuse a frame for
    // <= 50ms without extra temporal smoothing or spatial dead zones.
    explicit GazeCache(uint64_t max_age_ms = 50) : max_age_ms_{max_age_ms} {}

    UV update(uint64_t now_ms, std::optional<UV> fresh) {
        if (now_ms < last_tick_ms_) {
            sample_.reset();
        }
        last_tick_ms_ = now_ms;
        if (fresh && std::isfinite(fresh->u) && std::isfinite(fresh->v) &&
            fresh->u >= 0.f && fresh->u <= 1.f &&
            fresh->v >= 0.f && fresh->v <= 1.f) {
            sample_ = fresh;
            last_valid_ms_ = now_ms;
        }
        if (sample_ && now_ms >= last_valid_ms_ &&
            now_ms - last_valid_ms_ <= max_age_ms_) {
            return *sample_;
        }
        sample_.reset();
        return {.5f, .5f};
    }

private:
    std::optional<UV> sample_{};
    uint64_t last_valid_ms_{};
    uint64_t last_tick_ms_{};
    uint64_t max_age_ms_{50};
};

} // namespace uevr::duoview
