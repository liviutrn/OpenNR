#pragma once
// Four REAL, engine-created view-history references for same-eye native pairs.
// This adapter does NOT guess private UE virtual slots or synthesize ViewStates.
// An integration must supply VERIFIED engine ABI acquire/inspect/destroy callbacks.
// Do not enable QuadView ID7 merely because this portable contract passes tests.
#include "QuadPairLedger.hpp"
#include <array>
#include <cstdint>
#include <functional>
#include <optional>
#include <thread>
#include <utility>

namespace uevr::quadview {
struct EngineState {
    uint64_t owner{}, reference_slot{}, scene_state{}, scene{}, lifecycle{};
};
struct VerifiedEngineHistoryApi {
    // Must create a *new engine-owned* FSceneViewStateReference, using an
    // engine-supported allocator and feature level, never memcpy / raw malloc.
    std::function<std::optional<EngineState>(Eye, Role, uint32_t)> acquire;
    // Re-read the LIVE owning reference; never trust a cached state address.
    std::function<std::optional<uint64_t>(uint64_t owner, uint64_t slot)> inspect;
    // Must execute on validated UE owning thread after GPU retirement.
    std::function<bool(const EngineState&)> destroy;
};
class NativePairHistoryOwner {
public:
    enum class State { Empty, Ready, GpuPending, Quarantined };
    bool allocate(uint64_t scene, uint64_t lifecycle, uint64_t generation,
                  uint32_t feature_level, VerifiedEngineHistoryApi api) {
        if (state_ != State::Empty || !scene || !lifecycle || !generation ||
            !feature_level || generation <= prior_generation_ ||
            !api.acquire || !api.inspect || !api.destroy)
            return false;
        thread_ = std::this_thread::get_id();
        api_ = std::move(api);
        scene_ = scene; lifecycle_ = lifecycle; generation_ = generation;
        for (unsigned i = 0; i < 4; ++i) {
            const Eye eye = i < 2 ? Eye::Left : Eye::Right;
            const Role role = i % 2 ? Role::Periphery : Role::Fovea;
            auto h = api_.acquire(eye, role, feature_level);
            if (!h || !h->owner || !h->reference_slot || !h->scene_state ||
                h->scene != scene_ || h->lifecycle != lifecycle_) {
                // A returned malformed handle may still own memory. Do not
                // destroy speculative/aliased references: quarantine instead.
                if (h) { state_ = State::Quarantined; return false; }
                return rollback();
            }
            const auto observed = api_.inspect(h->owner, h->reference_slot);
            if (!observed || *observed != h->scene_state) {
                state_ = State::Quarantined; return false;
            }
            for (unsigned j = 0; j < i; ++j)
                if (handles_[j]->scene_state == h->scene_state ||
                    (handles_[j]->owner == h->owner &&
                     handles_[j]->reference_slot == h->reference_slot)) {
                    state_ = State::Quarantined; return false;
                }
            handles_[i] = *h;
        }
        state_ = State::Ready; return true;
    }
    // Requires monotonic logical XR/world frames and four unchanged real
    // UE owner references. This is a prerequisite, not proof of correct
    // rendered projection, singleton renderer isolation or compositor output.
    bool verify_frame(Key frame) {
        if (!correct_thread() || state_ != State::Ready ||
            frame.generation != generation_ || !frame.serial ||
            !frame.simulation_tick || !frame.xr_frame ||
            (last_frame_ && (frame.serial <= last_frame_->serial ||
              frame.simulation_tick <= last_frame_->simulation_tick ||
              frame.xr_frame <= last_frame_->xr_frame)) ||
            !all_live()) {
            if (state_ == State::Ready) state_ = State::Quarantined;
            return false;
        }
        last_frame_ = frame; return true;
    }
    std::optional<EngineState> get(Eye eye, Role role) const {
        if (!correct_thread() || state_ != State::Ready) return {};
        const unsigned i = (eye == Eye::Right ? 2u : 0u) +
                           (role == Role::Periphery ? 1u : 0u);
        return handles_[i];
    }
    // Terminal consumer/composite fence, NOT a producer-only fence.
    bool mark_composite_submitted(uint64_t queue, uint64_t consumer_fence) {
        if (!correct_thread() || state_ != State::Ready || !last_frame_ ||
            !queue || !consumer_fence || !all_live()) {
            if (state_ == State::Ready) state_ = State::Quarantined;
            return false;
        }
        queue_ = queue; consumer_fence_ = consumer_fence;
        state_ = State::GpuPending; return true;
    }
    // Ordinary frame retirement keeps all four persistent Unreal histories
    // alive for TAA/Lumen on the next frame. NEVER destroy states per frame.
    bool retire_frame(uint64_t queue, uint64_t completed_fence) {
        if (!correct_thread() || teardown_requested_ ||
            state_ != State::GpuPending || queue != queue_ ||
            completed_fence < consumer_fence_) return false;
        if (!all_live()) { state_ = State::Quarantined; return false; }
        queue_ = 0; consumer_fence_ = 0; state_ = State::Ready;
        return true;
    }
    // Mode/scene teardown is explicitly requested by integration, NOT inferred
    // from a completed frame. While GPU pending, continue to hold UE owners.
    bool request_teardown() {
        if (!correct_thread() ||
            (state_ != State::Ready && state_ != State::GpuPending))
            return false;
        teardown_requested_ = true; return true;
    }
    bool destroy_after_retirement(uint64_t queue, uint64_t completed_fence) {
        if (!correct_thread() || !teardown_requested_ ||
            state_ != State::GpuPending ||
            queue != queue_ || completed_fence < consumer_fence_) return false;
        if (!all_live()) { state_ = State::Quarantined; return false; }
        return destroy_all();
    }
    // Safe cancellation BEFORE any GPU producer submission.
    bool abandon_unsubmitted() {
        if (!correct_thread() || state_ != State::Ready || !all_live()) {
            if (state_ == State::Ready) state_ = State::Quarantined;
            return false;
        }
        return destroy_all();
    }
    void quarantine() { state_ = State::Quarantined; }
    State state() const { return state_; }
    // Never automatically free engine-owned states on destructor, callback
    // loss, device removal, worker-thread exit or failed retirement.
    ~NativePairHistoryOwner() = default;
    NativePairHistoryOwner() = default;
    NativePairHistoryOwner(const NativePairHistoryOwner&) = delete;
    NativePairHistoryOwner& operator=(const NativePairHistoryOwner&) = delete;
private:
    bool correct_thread() const {
        return thread_ == std::this_thread::get_id();
    }
    bool all_live() const {
        if (!api_.inspect) return false;
        for (auto h : handles_) {
            if (!h || h->scene != scene_ || h->lifecycle != lifecycle_)
                return false;
            const auto current = api_.inspect(h->owner, h->reference_slot);
            if (!current || *current != h->scene_state) return false;
        }
        return true;
    }
    bool rollback() {
        // Only allocated/verified non-aliased handles are held here, and no
        // render commands have been recorded. Destroy in reverse UE order.
        for (unsigned i = 4; i > 0; --i) {
            auto& h = handles_[i-1];
            if (h && !api_.destroy(*h)) {
                state_ = State::Quarantined; return false;
            }
            h.reset();
        }
        state_ = State::Empty; return false;
    }
    bool destroy_all() {
        for (unsigned i = 4; i > 0; --i) {
            auto& h = handles_[i-1];
            if (!h || !api_.destroy(*h)) {
                state_ = State::Quarantined; return false;
            }
            h.reset();
        }
        prior_generation_ = generation_; scene_ = 0; lifecycle_ = 0;
        generation_ = 0; queue_ = 0; consumer_fence_ = 0;
        last_frame_.reset(); teardown_requested_ = false; state_ = State::Empty;
        api_ = {}; return true;
    }
    VerifiedEngineHistoryApi api_{};
    std::array<std::optional<EngineState>,4> handles_{};
    std::optional<Key> last_frame_{};
    std::thread::id thread_{};
    uint64_t scene_{}, lifecycle_{}, generation_{}, prior_generation_{};
    uint64_t queue_{}, consumer_fence_{};
    bool teardown_requested_{};
    State state_{State::Empty};
};
} // namespace uevr::quadview
