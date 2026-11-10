#pragma once
// TriView NR-Lite: conservative admission policy for changing NVIDIA Feature 18.
// This is a headroom gate, NOT a promise that NVNGX allocations fit: the driver
// does not expose exact model/history sizes until they are created.
#include "../src/settings.hpp"
#include <cstdint>

namespace cheeky::foveated_dlss {

constexpr std::uint64_t nr_lite_mib = 1024ULL * 1024ULL;

[[nodiscard]] inline std::uint64_t nr_lite_required_headroom(
    const Settings& current, const Settings& requested) noexcept {
    // Other integrations preserve original behavior. This guard is targeted
    // at the two-fovea TriView setup where we know VRAM is constrained.
    if (requested.eye_processing_mode != 3U || !requested.nr_enabled)
        return 0ULL;

    // Enabling NR or switching into TriView mode can instantiate a second eye.
    if (!current.nr_enabled || current.eye_processing_mode != 3U)
        return (requested.nr_foveated ? 1024ULL : 2304ULL) * nr_lite_mib;

    // Expanding NR beyond the prior crop recreates NVIDIA model histories;
    // old ones cannot be freed until all recording and GPU fences retire.
    if (current.nr_foveated && !requested.nr_foveated)
        return 2304ULL * nr_lite_mib;

    // After-SR operates on larger images; switching NR order can reallocate
    // both eye features, even when the region selector was unchanged.
    if (current.nr_processing_order != requested.nr_processing_order)
        return (requested.nr_processing_order == NrProcessingOrder::after_upscaling
            ? 2560ULL : 1536ULL) * nr_lite_mib;

    if (requested.nr_passes > current.nr_passes)
        return 1536ULL * nr_lite_mib;

    const bool growing = requested.nr_working_scale > current.nr_working_scale + 0.0001F ||
        (requested.nr_foveated && current.nr_foveated &&
            (requested.nr_width > current.nr_width + 0.0001F ||
             requested.nr_height > current.nr_height + 0.0001F));
    if (growing)
        return (requested.nr_foveated ? 1024ULL : 2304ULL) * nr_lite_mib;

    // The model's parameters are part of its feature key. An edit can create
    // a new model even if the texture dimensions have not changed.
    const bool rekey = requested.nr_preset != current.nr_preset ||
        requested.nr_style != current.nr_style ||
        requested.nr_intensity != current.nr_intensity ||
        requested.nr_local_tone_strength != current.nr_local_tone_strength ||
        requested.nr_local_structure_strength != current.nr_local_structure_strength ||
        requested.nr_skin_structure_strength != current.nr_skin_structure_strength ||
        requested.nr_automatic_mask != current.nr_automatic_mask ||
        requested.nr_ui_correction != current.nr_ui_correction;
    return rekey ? 768ULL * nr_lite_mib : 0ULL;
}

[[nodiscard]] inline bool nr_lite_has_headroom(
    std::uint64_t required, bool valid, std::uint64_t usage,
    std::uint64_t budget) noexcept {
    if (!required) return true;
    return valid && budget >= usage && budget - usage >= required;
}

} // namespace cheeky::foveated_dlss
