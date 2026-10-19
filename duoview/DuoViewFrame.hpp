#pragma once
// Stage 5 — per-frame DuoView coordination. No UE/D3D headers.
// New compositions require a complete pair with matching gaze/pose and method
// generation. Submit continuity may briefly reuse an unchanged released image
// with its original pose; it never recomposes stale source textures.
//
// Backend integration contract:
//  (1) begin() once per game-render frame with the *same* immutable layout,
//      gaze and pose token used by both Unreal view projections.
//  (2) note_view() for each actually completed Unreal view, not merely for
//      GetDesiredNumberOfViews or AdjustViewRect callback invocation.
//  (3) queue_composite() only when both views were rendered.
//  (4) note_gpu_complete() only after the compositing GPU fence has signaled.
//  (5) consume_for_submit() once before both OpenXR eye copies.
//  Source validation and released-image continuity are separate contracts.
#include "DuoViewGeometry.hpp"
#include <array>
#include <cmath>
#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::duoview {

struct FrameKey {
    uint64_t generation{};
    uint64_t frame{};
    constexpr bool operator==(const FrameKey&) const = default;
};
class SubmitContinuity {
public:
    void reset() { ready_=false; }
    void submitted(uint64_t generation, uint64_t swapchain, uint64_t now_ms) {
        generation_=generation; swapchain_=swapchain; submitted_ms_=now_ms; ready_=true;
    }
    bool can_hold(uint64_t generation, uint64_t swapchain, uint64_t now_ms) const {
        return ready_ && generation==generation_ && swapchain && swapchain==swapchain_ &&
            now_ms>=submitted_ms_ && now_ms-submitted_ms_<=100;
    }
private:
    uint64_t generation_{}, swapchain_{}, submitted_ms_{};
    bool ready_{};
};

struct RenderFrame {
    FrameKey key{};
    Layout layout{};
    uint64_t pose_token{};
    uint64_t gaze_timestamp_ms{};
};
struct CompositedFrame {
    FrameKey key{};
    uint64_t output_resource_id{};
    uint64_t gpu_fence_value{};
};

inline bool layout_valid(const Layout& l) {
    if (!l.fovea.width || !l.fovea.height || !l.periphery.width ||
        !l.periphery.height || !l.atlas_width || !l.atlas_height) return false;
    const auto in_bounds = [&](const Rect& r) {
        return static_cast<uint64_t>(r.x) + r.width <= l.atlas_width &&
               static_cast<uint64_t>(r.y) + r.height <= l.atlas_height;
    };
    if (!in_bounds(l.fovea) || !in_bounds(l.periphery)) return false;
    const bool disjoint = static_cast<uint64_t>(l.fovea.x) + l.fovea.width <= l.periphery.x ||
        static_cast<uint64_t>(l.periphery.x) + l.periphery.width <= l.fovea.x ||
        static_cast<uint64_t>(l.fovea.y) + l.fovea.height <= l.periphery.y ||
        static_cast<uint64_t>(l.periphery.y) + l.periphery.height <= l.fovea.y;
    if (!disjoint) return false;
    return std::isfinite(l.u0) && std::isfinite(l.v0) &&
        std::isfinite(l.u1) && std::isfinite(l.v1) &&
        l.u0 >= 0.f && l.u0 < l.u1 && l.u1 <= 1.f &&
        l.v0 >= 0.f && l.v0 < l.v1 && l.v1 <= 1.f;
}

class FrameCoordinator {
public:
    bool begin(RenderFrame next) {
        std::scoped_lock lock{mutex_};
        if (!next.key.frame || !next.key.generation || !next.pose_token ||
            !layout_valid(next.layout)) return false;
        if (next.key.generation < last_begin_.generation ||
            (last_begin_.generation == next.key.generation &&
             next.key.frame <= last_begin_.frame)) return false;
        clear_locked();
        last_begin_ = next.key;
        active_ = next;
        return true;
    }

    // Called only for the completed scene rendering of the view; returns false
    // if the view's source generation or frame identity differs from the packet.
    bool note_view(FrameKey key, unsigned index, uint64_t pose_token) {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key || index > 1 ||
            !pose_token || pose_token != active_->pose_token || queued_ ||
            rendered_[index]) return false;
        rendered_[index] = true;
        return true;
    }

    bool queue_composite(FrameKey key, uint64_t output_resource_id,
                         uint64_t gpu_fence_value) {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key || queued_ || !rendered_[0] ||
            !rendered_[1] || !output_resource_id || !gpu_fence_value) return false;
        pending_ = CompositedFrame{key,output_resource_id,gpu_fence_value};
        queued_ = true;
        return true;
    }

    // Call ONLY when the actual D3D12 fence has reached fence_value.
    bool note_gpu_complete(FrameKey key, uint64_t completed_fence_value) {
        std::scoped_lock lock{mutex_};
        if (!active_ || !pending_ || key != active_->key ||
            completed_fence_value < pending_->gpu_fence_value) return false;
        complete_ = true;
        return true;
    }

    std::optional<CompositedFrame> consume_for_submit(FrameKey key) {
        std::scoped_lock lock{mutex_};
        if (!active_ || !pending_ || !complete_ || submitted_ ||
            key != active_->key) return {};
        submitted_ = true;
        return pending_;
    }

    std::optional<RenderFrame> snapshot(FrameKey key) const {
        std::scoped_lock lock{mutex_};
        if (!active_ || key != active_->key) return {};
        return active_;
    }

    void retire() {
        std::scoped_lock lock{mutex_};
        clear_locked();
    }

private:
    void clear_locked() {
        active_.reset();
        pending_.reset();
        rendered_ = {false,false};
        queued_ = complete_ = submitted_ = false;
    }

    mutable std::mutex mutex_{};
    FrameKey last_begin_{};
    std::optional<RenderFrame> active_{};
    std::optional<CompositedFrame> pending_{};
    std::array<bool,2> rendered_{false,false};
    bool queued_{}, complete_{}, submitted_{};
};
} // namespace uevr::duoview
