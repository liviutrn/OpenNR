"""Bind DuoView metadata to source-family RHI execution; leave stock selection intact."""

def apply(changed, edit):
    hook='src/mods/vr/FFakeStereoRenderingHook.cpp'
    header='src/mods/vr/FFakeStereoRenderingHook.hpp'
    edit(header,'#include "DuoViewState.hpp"','#include "DuoViewState.hpp"\n#include "DuoViewDelivery.hpp"')
    edit(header,'        bool duoview_pose_valid{};','        bool duoview_pose_valid{};\n        sdk::FRenderTarget* duoview_secondary_target{};')
    edit(header,'    bool is_nascar_native_ready() const {', '''    using DuoDelivery = uevr::duoview::Delivery<NativeStereoFramePacket>;
    mutable DuoDelivery duoview_delivery{};
    static inline thread_local std::shared_ptr<const NativeStereoFramePacket> duoview_build_packet{};
    void dump_duoview_delivery() const;

    bool is_nascar_native_ready() const {''')
    edit(hook,'    const auto publish_native_packet = [&]() {\n        auto packet = std::make_shared<NativeStereoFramePacket>();',
    '''    const auto make_native_packet = [&]() -> std::shared_ptr<const NativeStereoFramePacket> {
        auto packet = std::make_shared<NativeStereoFramePacket>();''')
    edit(hook,'            packet->duoview_pose_valid=true;',
         '            packet->duoview_pose_valid=true;\n            packet->duoview_secondary_target=rtfrt;')
    edit(hook,'''        g_hook->publish_native_stereo_frame_packet(std::move(packet));
        if (daysgone_snapshot_transaction != 0) {''',
    '''        return packet;
    };
    const auto duo_build_packet = duo_packet_frame && duo_packet_pose ? make_native_packet() : nullptr;
    const auto previous_duo_build = duoview_build_packet;
    duoview_build_packet = duo_build_packet;
    utility::ScopeGuard restore_duo_build{[&] { duoview_build_packet = previous_duo_build; }};
    const auto publish_native_packet = [&]() {
        g_hook->publish_native_stereo_frame_packet(duo_build_packet ? duo_build_packet : make_native_packet());
        if (daysgone_snapshot_transaction != 0) {''')
    edit(hook,'''    auto views_ptr = view_family.get_views();

    auto runtime = vr->get_runtime();''',
    '''    auto views_ptr = view_family.get_views();
    if (const auto packet = duoview_build_packet; packet && packet->duoview_frame) {
        const auto target = view_family.get_render_target();
        const auto role = target == packet->main_target ? uevr::duoview::SourceRole::primary :
            target == packet->duoview_secondary_target ? uevr::duoview::SourceRole::secondary :
            uevr::duoview::SourceRole::auxiliary;
        if (role != uevr::duoview::SourceRole::auxiliary && !g_hook->duoview_delivery.family(
                {packet, packet->duoview_frame->config.key.generation, reinterpret_cast<uintptr_t>(target),
                 reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), frame_count, role}, GetCurrentThreadId())) {
            SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Delivery] Family registration conflict serial={} frame={}", packet->serial, frame_count);
        }
    }

    auto runtime = vr->get_runtime();''')
    edit(hook,'''    } else {
        last_native_key = {};
    }

    static bool is_ue5_rdg_builder = false;''',
    '''    } else {
        last_native_key = {};
    }
    const auto duo_source = vr->is_duoview_renderer_active()
        ? g_hook->duoview_delivery.render(vr->mono_generation(), frame_count,
            reinterpret_cast<uintptr_t>(view_family.get_render_target()),
            reinterpret_cast<uintptr_t>(view_family.get_scene_interface()), GetCurrentThreadId())
        : DuoDelivery::Source{};

    static bool is_ue5_rdg_builder = false;''')
    # Only the source-bearing PreRender callback (including its captured Slate job) carries a marker.
    begin=changed[hook].index('void FFakeStereoRenderingHook::pre_render_viewfamily_renderthread(')
    end=changed[hook].index('\nvoid FFakeStereoRenderingHook::',begin+10)
    region=changed[hook][begin:end]
    region=region.replace('SceneViewExtensionAnalyzer::hook_old_rhi_command(',
        'if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());\n                    SceneViewExtensionAnalyzer::hook_old_rhi_command(')
    region=region.replace('vr->get_runtime()->enqueue_render_poses(frame_count + compensation);',
        'if (duo_source) g_hook->duoview_delivery.block(duo_source, 0, GetCurrentThreadId());\n                    vr->get_runtime()->enqueue_render_poses(frame_count + compensation);')
    region=region.replace('reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation);',
                          'reinterpret_cast<sdk::FRHICommandBase_New*>(*root), frame_count + compensation, duo_source);')
    region=region.replace('SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation);',
                          'SceneViewExtensionAnalyzer::hook_new_rhi_command(root, frame_count + compensation, duo_source);')
    region=region.replace('SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation);',
                          'SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)l->root, frame_count + compensation, duo_source);')
    region=region.replace('SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation);',
                          'SceneViewExtensionAnalyzer::hook_new_rhi_command((sdk::FRHICommandBase_New*)cmd_list->root, frame_count + compensation, duo_source);')
    changed[hook]=changed[hook][:begin]+region+changed[hook][end:]
    edit(hook,'''    static inline std::unordered_map<sdk::FRHICommandBase_New*, uint32_t> cmd_frame_counts{};''',
    '''    static inline std::unordered_map<sdk::FRHICommandBase_New*, uint32_t> cmd_frame_counts{};
    static inline std::unordered_map<sdk::FRHICommandBase_New*, FFakeStereoRenderingHook::DuoDelivery::Command> duo_command_sources{};''')
    edit(hook,'''        const auto func = (decltype(hooked_command_fn<N>)*)original_func;
        const auto frame_count = cmd_frame_counts[cmd];''',
    '''        const auto func = (decltype(hooked_command_fn<N>)*)original_func;
        const auto frame_count = cmd_frame_counts[cmd];
        const auto source_it = duo_command_sources.find(cmd);
        const auto duo_command = source_it != duo_command_sources.end()
            ? source_it->second : FFakeStereoRenderingHook::DuoDelivery::Command{};
        const auto duo_source = duo_command.owner();''')
    edit(hook,'''                runtime->enqueue_render_poses(frame_count);
                if (g_hook != nullptr) { g_hook->note_nascar25_render_pose_handoff(frame_count); }''',
    '''                if (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation()))
                    runtime->enqueue_render_poses(frame_count);
                if (duo_source && vr->is_duoview_renderer_active() && g_hook != nullptr) {
                    for (const auto& source : duo_command.sources) {
                        if (source) g_hook->duoview_delivery.executed(source, reinterpret_cast<uintptr_t>(cmd), GetCurrentThreadId());
                    }
                }
                if (g_hook != nullptr) { g_hook->note_nascar25_render_pose_handoff(frame_count); }''')
    edit(hook, '        RHIThreadWorker::get().execute();\n\n        if (vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY) {',
    '''        RHIThreadWorker::get().execute();

        if (vr->get_synchronize_stage() == VR::SynchronizeStage::EARLY &&
            (!duo_source || (vr->is_duoview_renderer_active() && duo_source.generation==vr->mono_generation()))) {''')
    edit(hook,'        original_vtables.erase(cmd);\n        cmd_frame_counts.erase(cmd);',
        '        original_vtables.erase(cmd);\n        cmd_frame_counts.erase(cmd);\n        duo_command_sources.erase(cmd);')
    edit(hook,'''    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count) {''',
    '''    static void hook_new_rhi_command(sdk::FRHICommandBase_New* last_command, uint32_t frame_count,
        const FFakeStereoRenderingHook::DuoDelivery::Source& duo_source = {}) {''')
    edit(hook,'''        const bool preserve_pending_identity = uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(''',
    '''        if (duo_source && (!vr->is_duoview_renderer_active() || duo_source.generation!=vr->mono_generation())) return;
        if (!duo_source && vr->is_duoview_renderer_active() && original_vtables.contains(last_command)) return;
        if (duo_source) {
            const char* root_rejection{};
            if (!original_vtables.contains(last_command) && !is_probable_new_rhi_command(last_command, root_rejection)) {
                g_hook->duoview_delivery.block(duo_source, reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
                return;
            }
            uintptr_t readable_begin{}, readable_end{};
            const auto tail = uevr::duoview::command_tail(reinterpret_cast<uintptr_t>(last_command),
                [&](uintptr_t at) -> std::optional<uintptr_t> {
                    if (at < readable_begin || at >= readable_end || readable_end-at < sizeof(sdk::FRHICommandBase_New)) {
                        MEMORY_BASIC_INFORMATION region{};
                        if (!is_readable_process_range(at, sizeof(sdk::FRHICommandBase_New)) ||
                            !VirtualQuery(reinterpret_cast<void*>(at), &region, sizeof(region))) return {};
                        readable_begin=reinterpret_cast<uintptr_t>(region.BaseAddress);
                        readable_end=readable_begin+region.RegionSize;
                    }
                    return reinterpret_cast<uintptr_t>(reinterpret_cast<sdk::FRHICommandBase_New*>(at)->next);
                });
            if (!tail) {
                g_hook->duoview_delivery.block(duo_source, reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
                SPDLOG_WARNING_EVERY_N_SEC(2, "[DuoView][Delivery] Command tail unreadable/cyclic; source ownership not advanced");
                return;
            }
            last_command = reinterpret_cast<sdk::FRHICommandBase_New*>(*tail);
            if (original_vtables.contains(last_command)) {
                const auto owner = duo_command_sources.find(last_command);
                using Attachment=FFakeStereoRenderingHook::DuoDelivery::Attachment;
                const auto attached=owner!=duo_command_sources.end()
                    ? owner->second.attach(duo_source) : Attachment::conflict;
                g_hook->duoview_delivery.note(attached==Attachment::added ? uevr::duoview::DeliveryEvent::hook :
                    attached==Attachment::duplicate ? uevr::duoview::DeliveryEvent::duplicate :
                    uevr::duoview::DeliveryEvent::conflict, duo_source, *tail, GetCurrentThreadId());
                if (attached==Attachment::conflict) g_hook->duoview_delivery.block(duo_source, *tail, GetCurrentThreadId());
                if (attached==Attachment::conflict) SPDLOG_WARNING_EVERY_N_SEC(2,
                    "[DuoView][Delivery] Pending tail ownership conflict command={:x} owner={} incoming={} frame={}",
                    *tail, owner != duo_command_sources.end() && owner->second.owner().packet ? owner->second.owner().packet->serial : 0,
                    duo_source.packet ? duo_source.packet->serial : 0, duo_source.frame);
                return;
            }
        }
        const bool preserve_pending_identity = vr->is_duoview_renderer_active() || uevr::vr_compatibility::should_preserve_mafia_pending_rhi_identity(''')
    edit(hook, '        if (!is_probable_new_rhi_command(last_command, rejection_reason)) {',
    '''        if (!is_probable_new_rhi_command(last_command, rejection_reason)) {
            if (duo_source) g_hook->duoview_delivery.block(duo_source,
                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());''')
    # Preserve Duo pending identities before any pre-render state assignment, including auxiliary callbacks.
    edit(hook,'''        original_vtables[last_command] = *(void***)last_command;
        *(void***)last_command = (void**)new_vtable.data();''',
    '''        original_vtables[last_command] = *(void***)last_command;
        if (duo_source) {
            FFakeStereoRenderingHook::DuoDelivery::Command command{};
            command.attach(duo_source);
            duo_command_sources.emplace(last_command, std::move(command));
            g_hook->duoview_delivery.note(uevr::duoview::DeliveryEvent::hook, duo_source,
                reinterpret_cast<uintptr_t>(last_command), GetCurrentThreadId());
        }
        *(void***)last_command = (void**)new_vtable.data();''')
    edit(hook, '        packet->engine_frame = g_frame_count;\n        packet->render_frame = vr->m_render_frame_count;',
    '''        if (!duo_packet_frame) {
            packet->engine_frame = g_frame_count;
            packet->render_frame = vr->m_render_frame_count;
        }''')
    # Keep Native's legacy clocks unchanged. Duo's selected packet follows RHI source ownership.
    start=changed[hook].index('FFakeStereoRenderingHook::get_native_stereo_frame_packet_for_submit(')
    end=changed[hook].index('\n}\n', start)+3
    prefix=changed[hook][:start]; body=changed[hook][start:end]; suffix=changed[hook][end:]
    old='    const auto packet = m_native_stereo_frame_packet.load(std::memory_order_acquire);'
    assert body.count(old)==1
    body=body.replace(old,'''    const bool duo_transaction = vr->is_duoview_renderer_active();
    const auto packet = duo_transaction
        ? duoview_delivery.select(vr->mono_generation(), GetCurrentThreadId())
        : m_native_stereo_frame_packet.load(std::memory_order_acquire);
    if (duo_transaction && !packet) dump_duoview_delivery();''',1)
    body=body.replace('static_cast<int64_t>(render_frame) - static_cast<int64_t>(packet->render_frame)',
                      'duo_transaction ? 0 : static_cast<int64_t>(render_frame) - static_cast<int64_t>(packet->render_frame)')
    body=body.replace('static_cast<uint32_t>(g_frame_count - packet->engine_frame)',
                      'duo_transaction ? 0u : static_cast<uint32_t>(g_frame_count - packet->engine_frame)')
    body=body.replace('packet->engine_frame == g_frame_count;', '!duo_transaction && packet->engine_frame == g_frame_count;')
    body=body.replace('observation->window_observed = true;', 'observation->window_observed = !duo_transaction;')
    body=body.replace('    if (!frame_diag::frame_window(render_frame_delta, engine_frame_delta, same_engine_frame_present_grace).accepted()) {',
        '    if (!duo_transaction && !frame_diag::frame_window(render_frame_delta, engine_frame_delta, same_engine_frame_present_grace).accepted()) {',1)
    body=body.replace('    if (!exact_render_frame && (same_engine_frame_present_grace || next_engine_frame_handoff)) {',
        '    if (!duo_transaction && !exact_render_frame && (same_engine_frame_present_grace || next_engine_frame_handoff)) {',1)
    changed[hook]=prefix+body+suffix
    edit(hook,'void FFakeStereoRenderingHook::sync_stalker2_native_experiment(bool enabled) {',
    '''void FFakeStereoRenderingHook::dump_duoview_delivery() const {
    static std::atomic<uint64_t> next_dump{};
    const auto now = GetTickCount64();
    auto expected = next_dump.load(std::memory_order_relaxed);
    if (now < expected || !next_dump.compare_exchange_strong(expected, now + 5000)) return;
    const auto events = duoview_delivery.recent();
    spdlog::warn("[DuoView][Delivery] No same-transaction RHI source pair on Present; recent bounded trace follows");
    for (size_t i=events.size()-24; i<events.size(); ++i) {
        const auto& e=events[i];
        if (e.sequence) spdlog::warn("[DuoView][Trace] seq={} us={} event={} gen={} serial={} family={} role={} thread={} command={:x} target={:x} draw={} pose={} capture_gen={}",
            e.sequence, e.time_us, static_cast<uint32_t>(e.event), e.generation, e.serial,
            e.frame, static_cast<uint32_t>(e.role), e.thread, e.command, e.target, e.draw, e.pose, e.capture_generation);
    }
}

void FFakeStereoRenderingHook::sync_stalker2_native_experiment(bool enabled) {''')
    edit(header, '    void on_device_reset() override {\n        if (m_recreate_textures_on_reset->value()) {',
    '''    void on_device_reset() override {
        duoview_delivery.retire();
        if (m_recreate_textures_on_reset->value()) {''')
    edit('src/mods/VR.cpp', '    if (!selection.commit_at_game_frame_boundary()) { return; }\n    m_duoview.retire();',
    '''    if (!selection.commit_at_game_frame_boundary()) { return; }
    m_duoview.retire();
    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.retire(mono_generation());''')
    edit('src/mods/VR.cpp', '    m_duoview_quarantined.store(true, std::memory_order_release);\n    m_duoview.retire();',
    '''    m_duoview_quarantined.store(true, std::memory_order_release);
    m_duoview.retire();
    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.retire(mono_generation());''')
    edit(header,'        sdk::FRenderTarget* duoview_secondary_target{};',
        '        sdk::FRenderTarget* duoview_secondary_target{};\n        Microsoft::WRL::ComPtr<ID3D12Resource> duoview_primary_resource{};')
    edit(hook,'            packet->duoview_secondary_target=rtfrt;',
    '''            packet->duoview_secondary_target=rtfrt;
            if (const auto primary=rtm->get_render_target()) {
                if (const auto native=static_cast<IUnknown*>(primary->get_native_resource())) {
                    native->QueryInterface(IID_PPV_ARGS(&packet->duoview_primary_resource));
                }
            }''')
    dx='src/mods/vr/D3D12Component.cpp'
    edit(dx,'                            packet->duoview_pose_valid;',
    '''                            packet->duoview_pose_valid && packet->duoview_primary_resource.Get()!=nullptr &&
                            packet->duoview_primary_resource.Get()==m_game_tex.texture.Get();''')
    edit(dx,'                            if (submitted && recorded) {\n                                runtimes::OpenXR::PipelineState pose{};',
    '''                            if (submitted && recorded && callback_attempted) {
                                native_stereo_hook->duoview_delivery.result(uevr::duoview::DeliveryEvent::copy,
                                    packet->serial, true, GetCurrentThreadId());
                                runtimes::OpenXR::PipelineState pose{};
                                pose.duoview_serial=packet->serial;''')
    edit(dx,'    const auto stalker_fence_before = retained_stalker_pair ? texture_ctx->commands.fence_value : 0;',
    '''    const bool duo_copy=vr->is_duoview_renderer_active() &&
        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE;
    const auto duo_fence_before=texture_ctx->commands.fence_value;
    const bool duo_recorded=texture_ctx->commands.has_commands;
    const auto stalker_fence_before = retained_stalker_pair ? texture_ctx->commands.fence_value : 0;''')
    edit(dx,'    bool stalker_enqueued = false;\n    if (retained_stalker_pair) {',
    '''    const bool duo_enqueued=!duo_copy || uevr::stalker2_native::SubmissionProof{
        duo_fence_before, texture_ctx->commands.fence_value, duo_recorded,
        !texture_ctx->commands.poisoned, texture_ctx->commands.waiting_for_fence,
        texture_ctx->commands.fence!=nullptr,
        binding.queue==g_framework->get_d3d12_hook()->get_command_queue(),
        binding.device==g_framework->get_d3d12_hook()->get_device()}.confirmed();
    bool stalker_enqueued = false;
    if (retained_stalker_pair) {''')
    edit(dx,'    return !texture_ctx->commands.poisoned && (!retained_stalker_pair || stalker_enqueued);',
        '    return duo_enqueued && !texture_ctx->commands.poisoned && (!retained_stalker_pair || stalker_enqueued);')
    xrh='src/mods/vr/runtimes/OpenXR.hpp'
    xr='src/mods/vr/runtimes/OpenXR.cpp'
    edit(xrh,'    struct PipelineState {\n        XrFrameState',
        '    struct PipelineState {\n        uint64_t duoview_serial{};\n        XrFrameState')
    edit(xr,'    if (vr->is_duoview_renderer_active()) {\n        std::scoped_lock lock{this->sync_assignment_mtx};\n        if (result==XR_SUCCESS && !projection_layer_views.empty()) {',
    '''    if (vr->is_duoview_renderer_active()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        if (const auto& stereo=vr->get_fake_stereo_hook(); stereo && this->frame_state.shouldRender==XR_TRUE) {
            stereo->duoview_delivery.result(uevr::duoview::DeliveryEvent::submit,
                submit_state.duoview_serial, result==XR_SUCCESS && !projection_layer_views.empty(), GetCurrentThreadId());
        }
        if (result==XR_SUCCESS && !projection_layer_views.empty()) {''')
    edit('src/mods/VR.cpp','                if (ImGui::Button("Reset DuoView delivery counters")) {',
    '''                if (m_fake_stereo_hook) {
                    const auto d=m_fake_stereo_hook->duoview_delivery.counts();
                    ImGui::TextWrapped("Transactions: %llu produced / %llu RHI pairs / %llu matched / %llu enqueued / %llu unique XR",
                        (unsigned long long)d.produced, (unsigned long long)d.ready, (unsigned long long)d.matched,
                        (unsigned long long)d.enqueued, (unsigned long long)d.submitted);
                    ImGui::TextWrapped("Duplicate Presents: %llu / overwritten before XR: %llu / failures: %llu / unproven: %llu",
                        (unsigned long long)d.duplicate_presents, (unsigned long long)d.overwritten,
                        (unsigned long long)d.failed, (unsigned long long)d.blocked);
                }
                if (ImGui::Button("Reset DuoView delivery counters")) {
                    if (m_fake_stereo_hook) m_fake_stereo_hook->duoview_delivery.reset_counts();''')
