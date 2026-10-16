#!/usr/bin/env python3
"""Static regression guards for the transformed Joey source; never a build verdict."""
from pathlib import Path
import argparse
import re


def block(text, anchor):
    start = text.index(anchor)
    opening = text.index("{", start)
    # Ignore braces inside comments and literals while locating this scope.
    tokens = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)
    depth = 0
    for token in tokens.finditer(text, opening):
        if token.group() == "{":
            depth += 1
        elif token.group() == "}":
            depth -= 1
            if depth == 0:
                return text[opening:token.end()]
    raise ValueError("Unterminated scope: " + anchor)


def verify(backend):
    def read(path):
        return (backend / "src/mods" / path).read_text(encoding="utf-8-sig")

    hook = read("vr/FFakeStereoRenderingHook.cpp")
    vr = read("VR.cpp")
    dx = read("vr/D3D12Component.cpp")
    dxh = read("vr/D3D12Component.hpp")
    xr = read("vr/runtimes/OpenXR.cpp")
    vrh = read("VR.hpp")
    cc = (backend / "src/mods/vr/d3d12/CommandContext.cpp").read_text(encoding="utf-8-sig")
    cch = (backend / "src/mods/vr/d3d12/CommandContext.hpp").read_text(encoding="utf-8-sig")
    compositor = read("vr/DuoViewD3D12.hpp")
    recovery_policy = read("vr/DuoViewCommandRecovery.hpp")
    bootstrap_policy = read("vr/DuoViewBootstrap.hpp")
    framework = (backend / "src/Framework.cpp").read_text(encoding="utf-8-sig")
    framework_header = (backend / "src/Framework.hpp").read_text(encoding="utf-8-sig")
    failures = []

    def require(condition, message):
        if not condition:
            failures.append(message)

    key = block(vrh, "uevr::duoview::FrameKey duoview_producer_key()")
    require("m_duoview_draw_frame" in key and "internal_frame_count" not in key,
            "Producer key must not add another frame after pose update")
    latch = hook.find("const auto prior_duoview_frame=vr->exchange_duoview_draw_frame(")
    pose_update = hook.find("vr->update_hmd_state(true, vr->get_runtime()->internal_frame_count + 1);")
    require(0 <= latch < pose_update and "utility::ScopeGuard restore_duoview_draw_frame" in hook,
            "Draw must latch the next frame before updating poses and restore nested scopes")

    begin = block(hook, "void FFakeStereoRenderingHook::begin_render_viewfamily(")
    xr_gate = block(begin, "if (vr->mono_frame_gate_required() && runtime->is_openxr())")
    require("duoview_state().family(" in begin and "duoview_state().family(" not in xr_gate,
            "DuoView family publication must also execute on OpenVR")
    family = block(begin, "if (vr->is_duoview_renderer_active() && views_ptr)") if "if (vr->is_duoview_renderer_active() && views_ptr)" in begin else ""
    require("rtm->get_view_family_render_target()" in family,
            "Family validation must use the same target identity as construction")
    require("utility::ScopeGuard restore_duoview_family" in hook and
            "if (duo_hidden_views) duo_hidden_views->count=duo_original_count" in hook,
            "Hidden DuoView family must restore on C++ unwind")
    constructor = hook.index("auto result = g_hook->m_sceneview_data.constructor_hook.unsafe_call")
    publication = hook.find("if (result && duo_scene_observation)")
    require(publication > constructor and "duoview_state().scene(key,index,state,applied)" not in hook,
            "Scene validity must be published after a successful constructor")
    require(dx.count("vr->duoview_frame_success()") == 1 and
            "if (duo_left_submit_ok) vr->duoview_frame_success()" in dx,
            "DX12 copy must not declare OpenXR presentation success")
    require("if (mono && vr->is_duoview_renderer_active() && !projection_layer_views.empty())" in xr and
            "if (result == XR_SUCCESS) vr->duoview_frame_success()" in xr and
            xr.index("auto result = xrEndFrame(this->session, &frame_end_info);") <
            xr.index("if (result == XR_SUCCESS) vr->duoview_frame_success()"),
            "OpenXR success must follow an accepted nonempty projection submission")
    for name in ("duoview_abort", "duoview_frame_success", "reset_duoview_faults"):
        signature = "void VR::" + name + "("
        body = block(vr, signature) if signature in vr else ""
        require("std::scoped_lock fault_lock{m_duoview_fault_mutex}" in body,
                name + " must serialize the multi-field fault transaction")
    tick = block(vr, "void VR::on_pre_engine_tick(")
    require("std::scoped_lock fault_lock{m_duoview_fault_mutex}" in tick and
            "m_rendering_method->request(RenderingMethod::MONO)" in tick,
            "Fallback recheck and Mono request must share the fault lock")
    bootstrap_request = block(vr, "void VR::request_duoview_autostart_if_ready()")
    bootstrap_draw = block(vr, "bool VR::defer_duoview_bootstrap_draw()")
    framework_init = block(framework, "bool Framework::first_frame_initialize()")
    viewport_draw = block(hook, "void FFakeStereoRenderingHook::game_viewport_client_draw_hook(")
    require("m_vr->on_duoview_startup_config_finalized()" in framework_init and
            framework_init.index("on_duoview_startup_config_finalized()") <
            framework_init.index("m_mods_fully_initialized = true;") and
            "is_mods_fully_initialized() const" in framework_header,
            "Auto-start readiness must publish the post-config request token before completed initialization")
    require("m_duoview_autostart_config_token" in bootstrap_request and
            "selection.request_token()!=baseline_token" in bootstrap_request and
            "m_rendering_method->request(RenderingMethod::DUOVIEW_MONO)" in bootstrap_request and
            "g_framework->is_mods_fully_initialized()" in bootstrap_request,
            "Autostart must override persisted ID5 once, after config, while preserving later choices")
    require("bootstrap_draw_decision(" in bootstrap_draw and
            "BootstrapDrawDecision::wait_for_manual_selection" in bootstrap_draw and
            "set_mono_status(reason)" in bootstrap_draw and
            "mono_supported=ready && mono_unavailable_reason()==nullptr" in bootstrap_draw and
            "m_d3d12.mono_consumers_retired()" in bootstrap_draw and
            "selection.consumers_retired(token)" in bootstrap_draw and
            "service_mono_transition_game_thread();" in bootstrap_draw,
            "Startup gate must retain unsupported Mono requests, or acknowledge actual retirement before frame-boundary commit")
    gate_position = viewport_draw.find("vr->defer_duoview_bootstrap_draw()) return;")
    original_position = viewport_draw.find("call_orig();", viewport_draw.find("if (!vr->is_hmd_active())"))
    early_gate = viewport_draw.find("startup_vr->defer_duoview_bootstrap_draw()")
    early_original = viewport_draw.find("call_orig();", viewport_draw.find("if (!g_framework->is_game_data_intialized())"))
    require(gate_position >= 0 and original_position > gate_position and
            early_gate >= 0 and early_original > early_gate,
            "Target scene Draw must be skipped until the startup transition is safe, including before config readiness")
    require("wait_for_manual_selection" in bootstrap_policy and
            "active_is_native_stereo" in bootstrap_policy and
            "configuration_and_runtime_ready" in bootstrap_policy,
            "Bootstrap policy must distinguish readiness, retirement, and user-required recovery")
    require("context.fence_value>fence_before" in dx and
            "recorded && context.ready() && context.waiting_for_fence" in dx,
            "OpenVR composition must prove a new healthy queued fence")
    pair = block(dxh, "bool copy_duoview_pair(") if "bool copy_duoview_pair(" in dxh else ""
    require("ctx.commands.fence_value<=fence_before" in pair and
            "!ctx.commands.waiting_for_fence" in pair and
            "ctx.commands.try_wait()" in pair and
            "ctx.commands.is_duoview_backpressured()" in pair and
            "wait(INFINITE)" not in pair,
            "Each OpenVR eye copy must defer on busy fences without blocking")
    require("if (duo_scene && !m_openvr.copy_duoview_pair(duo_scene.Get(), eye_copy_deferred))" in dx,
            "Failed eye copies must stop before SteamVR Submit")
    recovery = block(cc, "bool CommandContext::duoview_retirement_proven()")
    execute = block(cc, "void CommandContext::execute()")
    reset = block(cc, "void CommandContext::reset()")
    quarantine = block(cc, "void CommandContext::quarantine_duoview_resources()")
    require("duoview_queue = command_queue" in execute and
            execute.index("command_queue->ExecuteCommandLists") < execute.index("duoview_execute_submitted = true") and
            "command_queue->GetDevice(IID_PPV_ARGS(&this->duoview_device))" in execute,
            "The exact queue/device and ExecuteCommandLists state must be captured inside execute()")
    require("duoview_queue->Signal(this->fence.Get(), next)" in recovery and
            "prior_device_removed" in recovery and
            recovery.index("if (prior_device_removed) return true") < recovery.index("duoview_queue->Signal") and
            recovery.index("duoview_queue->Signal") < recovery.index("FAILED(this->duoview_device->GetDeviceRemovedReason())", recovery.index("duoview_queue->Signal")) and
            "fence_retirement_proven({" in recovery,
            "Failed Signal recovery must use the captured queue and explicit completion/device-loss proof")
    queue_failure = block(execute, "if (command_queue == nullptr)")
    reset_retirement = block(cc, "bool CommandContext::duoview_reset_after_retirement()")
    require("queue_unavailable_after_close" in queue_failure and
            "this->has_commands = failed_before_execute.commands_recorded" in queue_failure and
            "reset_failed_after_retirement(true" in reset_retirement and
            "this->duoview_preexecute_failure_proven = failed_reset.preexecute_failure_proven" in reset_retirement and
            "queue_unavailable_after_close" in recovery_policy and
            "reset_failed_after_retirement" in recovery_policy,
            "Known-unsubmitted queue/reset failures must clear recording state only through retirement policy")
    contracts = (Path(__file__).with_name("ProductionContractTests.cpp")).read_text(encoding="utf-8")
    require("Closed command list with no queue must discard only unsubmitted work" in contracts and
            "Allocator/list reset failure after proven retirement" in contracts and
            "without retirement proof must keep submitted ownership" in contracts,
            "Command recovery failure-sequence contracts are missing")
    require("Unknown backend must defer the target startup Draw" in contracts and
            "Saved fallback ID5 prevented the next eligible launch from requesting ID6" in contracts and
            "wait_for_manual_selection" in contracts and
            "actual GPU-consumer retirement" in contracts,
            "Bootstrap readiness, ID5-to-ID6 launch, unsupported selection, and retirement sequence contracts are missing")
    require("!this->duoview_retirement_proven()" in reset and
            "quarantine_duoview_resources()" in reset and
            "entry.references = this->duoview_retained_references" in quarantine and
            "entry.queue = this->duoview_queue" in quarantine and
            "entry.device = this->duoview_device" in quarantine and
            "entry.command_list = this->cmd_list" in quarantine,
            "Unproven teardown must quarantine the complete retained command/resource graph")
    require("duoview_recovery_enabled" in cch and
            "this->retain_duoview_reference(src)" in cc and
            "this->retain_duoview_reference(dst)" in cc and
            all(token in compositor for token in ("root_.Get()", "pipeline_.Get()", "srv_.Get()",
                "rtv_.Get()", "queries_.Get()", "timestamps_.Get()", "source_.Get()", "output_.Get()")),
            "DuoView command retention must cover copy resources and all compositor-owned GPU objects")
    require("bool duoview_recovery = false" in dxh and
            "bool* deferred_for_gpu = nullptr" in dxh and
            "texture_ctx->commands.is_duoview_backpressured()" in dx and
            "(!submitted || !recorded) && !deferred_for_gpu" in dx,
            "OpenXR busy texture slots must defer without counting as a bad pair")
    require(".eye_tracked=false" in vr and "m_duo_gaze->draw(" not in vr,
            "Fixed-center production path must keep gaze disabled")
    require("std::isfinite(vertical) ? std::clamp(vertical,0.f,1.f) : .5f" in vr,
            "Persisted vertical position must be finite and clamped")
    if failures:
        raise RuntimeError("\n".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", type=Path)
    args = parser.parse_args()
    verify(args.backend)
    print("PASS: static source regression guards only; no SDK/build/GPU/headset certification")
