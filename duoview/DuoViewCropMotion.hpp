#pragma once
#include "DuoViewConfig.hpp"
#include <cmath>
#include <limits>
#include <optional>

namespace uevr::duoview {

struct CropMotion {
    UV current_to_previous_uv{};
    double current_to_previous_pixels_x{};
    double current_to_previous_pixels_y{};
};

// The moving projection makes this crop contribution part of Unreal's
// current-to-previous view transform. This value is diagnostic/test math only.
inline std::optional<CropMotion> expected_crop_motion(
    const FrameConfig& previous, const FrameConfig& current) {
    const auto& old = previous.layout;
    const auto& now = current.layout;
    if (!previous.settings.eye_tracked || !current.settings.eye_tracked ||
        previous.key.generation != current.key.generation ||
        previous.key.frame == (std::numeric_limits<uint32_t>::max)() ||
        previous.key.frame + 1u != current.key.frame ||
        previous.settings.fovea_view != current.settings.fovea_view ||
        old.atlas_width != now.atlas_width || old.atlas_height != now.atlas_height ||
        old.fovea.width != now.fovea.width || old.fovea.height != now.fovea.height ||
        old.crop_width != now.crop_width || old.crop_height != now.crop_height ||
        !now.crop_width || !now.crop_height)
        return {};

    const double du = (double(now.u0) - old.u0) / now.crop_width;
    const double dv = (double(now.v0) - old.v0) / now.crop_height;
    if (!std::isfinite(du) || !std::isfinite(dv)) return {};
    return CropMotion{
        .current_to_previous_uv = {static_cast<float>(du), static_cast<float>(dv)},
        .current_to_previous_pixels_x = du * now.fovea.width,
        .current_to_previous_pixels_y = dv * now.fovea.height};
}

} // namespace uevr::duoview
