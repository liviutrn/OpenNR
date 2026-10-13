#pragma once
// Shared, production-used admission decisions. Keep this header free of
// Unreal/Windows/D3D dependencies so CI exercises the same conditions as
// Plugin.cpp rather than testing an unused parallel state machine.
namespace duoview_joey {
struct LiveFrameSafety {
    static constexpr bool may_crop(bool compatible, bool armed, bool faulted,
                                   bool optics_available, bool slot_available) noexcept {
        return compatible && armed && !faulted && optics_available && slot_available;
    }
    static constexpr bool suppress_scene(bool scene_identified, bool copy_failed,
                                         bool verified_image) noexcept {
        return scene_identified && copy_failed && !verified_image;
    }
    static constexpr bool accept_image(bool scene_identified, bool copy_verified,
                                       bool xr_success, bool same_generation) noexcept {
        return scene_identified && copy_verified && xr_success && same_generation;
    }
    static constexpr bool arm_next(bool accepted_image, bool faulted) noexcept {
        return accepted_image && !faulted;
    }
};
}
