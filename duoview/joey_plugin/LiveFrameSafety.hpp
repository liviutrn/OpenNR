#pragma once
// Shared, production-used admission decisions. Keep this header free of
// Unreal/Windows/D3D dependencies so CI exercises the same conditions as
// Plugin.cpp rather than testing an unused parallel state machine.
namespace duoview_joey {
struct LiveFrameSafety {
    // If no modified UE viewport has been issued in this renderer generation,
    // a missing producer packet can only correspond to the original native
    // renderer. Do not mistake this normal cadence gap for an atlas frame.
    // Once any crop was issued, unmatched source provenance is unknown: hold
    // a verified image instead of forwarding a potentially uncomposited atlas.
    static constexpr bool native_copy(bool producer_present, bool producer_modified,
                                       bool any_modified_draw_issued) noexcept {
        return (producer_present && !producer_modified) ||
               (!producer_present && !any_modified_draw_issued);
    }
    static constexpr bool hold_requires_quiesce(bool producer_present,
                                                 bool producer_modified) noexcept {
        // An incomplete known-cropped producer is an actual transaction error.
        // A missing packet alone is normal in Joey's multi-call frame cadence.
        return producer_present && producer_modified;
    }
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
