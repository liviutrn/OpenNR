#pragma once
// v45: gaze-only previous/current source-local mapping of stationary world rays.
// This is NOT a write to Unreal's hidden velocity/TSR history, nor an RGB shift.
#include "DuoViewConfig.hpp"
#include <cmath>
#include <optional>
namespace uevr::duoview {
struct GazePixelMotion { double x{},y{}; };
inline std::optional<UV> source_local(const FrameConfig& frame, UV full) {
    if(!std::isfinite(full.u)||!std::isfinite(full.v)) return {};
    if(frame.steering.active) return steering_local(frame.steering,full);
    const auto& l=frame.layout;
    if(!(l.crop_width>0.f&&l.crop_height>0.f)) return {};
    return UV{(full.u-l.u0)/l.crop_width,(full.v-l.v0)/l.crop_height};
}
inline std::optional<GazePixelMotion> gaze_only_pixel_motion(
    const FrameConfig& previous,const FrameConfig& current,UV stationary_screen_uv) {
    if(previous.key.generation!=current.key.generation ||
       previous.key.frame+1u!=current.key.frame ||
       previous.settings.fovea_view!=current.settings.fovea_view ||
       previous.layout.fovea.width!=current.layout.fovea.width ||
       previous.layout.fovea.height!=current.layout.fovea.height ||
       previous.layout.crop_width!=current.layout.crop_width ||
       previous.layout.crop_height!=current.layout.crop_height) return {};
    const auto old=source_local(previous,stationary_screen_uv);
    const auto now=source_local(current,stationary_screen_uv);
    if(!old||!now||!std::isfinite(old->u)||!std::isfinite(old->v)||
       !std::isfinite(now->u)||!std::isfinite(now->v)) return {};
    const double dx=(static_cast<double>(old->u)-now->u)*current.layout.fovea.width;
    const double dy=(static_cast<double>(old->v)-now->v)*current.layout.fovea.height;
    if(!std::isfinite(dx)||!std::isfinite(dy)) return {};
    return GazePixelMotion{dx,dy};
}
} // namespace uevr::duoview
