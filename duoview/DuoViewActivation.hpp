#pragma once
// Independent, fail-closed per-generation activation contract.
// This deliberately refuses to activate a renderer merely because its DLL
// loaded, a DX12 resource has RT flags, or a GPU command was enqueued.
// A real producer->Joey-copy->OpenXR swapchain contract is mandatory.
#include <cstdint>
#include <mutex>
#include <optional>
namespace uevr::duoview {
enum class ActivationPhase : unsigned { Disabled, Observing, Ready, Active, Quiescing, Blocked };
struct CopyContractEvidence {
  uint64_t backend_generation{}, producer_frame{};
  bool exact_binary{}, source_identity{}, source_state_known{},
       producer_queue_ordered{}, destination_swapchain_known{},
       copy_success_observable{}, submit_time_known{}, optical_basis_synchronized{},
       gpu_pipeline_prepared{};
  constexpr bool complete() const noexcept {
    return backend_generation!=0 && producer_frame!=0 && exact_binary &&
        source_identity && source_state_known && producer_queue_ordered &&
        destination_swapchain_known && copy_success_observable &&
        submit_time_known && optical_basis_synchronized && gpu_pipeline_prepared;
  }
};
class ActivationGate {
public:
  void configure(bool requested, uint64_t generation) {
    std::scoped_lock lock(mutex_);
    generation_=generation;
    phase_=requested ? ActivationPhase::Observing : ActivationPhase::Disabled;
    active_frame_.reset();
  }
  bool observe(const CopyContractEvidence& evidence) {
    std::scoped_lock lock(mutex_);
    if (phase_!=ActivationPhase::Observing ||
        evidence.backend_generation!=generation_ || !evidence.complete()) return false;
    phase_=ActivationPhase::Ready;
    return true;
  }
  bool start_frame(uint64_t generation,uint64_t frame) {
    std::scoped_lock lock(mutex_);
    if (!generation || !frame || generation!=generation_ ||
        (phase_!=ActivationPhase::Ready && phase_!=ActivationPhase::Active) ||
        active_frame_) return false;
    active_frame_=frame; phase_=ActivationPhase::Active;
    return true;
  }
  // Unmodified output is not proof of copy; an active frame only completes
  // when the exact acquired XR destination has been copied successfully.
  bool complete_copy(uint64_t generation,uint64_t frame,bool exact_destination,
                     bool copy_success) {
    std::scoped_lock lock(mutex_);
    if (phase_!=ActivationPhase::Active || generation!=generation_ ||
        !active_frame_ || *active_frame_!=frame || !exact_destination || !copy_success) {
      phase_=ActivationPhase::Blocked;
      return false;
    }
    active_frame_.reset(); phase_=ActivationPhase::Ready;
    return true;
  }
  void fault() {
    std::scoped_lock lock(mutex_);
    phase_=ActivationPhase::Blocked;
    active_frame_.reset();
  }
  void reset(uint64_t new_generation) {
    std::scoped_lock lock(mutex_);
    generation_=new_generation;
    phase_=ActivationPhase::Observing;
    active_frame_.reset();
  }
  ActivationPhase phase() const {
    std::scoped_lock lock(mutex_);
    return phase_;
  }
private:
  mutable std::mutex mutex_;
  uint64_t generation_{};
  ActivationPhase phase_{ActivationPhase::Disabled};
  std::optional<uint64_t> active_frame_{};
};
} // namespace uevr::duoview
