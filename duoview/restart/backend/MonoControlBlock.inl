if (vr->is_using_mono()) {
                        const auto control_mode = uevr::duoview_restart::dx12::requested_mode();
                        if (control_mode == uevr::duoview_restart::dx12::Mode::disabled &&
                            !uevr::duoview_restart::dx12::diagnostics_enabled()) {
                            bool recorded = false;
                            vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                            const bool submitted = m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                                [source = backbuffer, scene_source_state, device, &recorded](
                                    d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                    if (!commands.ready()) { return; }
                                    recorded = uevr::mono::dx12::copy_scene(commands.cmd_list.Get(), device,
                                        source.Get(), destination, scene_source_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
                                    if (recorded) { commands.has_commands = true; }
                                }, std::nullopt, scene_source_state, nullptr, std::nullopt, backbuffer.Get());
                            vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), submitted && recorded);
                            if (!submitted || !recorded) {
                                vr->set_mono_status("Waiting: Mono scene/device/format/extent or GPU copy validation failed");
                            }
                        } else {
                        const auto producer_frame = static_cast<uint64_t>(frame_count);
                        const bool stable_mask_requested = control_mode != uevr::duoview_restart::dx12::Mode::disabled;
                        bool callback_invoked = false;
                        bool control_recorded = false;
                        bool mono_copy_recorded = false;
                        bool recorded = false;
                        D3D12_RESOURCE_DESC destination_desc{};
                        auto fallback_reason = stable_mask_requested
                            ? uevr::duoview_restart::FallbackReason::producer_callback_not_invoked
                            : uevr::duoview_restart::FallbackReason::diagnostic_disabled;
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), false);
                        auto* const xr_device = m_openxr.binding.device;
                        auto* const xr_queue = m_openxr.binding.queue;
                        auto* const command_queue = g_framework != nullptr && g_framework->get_d3d12_hook() != nullptr
                            ? g_framework->get_d3d12_hook()->get_command_queue() : nullptr;
                        const bool submitted = m_openxr.copy(
                            (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE, nullptr,
                            [source = backbuffer, scene_source_state, device, xr_device, xr_queue,
                                command_queue, producer_frame, control_mode, stable_mask_requested,
                                &callback_invoked, &control_recorded, &mono_copy_recorded, &recorded,
                                &destination_desc, &fallback_reason](
                                d3d12::CommandContext& commands, ID3D12Resource* destination) {
                                callback_invoked = true;
                                if (!commands.ready()) {
                                    fallback_reason = uevr::duoview_restart::FallbackReason::command_context_unavailable;
                                    return;
                                }
                                if (destination != nullptr) { destination_desc = destination->GetDesc(); }
                                if (stable_mask_requested) {
                                    const auto result = uevr::duoview_restart::dx12::instance().record(
                                        control_mode, commands.cmd_list.Get(), device, xr_device,
                                        command_queue, xr_queue, source.Get(), destination,
                                        scene_source_state, D3D12_RESOURCE_STATE_RENDER_TARGET, producer_frame,
                                        commands.fence.Get(), commands.references_retired());
                                    if (result.command_recorded) {
                                        control_recorded = true;
                                        recorded = true;
                                        commands.has_commands = true;
                                        fallback_reason = uevr::duoview_restart::FallbackReason::none;
                                    } else {
                                        fallback_reason = result.reason;
                                    }
                                }
                                if (!control_recorded) {
                                    mono_copy_recorded = uevr::mono::dx12::copy_scene(commands.cmd_list.Get(), device,
                                        source.Get(), destination, scene_source_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
                                    recorded = mono_copy_recorded;
                                    if (mono_copy_recorded) { commands.has_commands = true; }
                                }
                            }, std::nullopt, scene_source_state, nullptr, std::nullopt, backbuffer.Get());
                        if (!callback_invoked && stable_mask_requested) {
                            fallback_reason = uevr::duoview_restart::FallbackReason::producer_callback_not_invoked;
                        }
                        const bool copy_submission_accepted = submitted && recorded;
                        vr->m_openxr->note_mono_copy(static_cast<uint32_t>(frame_count), copy_submission_accepted);
                        if (!submitted || !recorded) {
                            vr->set_mono_status("Waiting: Mono scene/device/format/extent or GPU copy validation failed");
                        }
                        uevr::duoview_restart::FrameObservation observation{};
                        observation.producer_frame = producer_frame;
                        observation.mask_frame = control_recorded ? producer_frame : 0;
                        observation.requested_method = vr->requested_rendering_method();
                        observation.effective_method = vr->is_using_mono()
                            ? static_cast<int32_t>(VR::MONO) : -1;
                        observation.requested_control_mode = static_cast<uint8_t>(control_mode);
                        observation.stable_mask_requested = stable_mask_requested;
                        observation.observed_path = uevr::duoview_restart::copy_accepted_path(
                            copy_submission_accepted, control_recorded, mono_copy_recorded);
                        observation.fallback = fallback_reason;
                        observation.submission_failure = !submitted
                            ? uevr::duoview_restart::FallbackReason::submission_not_accepted
                            : !recorded ? uevr::duoview_restart::FallbackReason::no_copy_command_recorded
                                        : uevr::duoview_restart::FallbackReason::none;
                        observation.control_command_recorded = control_recorded;
                        observation.mono_copy_command_recorded = mono_copy_recorded;
                        observation.copy_api_returned_successfully = submitted;
                        observation.copy_submission_accepted = copy_submission_accepted;
                        if (backbuffer.Get() != nullptr) {
                            const auto source_desc = backbuffer->GetDesc();
                            observation.source_width = static_cast<uint32_t>(source_desc.Width);
                            observation.source_height = source_desc.Height;
                        }
                        observation.destination_width = static_cast<uint32_t>(destination_desc.Width);
                        observation.destination_height = destination_desc.Height;
                        uevr::duoview_restart::dx12::record_observation(observation, control_mode);
                        }
                    } else if (use_native_array_submit) {
