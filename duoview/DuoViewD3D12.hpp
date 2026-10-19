#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewMonoCopyD3D12.hpp"
#include "DuoViewState.hpp"
#include "DuoViewShaderSource.hpp"
#include <memory>
#include <string>

namespace uevr::duoview::dx12 {
using Microsoft::WRL::ComPtr;
struct ShaderConstants {
    uint32_t output[2], atlas[2], fovea[4], periphery[4];
    float crop[4], feather;
    uint32_t border;
    uint32_t diagnostic;
    float reserved;
    uint32_t fovea_source_size[2], peripheral_source_size[2];
    uint32_t output_offset[2];
};
static_assert(sizeof(ShaderConstants) == 104);

class Compositor {
public:
    // Prebuild the per-slot PSO, descriptors and output outside OpenXR frame copy.
    // Called after swapchain images and their command contexts are constructed.
    bool prewarm(ID3D12Device* device, UINT width, UINT height, bool srgb, UINT64 frequency = 0) {
        if (!device || !width || !height || FAILED(device->GetDeviceRemovedReason())) return false;
        if (!prepare(device, width, height, srgb)) return false;
        setup_timing(device, frequency);
        return true;
    }
    // One instance per retired OpenXR command slot; descriptors/resources must
    // stay alive until that slot's GPU fence completes.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* atlas, ID3D12Resource* destination,
                D3D12_RESOURCE_STATES atlas_state, const FrameConfig& frame, UINT64 frequency = 0) {
        recorded_commands_ = false;
        if (!device || !cmd || !atlas || !destination || atlas == destination ||
            cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.layout)) return false;
        const auto source = atlas->GetDesc(), target = destination->GetDesc();
        const auto& l = frame.layout;
        if (source.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            target.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            source.Width != l.atlas_width || source.Height != l.atlas_height ||
            target.Width != l.atlas_width || target.Height != l.atlas_height ||
            source.DepthOrArraySize != 1 || target.DepthOrArraySize != 1 ||
            source.SampleDesc.Count != 1 || target.SampleDesc.Count != 1 ||
            source.SampleDesc.Quality != 0 || target.SampleDesc.Quality != 0 ||
            !(target.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            l.atlas_width / 2 > 16384 ||
            source.MipLevels != 1 || target.MipLevels != 1 ||
            (source.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) || !bgra8(target.Format)) return false;
        const auto format = srv_format(source.Format);
        if (format == DXGI_FORMAT_UNKNOWN) return false;
        ComPtr<ID3D12Device> sd, dd, cd;
        if (FAILED(atlas->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            sd.Get() != device || dd.Get() != device || cd.Get() != device) return false;
        const bool srgb = format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB || format == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (!prepare(device, l.atlas_width / 2, l.atlas_height, srgb)) return false;
        const bool timed = frequency && frequency == frequency_ && queries_ && timestamps_;
        update_timing(timed,false);
        ShaderConstants constants{
            {l.atlas_width / 2, l.atlas_height}, {l.atlas_width, l.atlas_height},
            {l.fovea.x, l.fovea.y, l.fovea.width, l.fovea.height},
            {l.periphery.x, l.periphery.y, l.periphery.width, l.periphery.height},
            {l.u0, l.v0, l.u1, l.v1}, frame.settings.feather_fraction,
            frame.settings.debug_border ? 1u : 0u, frame.settings.diagnostic_view, 0.f};
        ensure_srvs(device,atlas,atlas,format);
        source_ = atlas;
        transition(cmd, atlas, atlas_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_ = true;
        if (timed) cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(constants) / 4, &constants, 0);
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(width_), static_cast<float>(height_), 0, 1};
        const D3D12_RECT rect{0, 0, static_cast<LONG>(width_), static_cast<LONG>(height_)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &rect);
        const auto handle = rtv_cpu_start_;
        cmd->OMSetRenderTargets(1, &handle, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);
        const auto copied = copy_composite_to_stereo(cmd, device, output_.Get(), destination,
            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET);
        if (timed) {
            cmd->EndQuery(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 1);
            cmd->ResolveQueryData(queries_.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 2, timestamps_.Get(), 0);
            timing_pending_ = true; pending_direct_xr_=false;
        }
        return copied;
    }
    // Direct Native Fix composition: keep Joey's exact UE rendering and
    // captures, but sample the existing view rectangles as two SRVs instead
    // of copying them to a third (doublewide) render texture first.
    // No new GPU resources or PSO are created in this XR command callback.
    bool record_native(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {
        recorded_commands_=false;
        error_.clear();
        last_native_direct_xr_=false;
        const auto reject=[this](const char* reason) { error_=reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination ||
            primary==secondary || primary==destination || secondary==destination ||
            cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid direct Native source resources or DuoView layout");
        const auto& layout=frame.config.layout;
        if (frame.config.settings.fovea_view>1)
            return reject("Invalid frozen Native fovea source index");
        if (device_.Get()!=device || width_!=layout.atlas_width/2 ||
            height_!=layout.atlas_height || !output_ || !native_pipeline_ ||
            !root_ || !srv_ || !rtv_)
            return reject("Direct Native compositor not prewarmed for frozen source extent");
        const auto p=primary->GetDesc(), s=secondary->GetDesc();
        const auto xrd=destination->GetDesc();
        last_native_source_extents_=
            (uint64_t(static_cast<uint32_t>(p.Width)&0xffffu)<<48)|
            (uint64_t(p.Height&0xffffu)<<32)|
            (uint64_t(static_cast<uint32_t>(s.Width)&0xffffu)<<16)|
            uint64_t(s.Height&0xffffu);
        const auto xr_format=srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        // Render directly to the doublewide OpenXR texture only when its
        // render-target format matches the precompiled PSO. Keep a bit-for-bit
        // old compositor+copy fallback for incompatible swapchain formats.
        if (!stereo_destination_valid(xrd,width_,height_))
            return reject("Invalid Mono XR output dimensions, format, or render-target flags");
        const bool direct_xr=frame.config.settings.direct_xr_output &&
            xrd.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
            xrd.Width==static_cast<uint64_t>(width_)*2 && xrd.Height==height_ &&
            xrd.DepthOrArraySize==1 && xrd.MipLevels==1 &&
            xrd.SampleDesc.Count==1 && xrd.SampleDesc.Quality==0 &&
            (xrd.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)!=0 &&
            (xrd.Format==xr_format || xrd.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS);
        const auto& pr=frame.config.settings.fovea_view==0 ? layout.fovea : layout.periphery;
        const auto& sr=frame.config.settings.fovea_view==1 ? layout.fovea : layout.periphery;
        const auto is_bgra_family=[](DXGI_FORMAT f) {
            return f==DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        const auto valid_source=[&](const D3D12_RESOURCE_DESC& d,const Rect& rect) {
            return d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
                is_bgra_family(d.Format) && d.Width>=rect.width && d.Height>=rect.height &&
                d.DepthOrArraySize==1 && d.MipLevels==1 &&
                d.SampleDesc.Count==1 && d.SampleDesc.Quality==0 &&
                true;
        };
        if (!valid_source(p,pr) || !valid_source(s,sr) ||
            p.Width>UINT32_MAX || s.Width>UINT32_MAX ||
            p.Height>UINT32_MAX || s.Height>UINT32_MAX)
            return reject("Direct Native source format / rect incompatible with frozen view");
        const auto sampling_format=srgb_
            ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB
            : DXGI_FORMAT_B8G8R8A8_UNORM;
        // A typed resource cannot legally be reinterpreted as a different
        // sRGB class. This deliberately fails closed rather than silently
        // changing shading, unlike a typeless Native Fix capture.
        if ((p.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (s.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            (p.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && p.Format!=sampling_format) ||
            (s.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS && s.Format!=sampling_format)) {
            // Uncommon sources can still be copied safely. Never turn an
            // optimization compatibility failure into a black headset frame.
            return record_native_gather(device,cmd,primary,secondary,destination,
                primary_state,secondary_state,frame,std::move(packet_lifetime),frequency);
        }
        ComPtr<ID3D12Device> pd,sd,dd,cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get()!=device || sd.Get()!=device || dd.Get()!=device || cd.Get()!=device)
            return reject("Native primary/secondary/XR resource device mismatch");

        auto* fovea=frame.config.settings.fovea_view==0 ? primary : secondary;
        auto* periphery=frame.config.settings.fovea_view==0 ? secondary : primary;
        const auto& fd=frame.config.settings.fovea_view==0 ? p : s;
        const auto& vd=frame.config.settings.fovea_view==0 ? s : p;
        const auto fovea_state=frame.config.settings.fovea_view==0 ? primary_state : secondary_state;
        const auto peripheral_state=frame.config.settings.fovea_view==0 ? secondary_state : primary_state;

        ShaderConstants constants{
            {layout.atlas_width/2,layout.atlas_height},
            {layout.atlas_width,layout.atlas_height},
            {layout.fovea.x,layout.fovea.y,layout.fovea.width,layout.fovea.height},
            {layout.periphery.x,layout.periphery.y,layout.periphery.width,layout.periphery.height},
            {layout.u0,layout.v0,layout.u1,layout.v1},
            frame.config.settings.feather_fraction,
            frame.config.settings.debug_border ? 1u : 0u,
            frame.config.settings.diagnostic_view, 0.f,
            {static_cast<uint32_t>(fd.Width),fd.Height},
            {static_cast<uint32_t>(vd.Width),vd.Height}
        };
        ensure_srvs(device,fovea,periphery,sampling_format);
        // GPU lifetime remains bound to the exact retired OpenXR command slot,
        // never to whichever engine packet happens to arrive next.
        primary_reference_=primary; secondary_reference_=secondary;
        packet_lifetime_=std::move(packet_lifetime);
        const bool timed=frequency && frequency==frequency_ && queries_ && timestamps_;
        update_timing(timed,direct_xr);
        transition(cmd,fovea,fovea_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(cmd,periphery,peripheral_state,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        recorded_commands_=true;
        if (timed) cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1,heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(native_pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0,srv_gpu_start_);
        cmd->SetGraphicsRoot32BitConstants(1,sizeof(constants)/4,&constants,0);
        auto handle=rtv_cpu_start_;
        if (direct_xr) {
            // Each Compositor is owned by one fenced XR command slot, so its
            // second RTV descriptor cannot be overwritten while GPU-active.
            handle=direct_xr_rtv_cpu_;
            if (xr_rtv_reference_.Get()!=destination || xr_rtv_format_!=xr_format) {
                D3D12_RENDER_TARGET_VIEW_DESC xr_view{};
                xr_view.Format=xr_format; xr_view.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
                device->CreateRenderTargetView(destination,&xr_view,handle);
                xr_rtv_reference_=destination;
                xr_rtv_format_=xr_format;
                ++xr_rtv_refresh_count_;
            }
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_*2),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_*2),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        } else {
            const D3D12_VIEWPORT viewport{
                0,0,static_cast<float>(width_),static_cast<float>(height_),0,1};
            const D3D12_RECT rect{
                0,0,static_cast<LONG>(width_),static_cast<LONG>(height_)};
            cmd->RSSetViewports(1,&viewport);
            cmd->RSSetScissorRects(1,&rect);
            cmd->OMSetRenderTargets(1,&handle,FALSE,nullptr);
            cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
            cmd->DrawInstanced(3,1,0,0);
        }
        transition(cmd,fovea,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,fovea_state);
        transition(cmd,periphery,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,peripheral_state);
        const bool copied=direct_xr ||
            copy_composite_to_stereo(cmd,device,output_.Get(),destination,
                D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET);
        last_native_direct_xr_=direct_xr;
        if (timed) {
            cmd->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            cmd->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true; pending_direct_xr_=direct_xr;
        }
        if (!copied) return reject("Direct Native blend succeeded but Mono XR output validation failed");
        return true;
    }
    // Fallback for capture resources that cannot be sampled as SRVs.
    // Keep the original bit-for-bit gather path for format and GPU safety.
    // Gather Joey's actual Native Stereo Fix primary and secondary render
    // targets into this command slot's atlas, then run the same Mono compositor.
    bool record_native_gather(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* primary, ID3D12Resource* secondary,
                ID3D12Resource* destination, D3D12_RESOURCE_STATES primary_state,
                D3D12_RESOURCE_STATES secondary_state, const ViewFrame& frame,
                std::shared_ptr<const void> packet_lifetime, UINT64 frequency = 0) {
        recorded_commands_ = false;
        error_.clear();
        const auto reject = [this](const char* reason) { error_ = reason; return false; };
        if (!device || !cmd || !primary || !secondary || !destination || primary == secondary ||
            primary == destination || secondary == destination || cmd->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason()) || !layout_valid(frame.config.layout))
            return reject("Invalid Native resources, D3D12 device, or DuoView layout");
        last_native_direct_xr_=false;
        if (!stereo_destination_valid(destination->GetDesc(),frame.config.layout.atlas_width/2,
                                      frame.config.layout.atlas_height))
            return reject("Invalid gather XR destination before source copy");
        if (!atlas_) return reject("Missing prewarmed Native gather atlas (ID6 activation setup)");
        const auto p = primary->GetDesc(), s = secondary->GetDesc(), a = atlas_->GetDesc();
        const auto& l = frame.config.layout;
        const auto& primary_rect = frame.config.settings.fovea_view == 0 ? l.fovea : l.periphery;
        const auto& secondary_rect = frame.config.settings.fovea_view == 1 ? l.fovea : l.periphery;
        const auto valid_source = [&](const D3D12_RESOURCE_DESC& d, const Rect& r) {
            return d.Dimension == D3D12_RESOURCE_DIMENSION_TEXTURE2D && bgra8(d.Format) &&
                d.Width >= r.width && d.Height >= r.height && d.DepthOrArraySize == 1 &&
                d.MipLevels == 1 && d.SampleDesc.Count == 1 && d.SampleDesc.Quality == 0;
        };
        if (!valid_source(p, primary_rect) || !valid_source(s, secondary_rect) ||
            a.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || a.Width != l.atlas_width ||
            a.Height != l.atlas_height || a.DepthOrArraySize != 1 || a.MipLevels != 1 ||
            a.SampleDesc.Count != 1 || a.SampleDesc.Quality != 0 ||
            (a.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            primary == atlas_.Get() || secondary == atlas_.Get() || destination == atlas_.Get())
            return reject("Native capture extent/format incompatible with frozen atlas rectangles");
        ComPtr<ID3D12Device> pd, sd, dd, cd;
        if (FAILED(primary->GetDevice(IID_PPV_ARGS(&pd))) ||
            FAILED(secondary->GetDevice(IID_PPV_ARGS(&sd))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
            FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
            pd.Get() != device || sd.Get() != device || dd.Get() != device || cd.Get() != device)
            return reject("Native source / XR destination command-list device mismatch");
        const auto is_bgra_family = [](DXGI_FORMAT f) {
            return f == DXGI_FORMAT_B8G8R8A8_TYPELESS ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM ||
                   f == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        };
        if (!is_bgra_family(p.Format) || !is_bgra_family(s.Format) ||
            !bgra8(a.Format) ||
            a.Format != (srgb_ ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM))
            return reject("Native BGRA8 format/sRGB mismatch with prewarmed atlas");
        // record_native must use the exact prewarmed objects. Rebuilding here
        // would release atlas_ after CopyTextureRegion has already been queued.
        if (device_.Get() != device || width_ != l.atlas_width / 2 ||
            height_ != l.atlas_height || !output_ || !pipeline_ || !root_ || !srv_ || !rtv_)
            return reject("Native mode dimensions or shader state differ from prewarmed command slot");
        if (!copy_source_to_atlas(cmd, primary, atlas_.Get(), primary_state,
                                  primary_rect.x, primary_rect.y, primary_rect.width, primary_rect.height) ||
            !copy_source_to_atlas(cmd, secondary, atlas_.Get(), secondary_state,
                                  secondary_rect.x, secondary_rect.y, secondary_rect.width, secondary_rect.height)) {
            return reject("Failed recording Native primary/secondary source atlas copy");
        }
        recorded_commands_ = true;
        // These references live in the OpenXR command slot's compositor object.
        // Its slot is replaced only after the prior command fence has retired.
        primary_reference_ = primary;
        secondary_reference_ = secondary;
        packet_lifetime_ = std::move(packet_lifetime);
        const bool composed = record(device, cmd, atlas_.Get(), destination,
            D3D12_RESOURCE_STATE_COPY_DEST, frame.config, frequency);
        // record() clears its own command marker at entry. Preserve the gather
        // commands even if it rejects the later composite pass.
        const bool gather_recorded = true;
        recorded_commands_ = recorded_commands_ || gather_recorded;
        if (!composed && error_.empty()) error_ = "Native gather succeeded but Mono raster/copy validation failed";
        return composed;
    }
    const std::string& error() const { return error_; }
    bool recorded_commands() const { return recorded_commands_; }
    float gpu_milliseconds() const { return gpu_ms_; }
    bool last_native_direct_xr() const { return last_native_direct_xr_; }
    uint64_t last_native_source_extents() const { return last_native_source_extents_; }
    uint64_t srv_descriptor_refresh_count() const { return srv_descriptor_refresh_count_; }
    uint64_t xr_rtv_refresh_count() const { return xr_rtv_refresh_count_; }
    UINT64 timing_frequency() const { return frequency_; }
private:
    void ensure_srvs(ID3D12Device* device, ID3D12Resource* first,
                     ID3D12Resource* second, DXGI_FORMAT format) {
        if (srv_descriptors_valid_ && srv_first_reference_.Get()==first &&
            srv_second_reference_.Get()==second && srv_cached_format_==format) return;
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format=format;
        view.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels=1;
        auto cpu=srv_cpu_start_;
        device->CreateShaderResourceView(first,&view,cpu);
        cpu.ptr+=srv_descriptor_increment_;
        device->CreateShaderResourceView(second,&view,cpu);
        srv_first_reference_=first; srv_second_reference_=second;
        srv_cached_format_=format; srv_descriptors_valid_=true;
        ++srv_descriptor_refresh_count_;
    }
    void update_timing(bool timed, bool direct_xr) {
        if (!timed || (timing_pending_ && pending_direct_xr_!=direct_xr)) {
            timing_pending_=false;
            gpu_ms_=-1.f;
        }
        if (timed) read_timing();
    }
    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        D3D12_RANGE range{0, sizeof(UINT64) * 2};
        UINT64* data{};
        if (SUCCEEDED(timestamps_->Map(0, &range, reinterpret_cast<void**>(&data)))) {
            if (data[1] >= data[0]) gpu_ms_ = static_cast<float>((data[1] - data[0]) * 1000.0 / frequency_);
            D3D12_RANGE no_write{0, 0}; timestamps_->Unmap(0, &no_write);
        }
        timing_pending_ = false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!frequency || queries_) return;
        D3D12_QUERY_HEAP_DESC q{}; q.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP; q.Count = 2;
        if (FAILED(device->CreateQueryHeap(&q, IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{}; buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = sizeof(UINT64) * 2; buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1; buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&timestamps_)))) { queries_.Reset(); return; }
        frequency_ = frequency;
        queries_->SetName(L"DuoView::GPUQueries"); timestamps_->SetName(L"DuoView::GPUTimestamps");
    }
    static DXGI_FORMAT srv_format(DXGI_FORMAT f) {
        switch (f) {
        case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
        case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
        case DXGI_FORMAT_B8G8R8A8_UNORM: case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
        case DXGI_FORMAT_R8G8B8A8_UNORM: case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
        case DXGI_FORMAT_R10G10B10A2_UNORM: case DXGI_FORMAT_R16G16B16A16_FLOAT: return f;
        default: return DXGI_FORMAT_UNKNOWN;
        }
    }
    static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r,
                           D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER b{};
        b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition = {r, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        cmd->ResourceBarrier(1, &b);
    }
    static bool copy_source_to_atlas(ID3D12GraphicsCommandList* cmd, ID3D12Resource* source,
        ID3D12Resource* atlas, D3D12_RESOURCE_STATES source_state, UINT x, UINT y, UINT width, UINT height) {
        if (!width || !height) return false;
        transition(cmd, source, source_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        const D3D12_TEXTURE_COPY_LOCATION from{source, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_TEXTURE_COPY_LOCATION to{atlas, D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX, {0}};
        const D3D12_BOX box{0, 0, 0, width, height, 1};
        cmd->CopyTextureRegion(&to, x, y, 0, &from, &box);
        transition(cmd, source, D3D12_RESOURCE_STATE_COPY_SOURCE, source_state);
        return true;
    }
    bool check(HRESULT hr, const char* operation) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(operation) + " HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    bool prepare(ID3D12Device* device, UINT width, UINT height, bool srgb) {
        if (device_.Get() == device && output_ && atlas_ && pipeline_ && native_pipeline_ && root_ && srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;
        output_.Reset(); atlas_.Reset(); pipeline_.Reset(); native_pipeline_.Reset(); root_.Reset(); srv_.Reset(); rtv_.Reset();
        srv_first_reference_.Reset(); srv_second_reference_.Reset(); xr_rtv_reference_.Reset();
        srv_descriptors_valid_=false; srv_cached_format_=DXGI_FORMAT_UNKNOWN;
        xr_rtv_format_=DXGI_FORMAT_UNKNOWN;
        srv_cpu_start_={}; srv_gpu_start_={}; rtv_cpu_start_={}; direct_xr_rtv_cpu_={};
        srv_descriptor_increment_=0;
        queries_.Reset(); timestamps_.Reset(); timing_pending_ = false; gpu_ms_ = -1.f; frequency_ = 0;
        device_ = device; width_ = width; height_ = height; srgb_ = srgb;
        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 2;
        D3D12_ROOT_PARAMETER params[2]{};
        params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[0].DescriptorTable = {1, &range};
        params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        params[1].Constants = {0, 0, sizeof(ShaderConstants) / 4};
        params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_ALL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC desc{2, params, 1, &sampler, D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT};
        ComPtr<ID3DBlob> serialized, errors;
        if (!check(D3D12SerializeRootSignature(&desc, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &errors), "Root signature") ||
            !check(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_)), "Create root signature")) return false;
        // Compile shaders in CI and load DXBC directly. Never invoke HLSL compiler on a live XR frame.
        const auto output_format = srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC graphics{};
        graphics.pRootSignature = root_.Get();
        graphics.VS = {vertex_shader_bytecode, sizeof(vertex_shader_bytecode)};
        graphics.PS = {pixel_shader_bytecode, sizeof(pixel_shader_bytecode)};
        auto& blend = graphics.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        graphics.SampleMask = UINT_MAX;
        graphics.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        graphics.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        graphics.RasterizerState.DepthClipEnable = TRUE;
        graphics.DepthStencilState.DepthEnable = FALSE;
        graphics.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        graphics.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        graphics.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        graphics.NumRenderTargets = 1; graphics.RTVFormats[0] = output_format; graphics.SampleDesc.Count = 1;
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&pipeline_)), "Create raster PSO")) return false;
        graphics.PS = {native_pixel_shader_bytecode, sizeof(native_pixel_shader_bytecode)};
        if (!check(device->CreateGraphicsPipelineState(&graphics, IID_PPV_ARGS(&native_pipeline_)), "Create direct Native raster PSO")) return false;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC texture{};
        texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture.Width = width; texture.Height = height; texture.DepthOrArraySize = 1; texture.MipLevels = 1;
        texture.Format = DXGI_FORMAT_B8G8R8A8_TYPELESS; texture.SampleDesc.Count = 1;
        texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
            D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), "Create output")) return false;
        output_->SetName(L"DuoView::MonoComposite");
        D3D12_RESOURCE_DESC atlas_desc=texture;
        atlas_desc.Width=static_cast<uint64_t>(width)*2;
        atlas_desc.Height=height;
        atlas_desc.Format=srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        atlas_desc.Flags=D3D12_RESOURCE_FLAG_NONE;
        if (!check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&atlas_desc,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&atlas_)),"Create Native gather atlas")) return false;
        atlas_->SetName(L"DuoView::NativeGatherAtlasFallback");
        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 2; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_)), "Create RTV heap")) return false;
        hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE; hd.NumDescriptors = 2;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&srv_)), "Create SRV heap")) return false;
        srv_cpu_start_=srv_->GetCPUDescriptorHandleForHeapStart();
        srv_gpu_start_=srv_->GetGPUDescriptorHandleForHeapStart();
        rtv_cpu_start_=rtv_->GetCPUDescriptorHandleForHeapStart();
        srv_descriptor_increment_=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        direct_xr_rtv_cpu_=rtv_cpu_start_;
        direct_xr_rtv_cpu_.ptr+=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        D3D12_RENDER_TARGET_VIEW_DESC view{}; view.Format = output_format; view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        device->CreateRenderTargetView(output_.Get(), &view, rtv_cpu_start_);
        return true;
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12Resource> output_, source_, atlas_, primary_reference_, secondary_reference_;
    ComPtr<ID3D12Resource> srv_first_reference_, srv_second_reference_, xr_rtv_reference_;
    std::shared_ptr<const void> packet_lifetime_{};
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_, native_pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    D3D12_CPU_DESCRIPTOR_HANDLE srv_cpu_start_{}, rtv_cpu_start_{}, direct_xr_rtv_cpu_{};
    D3D12_GPU_DESCRIPTOR_HANDLE srv_gpu_start_{};
    UINT srv_descriptor_increment_{};
    ComPtr<ID3D12QueryHeap> queries_;
    ComPtr<ID3D12Resource> timestamps_;
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
    bool timing_pending_{}, pending_direct_xr_{}, recorded_commands_{}, last_native_direct_xr_{};
    uint64_t last_native_source_extents_{};
    uint64_t srv_descriptor_refresh_count_{}, xr_rtv_refresh_count_{};
    DXGI_FORMAT srv_cached_format_{DXGI_FORMAT_UNKNOWN}, xr_rtv_format_{DXGI_FORMAT_UNKNOWN};
    bool srv_descriptors_valid_{};
    UINT width_{}, height_{};
    bool srgb_{};
    std::string error_;
};
}

