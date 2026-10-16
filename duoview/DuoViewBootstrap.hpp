#pragma once

namespace uevr::duoview {

enum class BootstrapDrawDecision {
    allow,
    wait_for_backend,
    wait_for_configuration_or_runtime,
    wait_for_retirement,
    wait_for_manual_selection,
};

// Startup may hold only the STALKER 2 viewport while its renderer/runtime
// readiness and a requested Mono-family transition are established. Unknown
// renderer state is deferred; a confirmed non-DX12 backend is left untouched.
constexpr BootstrapDrawDecision bootstrap_draw_decision(
    bool launch_intent,
    bool backend_known,
    bool dx12,
    bool configuration_and_runtime_ready,
    bool mono_transition_supported,
    bool mono_transition_pending,
    bool active_is_native_stereo) {
    if (!launch_intent) return BootstrapDrawDecision::allow;
    if (!backend_known) return BootstrapDrawDecision::wait_for_backend;
    if (!dx12) return BootstrapDrawDecision::allow;
    if (!configuration_and_runtime_ready) return BootstrapDrawDecision::wait_for_configuration_or_runtime;
    if (mono_transition_pending && active_is_native_stereo)
        return mono_transition_supported ? BootstrapDrawDecision::wait_for_retirement
                                         : BootstrapDrawDecision::wait_for_manual_selection;
    return BootstrapDrawDecision::allow;
}

constexpr bool should_defer_bootstrap_draw(BootstrapDrawDecision decision) {
    return decision != BootstrapDrawDecision::allow;
}

} // namespace uevr::duoview
