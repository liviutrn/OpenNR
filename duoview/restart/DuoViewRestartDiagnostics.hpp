#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cstddef>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::duoview_restart {

// These are observations at the producer/copy boundary, not requested UI state.
enum class EffectivePath : uint8_t { unknown, mono_copy, stable_source_mask, identical_two_views };
enum class FallbackReason : uint8_t {
    none,
    mode_not_mono,
    diagnostic_disabled,
    unsupported_device_or_queue,
    invalid_extent_or_format,
    shader_resource_denied,
    descriptor_slot_limit,
    pipeline_unavailable,
    warmup_frame,
    invalid_diagnostic_configuration,
    submission_not_accepted,
    source_frame_unavailable,
    source_or_destination_state_unavailable,
    independent_view_state_unproven,
};

struct FrameObservation {
    uint64_t producer_frame{};
    uint64_t projection_frame{};
    uint64_t mask_frame{};
    int32_t requested_method{-1};
    int32_t effective_method{-1};
    uint8_t requested_control_mode{};
    bool stable_mask_requested{};
    EffectivePath observed_path{EffectivePath::unknown};
    FallbackReason fallback{FallbackReason::none};
    bool control_command_recorded{};
    bool mono_copy_command_recorded{};
    bool copy_submission_accepted{};
    bool projection_frame_observed{};
    uint32_t source_width{};
    uint32_t source_height{};
    uint32_t destination_width{};
    uint32_t destination_height{};
};

// Single-producer/single-consumer fixed storage. The render thread never locks,
// allocates, or writes files. When full, the newest record is dropped.
template <std::size_t Capacity>
class ObservationRing {
    static_assert(Capacity >= 2);
public:
    bool try_push(const FrameObservation& value) noexcept {
        const auto write = m_write.load(std::memory_order_relaxed);
        const auto next = (write + 1) % Capacity;
        if (next == m_read.load(std::memory_order_acquire)) {
            m_dropped.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        m_records[write] = value;
        m_write.store(next, std::memory_order_release);
        return true;
    }

    bool try_pop(FrameObservation& value) noexcept {
        const auto read = m_read.load(std::memory_order_relaxed);
        if (read == m_write.load(std::memory_order_acquire)) { return false; }
        value = m_records[read];
        m_read.store((read + 1) % Capacity, std::memory_order_release);
        return true;
    }

    uint64_t dropped() const noexcept { return m_dropped.load(std::memory_order_relaxed); }

private:
    std::array<FrameObservation, Capacity> m_records{};
    std::atomic<std::size_t> m_write{};
    std::atomic<std::size_t> m_read{};
    std::atomic<uint64_t> m_dropped{};
};

enum class ReplayPattern : uint8_t { fixed, step, ramp, alternating };

struct MaskSample {
    float center_u{0.5f};
    float center_v{0.5f};
    float radius_u{0.18f};
    float radius_v{0.18f};
    float feather{0.025f};
};

inline std::optional<MaskSample> replay_mask(
    ReplayPattern pattern, uint64_t frame, uint32_t period_frames,
    float radius_u = 0.18f, float radius_v = 0.18f, float feather = 0.025f) noexcept {
    if (period_frames == 0 || !std::isfinite(radius_u) || !std::isfinite(radius_v) ||
        !std::isfinite(feather) || radius_u <= 0.f || radius_v <= 0.f ||
        feather < 0.f || feather >= 0.5f || radius_u > 0.5f || radius_v > 0.5f) { return {}; }

    float u = 0.5f, v = 0.5f;
    switch (pattern) {
    case ReplayPattern::fixed:
        break;
    case ReplayPattern::step:
        u = ((frame / period_frames) & 1u) == 0 ? 0.32f : 0.68f;
        break;
    case ReplayPattern::ramp: {
        const auto phase = static_cast<float>(frame % (2ull * period_frames)) / period_frames;
        const auto t = phase <= 1.f ? phase : 2.f - phase;
        u = 0.25f + 0.5f * t;
        break;
    }
    case ReplayPattern::alternating: {
        constexpr std::array<std::array<float, 2>, 4> points{{
            {{0.32f, 0.32f}}, {{0.68f, 0.32f}}, {{0.68f, 0.68f}}, {{0.32f, 0.68f}},
        }};
        const auto point = points[(frame / period_frames) & 3u];
        u = point[0]; v = point[1];
        break;
    }
    default:
        return {};
    }
    return MaskSample{u, v, radius_u, radius_v, feather};
}

struct SourceMapping {
    float u{};
    float v{};
};

// Maps a per-eye normalized output coordinate into the valid left-eye region
// of the double-wide Mono source. Half-texel clamping prevents bilinear taps
// from crossing into the unused right half.
inline std::optional<SourceMapping> left_eye_source_uv(
    uint32_t source_width, uint32_t source_height, float eye_u, float eye_v) noexcept {
    if (source_width < 2 || (source_width & 1u) != 0 || source_height == 0 ||
        !std::isfinite(eye_u) || !std::isfinite(eye_v) ||
        eye_u < 0.f || eye_u > 1.f || eye_v < 0.f || eye_v > 1.f) { return {}; }
    const auto eye_width = source_width / 2;
    const auto min_u = 0.5f / static_cast<float>(source_width);
    const auto max_u = (static_cast<float>(eye_width) - 0.5f) / static_cast<float>(source_width);
    const auto min_v = 0.5f / static_cast<float>(source_height);
    const auto max_v = (static_cast<float>(source_height) - 0.5f) / static_cast<float>(source_height);
    return SourceMapping{
        (std::max)(min_u, (std::min)(max_u, eye_u * 0.5f)),
        (std::max)(min_v, (std::min)(max_v, eye_v))};
}

// This reports only the OpenXR copy() boundary. It does not assert that the
// later xrEndFrame call or headset presentation accepted the image.
inline EffectivePath copy_accepted_path(bool copy_submission_accepted, bool mask_command_recorded,
    bool mono_copy_recorded) noexcept {
    if (!copy_submission_accepted) { return EffectivePath::unknown; }
    if (mask_command_recorded) { return EffectivePath::stable_source_mask; }
    return mono_copy_recorded ? EffectivePath::mono_copy : EffectivePath::unknown;
}

} // namespace uevr::duoview_restart
