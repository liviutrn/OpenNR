#pragma once
#include <cstdint>
namespace duoview_joey {
enum class CopyAction { Native, Compose, Hold, Reject };
struct CopyInputs {
 bool native_producer{}, modified_producer{}, pair_complete{}, supported_source{},
      reserved_slot{}, hold_available{}, exact_generation{};
};
constexpr CopyAction choose_copy(CopyInputs v) {
 if (!v.exact_generation) return CopyAction::Reject;
 if (v.native_producer) return CopyAction::Native;
 if (v.modified_producer && v.pair_complete && v.supported_source && v.reserved_slot)
  return CopyAction::Compose;
 return v.hold_available ? CopyAction::Hold : CopyAction::Reject;
}
struct CopyProof {
 bool original_returned{}, recorded{}, destination_verified{}, poisoned{}, waiting{};
 uint64_t fence_before{}, fence_after{};
 constexpr bool queued() const {
  return original_returned && recorded && destination_verified && !poisoned &&
   waiting && fence_after>fence_before;
 }
};
}
