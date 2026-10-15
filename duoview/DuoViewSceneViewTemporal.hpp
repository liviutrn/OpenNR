#pragma once
// v46 Unreal-owned temporal bridge.
//
// The crop is not corrected in the final color/compositor path.  For a
// validated UE5.6 FSceneView, this writes the full current-clip -> previous-
// clip transform to the public engine field ClipToPrevClipOverride.  The
// transform is built from the exact current and previous source projections
// and view transforms latched by DuoViewState.
#include "DuoViewState.hpp"
#include "DuoViewTemporalMath.hpp"
#include "DuoViewUE56Layout.hpp"
#include <sdk/FSceneView.hpp>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>

namespace uevr::duoview::ue56 {

using MemoryProbe = bool (*)(uintptr_t, size_t);

inline bool address_range(uintptr_t base, size_t offset, size_t size, uintptr_t& out) {
    if (base > std::numeric_limits<uintptr_t>::max() - offset) return false;
    out = base + offset;
    return out <= std::numeric_limits<uintptr_t>::max() - size;
}

inline bool readable(uintptr_t address, size_t size, MemoryProbe probe) {
    return probe != nullptr && address != 0 && probe(address, size);
}

inline bool read_bytes(uintptr_t address, void* destination, size_t size, MemoryProbe probe) {
    if (!readable(address, size, probe)) return false;
    std::memcpy(destination, reinterpret_cast<const void*>(address), size);
    return true;
}

inline bool finite_raw(const temporal::RawMatrix4d& matrix) {
    for (const double value : matrix) if (!std::isfinite(value)) return false;
    return true;
}

inline bool close_enough(double actual, double expected) {
    const double scale = (std::max)(1.0, (std::max)(std::abs(actual), std::abs(expected)));
    return std::abs(actual - expected) <= 2.0e-7 * scale;
}

inline bool same_matrix(const temporal::RawMatrix4d& actual,
                        const temporal::RawMatrix4d& expected) {
    for (size_t i = 0; i < actual.size(); ++i)
        if (!close_enough(actual[i], expected[i])) return false;
    return true;
}

inline bool same_vector(const std::array<double, 3>& actual,
                        const std::array<double, 3>& expected) {
    for (size_t i = 0; i < actual.size(); ++i)
        if (!close_enough(actual[i], expected[i])) return false;
    return true;
}

inline temporal::ViewInput temporal_input(const ViewFrame& frame, unsigned view) {
    temporal::ViewInput result{};
    result.projection=frame.projection;
    result.layout=frame.config.layout;
    result.fovea_view=frame.config.settings.fovea_view;
    result.valid=view<2 && frame.view_transforms[view].valid;
    if (result.valid) {
        result.origin=frame.view_transforms[view].origin;
        result.view_rotation=frame.view_transforms[view].rotation;
    }
    return result;
}

inline bool fail(const char** failure_reason, const char* reason) {
    if (failure_reason != nullptr) *failure_reason=reason;
    return false;
}

// The only runtime writer in v46. Every pointer, field value and copied
// constructor input is checked before ClipToPrevClipOverride is touched.
inline bool apply_clip_to_prev_clip_override(
    sdk::FSceneView* view,
    sdk::FSceneViewFamily* expected_family,
    uintptr_t expected_state,
    const TemporalContract& contract,
    const temporal::RawMatrix4d& override_raw,
    MemoryProbe readable_probe,
    MemoryProbe writable_probe,
    const char** failure_reason = nullptr) {
    if (failure_reason != nullptr) *failure_reason=nullptr;
    if (view == nullptr || expected_family == nullptr || expected_state == 0 ||
        contract.view > 1 || !finite_raw(override_raw))
        return fail(failure_reason,"invalid temporal bridge inputs");

    const uintptr_t view_address=reinterpret_cast<uintptr_t>(view);
    if (!readable(view_address,sizeof(uintptr_t),readable_probe))
        return fail(failure_reason,"SceneView pointer is not readable");

    // UESDK's family discovery must independently prove that UE5.6 still has
    // the expected post-vtable Family slot. This is not a guessed offset.
    const auto family_offset=view->get_view_family_offset(expected_family);
    if (!family_offset || *family_offset != layout::scene_view_family_offset ||
        !view->has_view_family(expected_family))
        return fail(failure_reason,"SceneView Family backlink is not the UE5.6 contract");

    uintptr_t address{};
    uintptr_t stored_family{};
    if (!address_range(view_address,layout::scene_view_family_offset,sizeof(stored_family),address) ||
        !read_bytes(address,&stored_family,sizeof(stored_family),readable_probe) ||
        stored_family!=reinterpret_cast<uintptr_t>(expected_family))
        return fail(failure_reason,"SceneView Family slot changed");
    uintptr_t stored_state{};
    if (!address_range(view_address,layout::scene_view_state_offset,sizeof(stored_state),address) ||
        !read_bytes(address,&stored_state,sizeof(stored_state),readable_probe) ||
        stored_state!=expected_state)
        return fail(failure_reason,"SceneView State identity changed");

    uintptr_t options_address{};
    if (!address_range(view_address,layout::scene_view_init_options_offset,
                       sizeof(layout::InitOptions),options_address) ||
        !readable(options_address,sizeof(layout::InitOptions),readable_probe))
        return fail(failure_reason,"SceneView InitOptions copy is not readable");

    uintptr_t field_address{};
    uintptr_t copied_family{};
    if (!address_range(options_address,layout::init_options_family_offset,
                       sizeof(copied_family),field_address) ||
        !read_bytes(field_address,&copied_family,sizeof(copied_family),readable_probe) ||
        copied_family!=reinterpret_cast<uintptr_t>(expected_family))
        return fail(failure_reason,"copied InitOptions Family does not match");
    uintptr_t copied_state{};
    if (!address_range(options_address,layout::init_options_state_offset,
                       sizeof(copied_state),field_address) ||
        !read_bytes(field_address,&copied_state,sizeof(copied_state),readable_probe) ||
        copied_state!=expected_state)
        return fail(failure_reason,"copied InitOptions State does not match");

    const unsigned view_index=contract.view;
    const auto current_input=temporal_input(contract.current,view_index);
    const auto expected_projection=temporal::store_raw(
        temporal::projection_for_view(current_input,view_index));
    temporal::RawMatrix4d copied_projection{};
    if (!address_range(options_address,layout::init_options_projection_offset,
                       sizeof(copied_projection),field_address) ||
        !read_bytes(field_address,copied_projection.data(),sizeof(copied_projection),readable_probe) ||
        !same_matrix(copied_projection,expected_projection))
        return fail(failure_reason,"copied InitOptions projection is not the frozen crop");

    std::array<double,3> copied_origin{};
    if (!address_range(options_address,layout::init_options_view_origin_offset,
                       sizeof(copied_origin),field_address) ||
        !read_bytes(field_address,copied_origin.data(),sizeof(copied_origin),readable_probe) ||
        !same_vector(copied_origin,current_input.origin))
        return fail(failure_reason,"copied InitOptions origin is not the source transform");
    temporal::RawMatrix4d copied_rotation{};
    if (!address_range(options_address,layout::init_options_view_rotation_offset,
                       sizeof(copied_rotation),field_address) ||
        !read_bytes(field_address,copied_rotation.data(),sizeof(copied_rotation),readable_probe) ||
        !same_matrix(copied_rotation,current_input.view_rotation))
        return fail(failure_reason,"copied InitOptions rotation is not the source transform");

    const auto& wanted=view_index==contract.current.config.settings.fovea_view
        ? contract.current.config.layout.fovea : contract.current.config.layout.periphery;
    const std::array<int32_t,4> expected_rect{
        static_cast<int32_t>(wanted.x), static_cast<int32_t>(wanted.y),
        static_cast<int32_t>(wanted.x+wanted.width),
        static_cast<int32_t>(wanted.y+wanted.height)};
    std::array<int32_t,4> copied_rect{};
    if (!address_range(options_address,layout::init_options_view_rect_offset,
                       sizeof(copied_rect),field_address) ||
        !read_bytes(field_address,copied_rect.data(),sizeof(copied_rect),readable_probe) ||
        copied_rect!=expected_rect)
        return fail(failure_reason,"copied InitOptions rect is not the source rect");

    uintptr_t clip_address{};
    if (!address_range(view_address,layout::clip_to_prev_clip_override_offset,
                       sizeof(layout::OptionalMatrix),clip_address) ||
        !readable(clip_address,sizeof(layout::OptionalMatrix),readable_probe) ||
        !writable_probe || !writable_probe(clip_address,sizeof(layout::OptionalMatrix)))
        return fail(failure_reason,"ClipToPrevClipOverride is not safely writable");

    uint8_t already_set{};
    if (!address_range(clip_address,sizeof(layout::Matrix),sizeof(already_set),field_address) ||
        !read_bytes(field_address,&already_set,sizeof(already_set),readable_probe))
        return fail(failure_reason,"ClipToPrevClipOverride optional state is unreadable");
    if (already_set != 0)
        return fail(failure_reason,"ClipToPrevClipOverride was already populated");

    std::memcpy(reinterpret_cast<void*>(clip_address),override_raw.data(),sizeof(override_raw));
    const uint8_t set=1;
    std::memcpy(reinterpret_cast<void*>(field_address),&set,sizeof(set));

    temporal::RawMatrix4d written{};
    uint8_t written_state{};
    if (!read_bytes(clip_address,written.data(),sizeof(written),readable_probe) ||
        !address_range(clip_address,sizeof(layout::Matrix),sizeof(written_state),field_address) ||
        !read_bytes(field_address,&written_state,sizeof(written_state),readable_probe) ||
        written_state != 1 || !same_matrix(written,override_raw))
        return fail(failure_reason,"ClipToPrevClipOverride readback failed");
    return true;
}

} // namespace uevr::duoview::ue56
