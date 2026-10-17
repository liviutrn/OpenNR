#pragma once
// QuadView engine history/texture lease contract. This does NOT allocate
// Unreal ViewStates. All identities and fence values must be observed at real
// UE/UESDK and D3D12 boundaries; mock identities are unit-test data only.
#include "QuadPairLedger.hpp"
#include <algorithm>
#include <array>
#include <cstdint>
#include <functional>
#include <optional>

namespace uevr::quadview {
struct HistoryObservation {
    uint64_t owner_object{}, reference_slot{}, scene_state{}, scene{};
    uint64_t owner_lifecycle{}, family{}, target{}, target_generation{};
};
using InspectReference = std::function<std::optional<uint64_t>(uint64_t owner, uint64_t reference_slot)>;

class FourHistoryLease {
public:
    // A new mode generation is required after owner reallocation, scene
    // replacement or device/runtime reset; never carry histories across it.
    bool begin(Key key, uint64_t scene, uint64_t owner_lifecycle) {
        if (state_ != State::Idle || scene == 0 || owner_lifecycle == 0 ||
            key.generation == 0 || key.serial == 0 ||
            (previous_.has_value() && (key.generation != previous_->generation ||
             key.serial <= previous_->serial ||
             key.simulation_tick <= previous_->simulation_tick ||
             key.xr_frame <= previous_->xr_frame ||
             scene != previous_scene_ || owner_lifecycle != previous_owner_lifecycle_)))
            return reject();
        key_ = key; scene_ = scene; lifecycle_ = owner_lifecycle;
        current_ = {}; recorded_ = {}; fence_queue_ = 0;
        producer_fences_ = {}; consumer_fence_ = 0;
        state_ = State::Collecting;
        return true;
    }

    bool observe(Eye eye, Role role, const HistoryObservation& h,
                 const InspectReference& inspect) {
        const unsigned index = (eye == Eye::Right ? 2u : 0u) +
                               (role == Role::Periphery ? 1u : 0u);
        if (state_ != State::Collecting || current_[index].has_value() ||
            h.owner_object == 0 || h.reference_slot == 0 || h.scene_state == 0 ||
            h.scene != scene_ || h.owner_lifecycle != lifecycle_ ||
            h.family == 0 || h.target == 0 || h.target_generation == 0 ||
            !inspect) return reject();
        const auto live = inspect(h.owner_object, h.reference_slot);
        if (!live || *live != h.scene_state) return reject();
        for (const auto& other : current_)
            if (other && (other->reference_slot == h.reference_slot ||
                          other->scene_state == h.scene_state ||
                          other->target == h.target)) return reject();
        // Stable engine-owned state/reference across frames is mandatory.
        if (previous_ && (previous_histories_[index].reference_slot != h.reference_slot ||
                          previous_histories_[index].scene_state != h.scene_state ||
                          previous_histories_[index].owner_object != h.owner_object))
            return reject();
        current_[index] = h;
        return true;
    }

    // At the render producer boundary re-inspect all four references. Catch
    // owners destroyed/changed while the two viewport phases were scheduled.
    bool seal(const InspectReference& inspect) {
        if (state_ != State::Collecting || !inspect) return reject();
        for (const auto& h : current_) {
            if (!h) return reject();
            const auto live = inspect(h->owner_object, h->reference_slot);
            if (!live || *live != h->scene_state) return reject();
        }
        if (current_[0]->family == current_[2]->family ||
            current_[0]->family != current_[1]->family ||
            current_[2]->family != current_[3]->family)
            return reject();
        state_ = State::Sealed;
        return true;
    }

    // A single, exact queue is the initial DX12 safety contract. New queues
    // need explicit cross-queue signal/wait tracking, not made-up ordering.
    bool submitted_source(Eye eye, Role role, uint64_t queue, uint64_t fence) {
        const unsigned index = (eye == Eye::Right ? 2u : 0u) +
                               (role == Role::Periphery ? 1u : 0u);
        if (state_ != State::Sealed || queue == 0 || fence == 0 ||
            recorded_[index] || (fence_queue_ && fence_queue_ != queue))
            return reject();
        if (!fence_queue_) fence_queue_ = queue;
        for (auto previous : producer_fences_) if (previous == fence) return reject();
        producer_fences_[index] = fence; recorded_[index] = true;
        return true;
    }

    // Efficient alternative for a single ordered D3D12 producer submission:
    // the caller must prove the *same queue* recorded all four source captures
    // BEFORE signaling one final fence for the whole producer batch. Do not
    // call after partial coverage, and never label CPU completion as a GPU fence.
    // This attestation is an integration obligation, not measured by the ledger.
    bool submitted_joint_producer_batch(uint64_t queue, uint64_t terminal_fence,
                                        bool all_four_captures_recorded) {
        if (state_ != State::Sealed || queue == 0 || terminal_fence == 0 ||
            !all_four_captures_recorded || fence_queue_ ||
            std::any_of(recorded_.begin(), recorded_.end(), [](bool v){return v;}))
            return reject();
        fence_queue_=queue;
        producer_fences_.fill(terminal_fence);
        recorded_.fill(true);
        return true;
    }

    bool submitted_composite(uint64_t queue, uint64_t fence) {
        if (state_ != State::Sealed || queue == 0 || queue != fence_queue_ ||
            fence == 0 || !std::all_of(recorded_.begin(), recorded_.end(), [](bool n){return n;}) ||
            fence <= *std::max_element(producer_fences_.begin(), producer_fences_.end()))
            return reject();
        consumer_fence_ = fence; state_ = State::PendingGPU;
        return true;
    }

    // Do NOT release captured textures or resubmit a new frame merely
    // because command recording succeeded, XR Submit returned or a fence was
    // *signaled*. Only COMPLETED fence on exact device queue proves retirement.
    bool retire(uint64_t queue, uint64_t completed_fence, const InspectReference& inspect) {
        if (state_ != State::PendingGPU || queue != fence_queue_ ||
            completed_fence < consumer_fence_ || !inspect) return false;
        // Owners might be destroyed while the GPU was processing the frame.
        // Reject rather than carry invalid histories to the next frame.
        for (const auto& h : current_) {
            const auto live = inspect(h->owner_object, h->reference_slot);
            if (!live || *live != h->scene_state) return reject();
        }
        for (unsigned i=0;i<4;++i) previous_histories_[i] = *current_[i];
        previous_=key_; previous_scene_=scene_; previous_owner_lifecycle_=lifecycle_;
        state_ = State::Idle; return true;
    }

    // Device removed or owner destroyed: this epoch is poisoned. Its GPU
    // resources must be quarantined by the integration until process exit
    // unless explicit retirement/device-removed proof is available.
    void poison() { state_ = State::Failed; }
    bool failed() const {return state_ == State::Failed;}
    bool gpu_pending() const {return state_ == State::PendingGPU;}
    bool ready_for_next_frame() const {return state_ == State::Idle;}
    // Reset only following external GPU retirement and owner lifecycle reset.
    // This cannot itself destroy an Unreal-owned state.
    bool reset_epoch(bool all_gpu_retired, uint64_t next_generation) {
        if (!all_gpu_retired || next_generation == 0 ||
            (key_.generation && next_generation <= key_.generation))
            return false;
        key_ = {}; current_={}; previous_histories_={};previous_.reset();
        recorded_={};producer_fences_={};consumer_fence_=0;fence_queue_=0;
        scene_=0;lifecycle_=0;previous_scene_=0;previous_owner_lifecycle_=0;
        state_=State::Idle;return true;
    }
private:
    enum class State:uint8_t {Idle,Collecting,Sealed,PendingGPU,Failed};
    bool reject() {state_ = State::Failed; return false;}
    Key key_{};
    uint64_t scene_{},lifecycle_{},fence_queue_{},consumer_fence_{};
    uint64_t previous_scene_{},previous_owner_lifecycle_{};
    std::optional<Key> previous_{};
    std::array<HistoryObservation,4> previous_histories_{};
    std::array<std::optional<HistoryObservation>,4> current_{};
    std::array<uint64_t,4> producer_fences_{};
    std::array<bool,4> recorded_{};
    State state_{State::Idle};
};
} // namespace uevr::quadview
