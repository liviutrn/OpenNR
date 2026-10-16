#pragma once

#include <cstdint>
#include <limits>

namespace uevr::duoview {
struct RecordingRecoveryEvidence {
    bool execute_submitted{};
    bool commands_recorded{};
    bool poisoned{};
    bool preexecute_failure_proven{};
};

constexpr RecordingRecoveryEvidence queue_unavailable_after_close(RecordingRecoveryEvidence evidence) {
    if (!evidence.execute_submitted) return {false, false, true, true};
    return evidence;
}

constexpr RecordingRecoveryEvidence reset_failed_after_retirement(
    bool retirement_proven, RecordingRecoveryEvidence evidence) {
    if (retirement_proven) return {false, false, true, true};
    return evidence;
}

struct FenceRetirementEvidence {
    bool execute_submitted{};
    bool commands_recorded{};
    bool poisoned{};
    bool preexecute_failure_proven{};
    bool submitted_fence_signaled{};
    uint64_t submitted_fence_value{};
    bool recovery_fence_signaled{};
    uint64_t recovery_fence_value{};
    uint64_t completed_value{};
    bool device_removed{};
};

constexpr bool fence_retirement_proven(const FenceRetirementEvidence& evidence) {
    if (evidence.device_removed) return true;
    if (!evidence.execute_submitted)
        return !evidence.commands_recorded && (!evidence.poisoned || evidence.preexecute_failure_proven);
    if (evidence.completed_value == (std::numeric_limits<uint64_t>::max)()) return false;
    return (evidence.submitted_fence_signaled && evidence.submitted_fence_value != 0 &&
            evidence.submitted_fence_value != (std::numeric_limits<uint64_t>::max)() &&
            evidence.completed_value >= evidence.submitted_fence_value) ||
           (evidence.recovery_fence_signaled && evidence.recovery_fence_value != 0 &&
            evidence.recovery_fence_value != (std::numeric_limits<uint64_t>::max)() &&
            evidence.completed_value >= evidence.recovery_fence_value);
}
}
