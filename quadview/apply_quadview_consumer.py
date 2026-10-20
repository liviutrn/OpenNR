#!/usr/bin/env python3
"""Exact-anchor OpenXR/D3D12 consumer adapter, after apply_quadviews.py."""
from pathlib import Path
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('backend', type=Path)
    args = parser.parse_args()
    changed = {}

    def edit(name, old, new):
        path = args.backend / name
        content = changed.get(path, path.read_text(encoding='utf-8'))
        if content.count(old) != 1:
            raise RuntimeError(f'{name}: expected one consumer anchor, got {content.count(old)}: {old[:100]}')
        changed[path] = content.replace(old, new, 1)

    xr_h = 'src/mods/vr/runtimes/OpenXR.hpp'
    xr = 'src/mods/vr/runtimes/OpenXR.cpp'
    dx_h = 'src/mods/vr/D3D12Component.hpp'
    dx = 'src/mods/vr/D3D12Component.cpp'
    edit(xr_h, '        uint64_t duoview_serial{};',
         '        uint64_t duoview_serial{};\n        uint64_t quadview_serial{};\n        bool quadview_pose_valid{};')
    edit(xr_h, '    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);', '''    std::optional<PipelineState> capture_quadview_pose(uint32_t frame);
    std::optional<PipelineState> capture_quadview_current_pose();
    void note_quadview_copy(PipelineState pose, uint64_t generation);
    void invalidate_quadview_scene();
    std::optional<PipelineState> quadview_pending_pose, quadview_submitted_pose;
    uevr::duoview::SubmitContinuity quadview_continuity;
    uint64_t quadview_pose_generation{};
    bool quadview_holding{};
    std::optional<PipelineState> capture_duoview_pose(uint32_t frame);''')
    edit(xr, '    if (vr->mono_frame_gate_required()) {\n        if (vr->is_duoview_renderer_active()) pipeline_state.frame_count=frame_count;',
         '''    if (vr->is_quadview_renderer_active()) {
        pipeline_state.frame_count=frame_count;
        const auto flags=XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT;
        pipeline_state.quadview_pose_valid=view_count==2 &&
            (this->stage_view_state.viewStateFlags & flags)==flags &&
            (this->view_state.viewStateFlags & flags)==flags;
    }
    if (vr->mono_frame_gate_required()) {
        if (vr->is_duoview_renderer_active()) pipeline_state.frame_count=frame_count;''')
    edit(xr, '    mono_frames = {};\n    mono_copied_frame.reset();', '''    mono_frames = {};
    mono_copied_frame.reset();
    quadview_pending_pose.reset(); quadview_submitted_pose.reset();
    quadview_continuity.reset(); quadview_holding=false; quadview_pose_generation=0;''')
    edit(xr, '    auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];\n\n    if (vr->mono_frame_gate_required()) {',
         '    auto& pipeline_state = this->pipeline_states[frame_count % OpenXR::QUEUE_SIZE];\n    if (vr->is_quadview_mode_selected()) pipeline_state.quadview_pose_valid=false;\n\n    if (vr->mono_frame_gate_required()) {')
    edit(xr, 'std::optional<OpenXR::PipelineState> OpenXR::capture_duoview_pose(uint32_t frame) {', '''std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_pose(uint32_t frame) {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto& pose=this->pipeline_states[frame%QUEUE_SIZE];
    if (pose.frame_count!=frame || pose.stage_views.size()!=2 || !pose.quadview_pose_valid) return {};
    const auto& h=pose.view_space_location.pose.orientation;
    const double head_norm=double(h.x)*h.x+double(h.y)*h.y+double(h.z)*h.z+double(h.w)*h.w;
    if (!std::isfinite(head_norm) || std::abs(head_norm-1.0)>.01) return {};
    for (const auto& view : pose.stage_views) {
        const auto& p=view.pose.position; const auto& q=view.pose.orientation; const auto& f=view.fov;
        const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
            !std::isfinite(norm) || std::abs(norm-1.0)>.01 ||
            !std::isfinite(f.angleLeft) || !std::isfinite(f.angleRight) ||
            !std::isfinite(f.angleUp) || !std::isfinite(f.angleDown) ||
            f.angleLeft>=f.angleRight || f.angleDown>=f.angleUp) return {};
    }
    return pose;
}

std::optional<OpenXR::PipelineState> OpenXR::capture_quadview_current_pose() {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto frame=this->internal_frame_count;
    const auto& pose=this->pipeline_states[frame%QUEUE_SIZE];
    if (pose.frame_count!=frame || pose.stage_views.size()!=2 || !pose.quadview_pose_valid ||
        pose.frame_state.predictedDisplayTime<=0 || pose.frame_state.shouldRender!=XR_TRUE) return {};
    const auto& h=pose.view_space_location.pose.orientation;
    const double head_norm=double(h.x)*h.x+double(h.y)*h.y+double(h.z)*h.z+double(h.w)*h.w;
    if (!std::isfinite(head_norm) || std::abs(head_norm-1.0)>.01) return {};
    for (const auto& view : pose.stage_views) {
        const auto& p=view.pose.position; const auto& q=view.pose.orientation; const auto& f=view.fov;
        const double norm=double(q.x)*q.x+double(q.y)*q.y+double(q.z)*q.z+double(q.w)*q.w;
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z) ||
            !std::isfinite(norm) || std::abs(norm-1.0)>.01 ||
            !std::isfinite(f.angleLeft) || !std::isfinite(f.angleRight) ||
            !std::isfinite(f.angleUp) || !std::isfinite(f.angleDown) ||
            f.angleLeft>=f.angleRight || f.angleDown>=f.angleUp) return {};
    }
    return pose;
}

void OpenXR::invalidate_quadview_scene() {
    std::scoped_lock lock{this->sync_assignment_mtx};
    quadview_pending_pose.reset(); quadview_submitted_pose.reset();
    quadview_continuity.reset(); quadview_holding=false; quadview_pose_generation=0;
}

void OpenXR::note_quadview_copy(PipelineState pose, uint64_t generation) {
    std::scoped_lock lock{this->sync_assignment_mtx};
    const auto vr=VR::get();
    if (!vr->is_quadview_renderer_active() || generation!=vr->mono_generation() ||
        pose.stage_views.size()!=2 || !pose.quadview_serial) return;
    if (quadview_pose_generation!=generation) {
        quadview_submitted_pose.reset(); quadview_continuity.reset();
    }
    quadview_pose_generation=generation;
    quadview_pending_pose=std::move(pose);
}

std::optional<OpenXR::PipelineState> OpenXR::capture_duoview_pose(uint32_t frame) {''')
    edit(xr, 'OpenXR::PipelineState OpenXR::get_submit_state() {', '''OpenXR::PipelineState OpenXR::get_submit_state() {
    if (const auto vr=VR::get(); vr->is_quadview_mode_selected()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        PipelineState selected{};
        quadview_holding=false;
        const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
        const uint64_t handle=scene==this->swapchains.end() ? 0 : reinterpret_cast<uint64_t>(scene->second.handle);
        if (vr->is_quadview_renderer_active() && quadview_pose_generation==vr->mono_generation()) {
            if (quadview_pending_pose) {
                selected=std::move(*quadview_pending_pose); quadview_pending_pose.reset();
            } else if (quadview_submitted_pose &&
                quadview_continuity.can_hold(vr->mono_generation(),handle,GetTickCount64())) {
                selected=*quadview_submitted_pose; quadview_holding=true;
            }
        }
        // xrEndFrame uses the current frame time, while eye poses remain bound
        // to the exact source image that was composed or explicitly held.
        selected.frame_state=this->frame_state;
        this->has_render_frame_count=false;
        this->last_submit_state=selected;
        return selected;
    }''')
    edit(xr, '    if (vr->is_duoview_renderer_active()) {\n        std::scoped_lock lock{this->sync_assignment_mtx};\n        if (const auto& stereo=', '''    if (vr->is_quadview_mode_selected()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        if (vr->is_quadview_renderer_active() && result==XR_SUCCESS && !projection_layer_views.empty()) {
            if (!quadview_holding) {
                const auto scene=this->swapchains.find((uint32_t)SwapchainIndex::DOUBLE_WIDE);
                if (scene!=this->swapchains.end()) {
                    quadview_submitted_pose=submit_state;
                    quadview_continuity.submitted(vr->mono_generation(),
                        reinterpret_cast<uint64_t>(scene->second.handle),GetTickCount64());
                }
            }
            vr->set_quadview_status(quadview_holding ? "Holding the last stereo QuadView image briefly" :
                "Four engine histories: stereo QuadView image submitted");
            SPDLOG_INFO_EVERY_N_SEC(2,"[QuadView][Submit] serial={} held={} eyes={}",
                submit_state.quadview_serial,quadview_holding,projection_layer_views.size());
        } else {
            quadview_continuity.reset();
            vr->set_quadview_status("Waiting for an executed four-view source and stereo output");
        }
    } else if (vr->is_duoview_renderer_active()) {
        std::scoped_lock lock{this->sync_assignment_mtx};
        if (const auto& stereo=''')

    edit(dx_h, '#include "DuoViewD3D12.hpp"', '#include "DuoViewD3D12.hpp"\n#include "QuadViewD3D12.hpp"')
    edit(dx_h, '        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;',
         '''        void prepare_quadview_compositors(ID3D12Device* device, DXGI_FORMAT source_format, UINT64 timestamp_frequency);
        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::quadview::dx12::Compositor>> quadview_compositors;
        std::unordered_map<d3d12::CommandContext*, std::unique_ptr<uevr::duoview::dx12::Compositor>> duoview_compositors;''')
    edit(dx, 'void D3D12Component::on_post_present(VR* vr) {\n    if (vr->is_mono_transition_quiescing()) { return; }\n    if (vr->is_mono_transition_waiting() || m_mono_block_post_present) {',
         'void D3D12Component::on_post_present(VR* vr) {\n    if (vr->is_mono_transition_quiescing()) { return; }\n    // Quad owns separate source proof; retire UI allocations even while its first scene is pending.\n    if ((vr->is_mono_transition_waiting() && !vr->is_quadview_mode_selected()) || m_mono_block_post_present) {')
    edit(dx, 'bool D3D12Component::mono_consumers_retired() {', '''bool D3D12Component::mono_consumers_retired() {
    const auto vr=VR::get();
    if (vr && vr->is_quadview_mode_selected()) {
        if (vr->is_mono_transition_pending() && !vr->quadview_transition_draw_closed()) {
            vr->set_quadview_status("Waiting for the active viewport draw to latch a closed ID7 admission boundary");
            return false;
        }
        const auto& stereo=vr->get_fake_stereo_hook();
        if (!stereo || !stereo->quadview_delivery.engine_commands_retired(vr->mono_generation())) {
            vr->set_quadview_status(stereo && stereo->quadview_delivery.engine_tracking_overflowed(vr->mono_generation())
                ? "ID7 engine ownership tracking overflowed; transition remains blocked"
                : "Waiting for tracked ID7 render-thread/RHI owners to execute before transition");
            return false;
        }
    }
    {
        std::scoped_lock lock{m_openxr.mtx};
        for (auto& [commands, compositor] : m_openxr.quadview_compositors) {
            if (!commands || !commands->references_retired()) return false;
            if (compositor) {
                compositor->on_slot_retired();
                if (vr) vr->note_quadview_gpu_ms(compositor->gpu_milliseconds());
            }
        }
    }''')
    edit(dx, 'void D3D12Component::OpenXR::initialize(XrSessionCreateInfo& session_info) {', '''void D3D12Component::OpenXR::prepare_quadview_compositors(ID3D12Device* device, DXGI_FORMAT source_format,
    UINT64 timestamp_frequency) {
    // Prewarm outside copy(): no pipeline/heap/allocation creation in its callback.
    std::scoped_lock lock{mtx};
    auto it=contexts.find((uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE);
    if (it==contexts.end()) return;
    if (source_format==DXGI_FORMAT_B8G8R8A8_TYPELESS) source_format=DXGI_FORMAT_B8G8R8A8_UNORM;
    if (source_format==DXGI_FORMAT_R8G8B8A8_TYPELESS) source_format=DXGI_FORMAT_R8G8B8A8_UNORM;
    auto& context=it->second;
    for (size_t i=0; i<context.texture_contexts.size() && i<context.textures.size(); ++i) {
        auto& tc=context.texture_contexts[i];
        if (!tc || !tc->commands.references_retired() || !context.textures[i].texture) continue;
        auto& comp=quadview_compositors[&tc->commands];
        if (!comp) comp=std::make_unique<uevr::quadview::dx12::Compositor>();
        comp->on_slot_retired();
        auto output_format=context.textures[i].texture->GetDesc().Format;
        // The existing DOUBLE_WIDE swapchain is requested as BGRA8 sRGB;
        // runtimes may expose its resource with a typeless family format.
        if (output_format==DXGI_FORMAT_B8G8R8A8_TYPELESS) output_format=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (output_format==DXGI_FORMAT_R8G8B8A8_TYPELESS) output_format=DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (!comp->prewarm(device,source_format,output_format,timestamp_frequency))
            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][Prewarm] {}",comp->error());
    }
}

void D3D12Component::OpenXR::initialize(XrSessionCreateInfo& session_info) {''')
    edit(dx, '    if (!this->duoview_compositors.empty())\n        return "DuoView command-slot retirement pending; swapchains retained";', '''    if (!this->duoview_compositors.empty())
        return "DuoView command-slot retirement pending; swapchains retained";
    if (!this->quadview_compositors.empty())
        return "QuadView command-slot retirement pending; swapchains retained";''')
    edit(dx, '    for (const auto& [commands, compositor] : this->duoview_compositors) {\n        if (compositor && (!commands || commands->poisoned)) {', '''    for (const auto& [commands, compositor] : this->quadview_compositors) {
        if (compositor && (!commands || commands->poisoned)) {
            spdlog::error("[QuadView] Swapchain retirement is unproven"); return;
        }
    }
    for (const auto& [commands, compositor] : this->duoview_compositors) {
        if (compositor && (!commands || commands->poisoned)) {''')
    edit(dx, '    vr->get_openxr_runtime()->invalidate_duoview_scene();\n    this->duoview_compositors.clear();', '''    for (auto& [commands, compositor] : this->quadview_compositors) {
        if (compositor && !commands->references_retired()) {
            spdlog::error("[QuadView] GPU references have not retired"); return;
        }
        if (compositor) compositor->on_slot_retired();
    }
    vr->get_openxr_runtime()->invalidate_quadview_scene();
    this->quadview_compositors.clear();
    vr->get_openxr_runtime()->invalidate_duoview_scene();
    this->duoview_compositors.clear();''')
    edit(dx, '        vr->get_openxr_runtime()->invalidate_duoview_scene();\n        m_openxr.wait_for_all_copies();', '''        vr->get_openxr_runtime()->invalidate_duoview_scene();
        vr->get_openxr_runtime()->invalidate_quadview_scene();
        m_openxr.wait_for_all_copies();''')
    edit(dx, '                    if (vr->is_duoview_renderer_active()) {\n                        const auto packet = native_stereo_packet;', '''                    if (vr->is_quadview_mode_selected()) {
                        const auto& stereo=vr->get_fake_stereo_hook();
                        const auto source=stereo && vr->is_quadview_renderer_active()
                            ? stereo->quadview_delivery.select(vr->mono_generation(),GetCurrentThreadId())
                            : std::optional<FFakeStereoRenderingHook::QuadViewDelivery::Source>{};
                        if (source && source->packet && source->packet->producer && source->packet->atlas) {
                            const auto packet=source->packet;
                            const auto frozen=packet->producer;
                            UINT64 timestamp_frequency{};
                            if (frozen->settings.gpu_timing) {
                                if (const auto hook=g_framework->get_d3d12_hook(); hook) {
                                    if (const auto queue=hook->get_command_queue(); queue)
                                        queue->GetTimestampFrequency(&timestamp_frequency);
                                }
                            }
                            m_openxr.prepare_quadview_compositors(device,packet->atlas->GetDesc().Format,timestamp_frequency);
                            bool recorded=false;
                            ID3D12Resource* output=nullptr;
                            uintptr_t command_list=0;
                            const bool accepted=m_openxr.copy(
                                (uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE,nullptr,
                                [this,packet,frozen,timestamp_frequency,&recorded,&output,&command_list](d3d12::CommandContext& commands,ID3D12Resource* destination) {
                                    if (!commands.ready() || frozen->key.generation!=VR::get()->mono_generation()) return;
                                    if (!commands.references_retired()) {
                                        VR::get()->set_quadview_status("Waiting for the selected GPU command slot to retire before reuse");
                                        return;
                                    }
                                    const auto found=m_openxr.quadview_compositors.find(&commands);
                                    if (found==m_openxr.quadview_compositors.end() || !found->second) return;
                                    auto& comp=*found->second;
                                    comp.on_slot_retired();
                                    VR::get()->note_quadview_gpu_ms(comp.gpu_milliseconds());
                                    recorded=comp.record(commands.cmd_list.Get(),packet->atlas.Get(),destination,
                                        frozen->layout,frozen->settings,
                                        packet->source_state,D3D12_RESOURCE_STATE_RENDER_TARGET,
                                        std::static_pointer_cast<const void>(packet),
                                        frozen->settings.gpu_timing ? timestamp_frequency : 0);
                                    if (comp.commands_recorded()) commands.has_commands=true;
                                    if (recorded) { output=destination; command_list=reinterpret_cast<uintptr_t>(commands.cmd_list.Get()); }
                                    else SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][Composite] {}",comp.error());
                                },std::nullopt,packet->source_state,nullptr,std::nullopt,packet->atlas.Get());
                            if (accepted && recorded && output &&
                                stereo->quadview_delivery.submitted(*source,reinterpret_cast<uintptr_t>(output))) {
                                auto pose=packet->pose;
                                pose.quadview_serial=source->serial;
                                vr->m_openxr->note_quadview_copy(std::move(pose),source->generation);
                                // Shared mode-transition readiness also gates post-present GPU memory retirement.
                                vr->note_mono_frame_ready(source->generation);
                                SPDLOG_INFO_EVERY_N_SEC(2,"[QuadView][CopyEnqueued] serial={} histories={} source={:x} output={:x}",
                                    source->serial,static_cast<unsigned>(frozen->constructor_mask),
                                    reinterpret_cast<uintptr_t>(packet->atlas.Get()),reinterpret_cast<uintptr_t>(output));
                                vr->quadview_producer().note_compositor_record(frozen->key,
                                    reinterpret_cast<uintptr_t>(packet->atlas.Get()),command_list);
                                // Packet and snapshot stay owned by the fence-bound compositor.
                                vr->quadview_producer().retire(frozen->key);
                                stereo->quadview_delivery.retire(source->generation,source->serial);
                            } else {
                                vr->set_quadview_status("Waiting for a reusable QuadView output slot");
                                SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][CopyRejected] serial={} accepted={} recorded={} output={:x} generation={}/{}",
                                    source->serial,accepted,recorded,reinterpret_cast<uintptr_t>(output),
                                    source->generation,vr->mono_generation());
                            }
                        } else {
                            vr->set_quadview_status("Waiting for four distinct main-family views and executed source");
                            SPDLOG_WARNING_EVERY_N_SEC(2,"[QuadView][OutputWaiting] no executed source generation={} thread={}",
                                vr->mono_generation(),GetCurrentThreadId());
                        }
                    } else if (vr->is_duoview_renderer_active()) {
                        const auto packet = native_stereo_packet;''')
    edit(dx, '    const bool duo_copy=vr->is_duoview_renderer_active() &&',
         '    const bool duo_copy=(vr->is_duoview_renderer_active() || vr->is_quadview_mode_selected()) &&')
    # Once an acquired image is released, OpenXR selects that image for the
    # next projection submission. An old pose cannot make an unwritten image
    # safe to hold. Invalidate at publication, not on entering the compositor:
    # failures before acquisition retain the previous image/pose; every release
    # path clears stale proof, and only accepted copies install replacement proof.
    edit(dx, '    const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];\n    XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};',
         '''    const auto& swapchain = vr->m_openxr->swapchains[swapchain_idx];
    if (vr->is_quadview_mode_selected() &&
        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
        vr->m_openxr->invalidate_quadview_scene();
    XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};''')
    edit(dx, '            XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};\n            if (XR_SUCCEEDED(xrReleaseSwapchainImage(swapchain.handle, &release_info))) {',
         '''            if (vr->is_quadview_mode_selected() &&
                swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
                vr->m_openxr->invalidate_quadview_scene();
            XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
            if (XR_SUCCEEDED(xrReleaseSwapchainImage(swapchain.handle, &release_info))) {''')
    edit(dx, '    XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};\n    auto result = xrReleaseSwapchainImage(swapchain.handle, &release_info);\n\n    // SteamVR shenanigans.',
         '''    // Invalidate the old image/pose only when publishing a replacement.
    // A failed recording or enqueue still releases this acquired image, so it
    // must not be submitted using the previous image's pose.
    if (vr->is_quadview_mode_selected() &&
        swapchain_idx==(uint32_t)runtimes::OpenXR::SwapchainIndex::DOUBLE_WIDE)
        vr->m_openxr->invalidate_quadview_scene();
    XrSwapchainImageReleaseInfo release_info{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
    auto result = xrReleaseSwapchainImage(swapchain.handle, &release_info);

    // SteamVR shenanigans.''')
    for path, content in changed.items():
        path.write_text(content, encoding='utf-8')
    print(f'Applied QuadView consumer adapter to {len(changed)} source files.')


if __name__ == '__main__':
    main()
