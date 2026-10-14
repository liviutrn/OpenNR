#pragma once
// Retained for the regression counterexample; production color never uses it.
// Temporal crop displacement belongs in history lookup, not current RGB sampling.
#include "DuoViewConfig.hpp"
#include <algorithm>
#include <cmath>
#include <optional>
namespace uevr::duoview {
// Only a previous successfully ACCEPTED DuoView XR composition may be used.
// Missing/gapped/stale frames, a source-size change or a saccade disable
// correction (gaze position itself is always instant).
inline std::optional<UV> compositor_history_shift(
    const FrameConfig& previous, bool previous_gaze_valid,
    const FrameConfig& current, bool current_gaze_valid) {
    if (!current.settings.history_sample_correction ||
        !current.settings.eye_tracked || !previous.settings.eye_tracked ||
        !previous_gaze_valid || !current_gaze_valid ||
        previous.key.generation != current.key.generation ||
        previous.key.frame + 1u != current.key.frame ||
        previous.settings.fovea_view != current.settings.fovea_view ||
        previous.layout.fovea.width != current.layout.fovea.width ||
        previous.layout.fovea.height != current.layout.fovea.height ||
        previous.layout.atlas_width != current.layout.atlas_width ||
        previous.layout.atlas_height != current.layout.atlas_height ||
        previous.layout.crop_width != current.layout.crop_width ||
        previous.layout.crop_height != current.layout.crop_height)
        return {};
    const float strength=current.settings.history_sample_strength;
    if (!std::isfinite(strength) || strength<0.f || strength>1.f) return {};
    // Cheeky sign: current->previous texture coordinate = current coordinate
    // + (currentOrigin-previousOrigin)/currentCropExtent.
    const float dx=(current.layout.u0-previous.layout.u0)/current.layout.crop_width;
    const float dy=(current.layout.v0-previous.layout.v0)/current.layout.crop_height;
    if (!std::isfinite(dx) || !std::isfinite(dy) ||
        std::abs(dx) > .25f || std::abs(dy) > .25f) return {};
    return UV{strength*dx,strength*dy};
}
}
