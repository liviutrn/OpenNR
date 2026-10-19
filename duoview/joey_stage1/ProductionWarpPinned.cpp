#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <array>
#include <cstring>
#include <memory>
#include <vector>
#include <iostream>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
static void check(HRESULT h) { if (FAILED(h)) throw std::runtime_error("D3D12 failure " + std::to_string(static_cast<uint32_t>(h))); }
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES h{}; h.Type=type; h.CreationNodeMask=h.VisibleNodeMask=1; return h;
}
static D3D12_RESOURCE_DESC texture(UINT w, UINT h, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=w; d.Height=h; d.DepthOrArraySize=d.MipLevels=1; d.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    d.SampleDesc.Count=1; d.Flags=flags; return d;
}
static D3D12_RESOURCE_DESC buffer(UINT64 size) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    d.Width=size; d.Height=d.DepthOrArraySize=d.MipLevels=1;
    d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR; return d;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* device, D3D12_RESOURCE_DESC desc,
    D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    auto hp=heap(type); ComPtr<ID3D12Resource> r;
    check(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r))); return r;
}
static void transition(ID3D12GraphicsCommandList* cmd, ID3D12Resource* r, D3D12_RESOURCE_STATES a,D3D12_RESOURCE_STATES b) {
    D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,a,b};cmd->ResourceBarrier(1,&barrier);
}
struct NativeSource {
    ComPtr<ID3D12Resource> texture;
    ComPtr<ID3D12Resource> upload;
};
static NativeSource native_source(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                                  UINT width, UINT height, std::array<uint8_t,4> bgra,
                                  bool gradient = false, UINT gradient_offset = 0,
                                  DXGI_FORMAT resource_format = DXGI_FORMAT_B8G8R8A8_TYPELESS) {
    auto desc=texture(width,height,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    desc.Format=resource_format;
    NativeSource result;
    result.texture=resource(device,desc,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&bytes);
    footprint.Footprint.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
    result.upload=resource(device,buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped{};D3D12_RANGE zero{0,0};check(result.upload->Map(0,&zero,&mapped));
    std::memset(mapped,0,bytes);
    for(UINT y=0;y<height;++y) for(UINT x=0;x<width;++x) {
        auto pixel=bgra;
        if (gradient) {
            pixel={static_cast<uint8_t>((x*17+gradient_offset*11)&255),
                   static_cast<uint8_t>((y*23+gradient_offset*7)&255),
                   static_cast<uint8_t>((x*3+y*5+gradient_offset*13)&255),255};
        }
        std::memcpy(static_cast<uint8_t*>(mapped)+y*footprint.Footprint.RowPitch+x*4,pixel.data(),4);
    }
    result.upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{result.upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    from.PlacedFootprint=footprint;
    D3D12_TEXTURE_COPY_LOCATION to{result.texture.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(cmd,result.texture.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    return result;
}
int main() try {
    // Exercise the actual copied Joey compositor with D3D12 validation on WARP.
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))
        debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> cmd;check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)));
    auto atlas=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto stereo=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
    auto bad=resource(device.Get(),texture(64,32,D3D12_RESOURCE_FLAG_NONE),D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COMMON);
    const auto desc=atlas->GetDesc();D3D12_PLACED_SUBRESOURCE_FOOTPRINT foot{};UINT64 bytes{};
    device->GetCopyableFootprints(&desc,0,1,0,&foot,nullptr,nullptr,&bytes);
    auto upload=resource(device.Get(),buffer(bytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback=resource(device.Get(),buffer(bytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    auto layout=uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.5f,.5f);
    if (!layout) throw std::runtime_error("Invalid test layout");
    void* mapped{};D3D12_RANGE zero{0,0};check(upload->Map(0,&zero,&mapped));std::memset(mapped,0,bytes);
    auto fill=[&](uevr::duoview::Rect r,std::array<uint8_t,4> bgra) {
        for(UINT y=r.y;y<r.y+r.height;++y) for(UINT x=r.x;x<r.x+r.width;++x)
            std::memcpy(static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4,bgra.data(),4);
    };
    fill(layout->fovea,{0,0,255,255}); fill(layout->periphery,{255,0,0,255});upload->Unmap(0,nullptr);
    D3D12_TEXTURE_COPY_LOCATION from{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};from.PlacedFootprint=foot;
    D3D12_TEXTURE_COPY_LOCATION to{atlas.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    uevr::duoview::FrameConfig frame{{1,1},*layout,{.5f,.5f},{},1};frame.settings.feather_fraction=.12f;
    uevr::duoview::dx12::Compositor compositor;
    UINT64 frequency{};check(queue->GetTimestampFrequency(&frequency));
    if (!compositor.prewarm(device.Get(),32,32,false,frequency))
        throw std::runtime_error("DX12 startup prewarm failed");
    if (compositor.record(device.Get(),cmd.Get(),atlas.Get(),bad.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame)) throw std::runtime_error("Invalid destination accepted");
    if (compositor.recorded_commands()) throw std::runtime_error("Rejected input recorded GPU commands");
    if (!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency)) throw std::runtime_error(compositor.error());
    const auto stable_mono_srv_refreshes=compositor.srv_descriptor_refresh_count();
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    from={stereo.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};to={readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};to.PlacedFootprint=foot;
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);check(cmd->Close());
    ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);
    ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));check(queue->Signal(fence.Get(),1));
    auto event=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(fence->SetEventOnCompletion(1,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("GPU timeout");CloseHandle(event);
    D3D12_RANGE read{0,static_cast<size_t>(bytes)};check(readback->Map(0,&read,&mapped));
    auto sample=[&](UINT x,UINT y) { return static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4; };
    if(sample(16,16)[2]<240 || sample(1,1)[0]<240 || sample(8,16)[2]<5 || sample(8,16)[2]>250) throw std::runtime_error("Production compositor pixels wrong");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4)) throw std::runtime_error("Mono stereo-copy mismatch");
    readback->Unmap(0,nullptr);
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    frame.key.frame=2;frame.gaze={.75f,.5f};frame.layout=*uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.75f,.5f);
    if (!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency)) throw std::runtime_error(compositor.error());
    if (compositor.srv_descriptor_refresh_count()!=stable_mono_srv_refreshes)
        throw std::runtime_error("Stable compatibility atlas SRVs were rewritten");
    if (compositor.gpu_milliseconds()<0.f) throw std::runtime_error("Completed GPU timestamps missing");
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);check(cmd->Close());queue->ExecuteCommandLists(1,lists);check(queue->Signal(fence.Get(),2));
    event=CreateEventW(nullptr,FALSE,FALSE,nullptr);check(fence->SetEventOnCompletion(2,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("Second GPU timeout");CloseHandle(event);
    check(readback->Map(0,&read,&mapped));
    if(sample(24,16)[2]<240 || sample(8,16)[0]<240) throw std::runtime_error("Moved gaze crop pixels wrong");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4)) throw std::runtime_error("Reused mono copy mismatch");
    readback->Unmap(0,nullptr);
    // Real production raster path: isolate EACH independent UE source view.
    // The same GPU output must still be copied identically into both XR eyes.
    for (unsigned mode : {1u,2u}) {
        check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        frame.key.frame=2+mode; frame.settings.diagnostic_view=mode;
        if (!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,frame,frequency))
            throw std::runtime_error("Diagnostic mode rejected: "+compositor.error());
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        check(cmd->Close());queue->ExecuteCommandLists(1,lists);
        const UINT64 signal=2+mode;
        check(queue->Signal(fence.Get(),signal));
        event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        check(fence->SetEventOnCompletion(signal,event));
        if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
            throw std::runtime_error("Diagnostic GPU fence timeout");
        CloseHandle(event);
        check(readback->Map(0,&read,&mapped));
        if(mode==1) {
            // Periphery-only must remain blue EVERYWHERE, including foveal ROI.
            if(sample(24,16)[0]<240 || sample(24,16)[2]>20 ||
               sample(8,16)[0]<240 || sample(8,16)[2]>20)
                throw std::runtime_error("Periphery-isolation pixels wrong");
        } else {
            // Fovea-only must show red in ROI and a dark sentinel OUTSIDE.
            if(sample(24,16)[2]<240 || sample(24,16)[0]>20 ||
               sample(8,16)[0]>24 || sample(8,16)[2]>24)
                throw std::runtime_error("Fovea-isolation pixels wrong");
        }
        for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
            if(std::memcmp(sample(x,y),sample(x+32,y),4))
                throw std::runtime_error("Diagnostic eye-copy pixel mismatch");
        readback->Unmap(0,nullptr);
    }
    // Exercise the actual Native Fix gather path, including its frozen source
    // selection and prewarmed sRGB interpretation. Source textures model Joey's
    // typeless primary/secondary BGRA targets; the composed Mono image must be
    // identical when the selected fovea comes from either UE source view.
    ComPtr<ID3D12InfoQueue> info_queue;
    if (SUCCEEDED(device.As(&info_queue))) info_queue->ClearStoredMessages();
    UINT64 native_signal=10;
    for (bool srgb : {false,true}) for (uint32_t fovea_view : {0u,1u}) {
        check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        const auto native_layout=uevr::duoview::make_layout(32,32,.50f,.50f,.25f,1.f,.5f,.5f);
        if(!native_layout) throw std::runtime_error("Invalid Native test layout");
        const auto primary_color=fovea_view==0 ? std::array<uint8_t,4>{0,0,255,255} : std::array<uint8_t,4>{255,0,0,255};
        const auto secondary_color=fovea_view==1 ? std::array<uint8_t,4>{0,0,255,255} : std::array<uint8_t,4>{255,0,0,255};
        const bool gradient=!srgb && fovea_view==0;
        auto primary=native_source(device.Get(),cmd.Get(),32,32,primary_color,gradient,0);
        auto secondary=native_source(device.Get(),cmd.Get(),32,32,secondary_color,gradient,1);
        uevr::duoview::ViewFrame native_frame{};
        native_frame.config={{1,20+static_cast<uint64_t>(srgb)*2+fovea_view},*native_layout,{.5f,.5f},{},1};
        native_frame.config.settings.fovea_view=fovea_view;
        native_frame.config.settings.direct_xr_output=true;
        if(!compositor.prewarm(device.Get(),32,32,srgb,frequency))
            throw std::runtime_error("Native prewarm color interpretation rejected");
        if(compositor.record_native(device.Get(),cmd.Get(),primary.texture.Get(),secondary.texture.Get(),
                bad.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                native_frame,std::make_shared<const int>(6),0) || compositor.recorded_commands())
            throw std::runtime_error("Invalid Native destination recorded GPU commands");
        if(compositor.record_native_gather(device.Get(),cmd.Get(),primary.texture.Get(),secondary.texture.Get(),
                bad.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                native_frame,std::make_shared<const int>(6),0) || compositor.recorded_commands())
            throw std::runtime_error("Invalid gather destination recorded GPU commands");
        if(!compositor.record_native(device.Get(),cmd.Get(),primary.texture.Get(),secondary.texture.Get(),
                stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
                native_frame,std::make_shared<const int>(7),frequency))
            throw std::runtime_error("Native primary/secondary gather or composite failed: "+compositor.error());
        // Typed UNORM XR should use direct doublewide raster. An incompatible
        // sRGB RTV must preserve the original composite+copy pathway instead.
        if (compositor.last_native_direct_xr() == srgb)
            throw std::runtime_error("Incorrect direct-XR route selection for output format");
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);check(cmd->Close());
        ID3D12CommandList* native_lists[]{cmd.Get()};queue->ExecuteCommandLists(1,native_lists);
        const UINT64 signal=++native_signal;
        check(queue->Signal(fence.Get(),signal));event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        check(fence->SetEventOnCompletion(signal,event));
        if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)throw std::runtime_error("Native gather GPU timeout");CloseHandle(event);
        check(readback->Map(0,&read,&mapped));
        if (!gradient && (sample(16,16)[2]<220 || sample(16,16)[0]>25 ||
           sample(1,1)[0]<220 || sample(1,1)[2]>25))
            throw std::runtime_error("Native fovea/periphery source mapping or sRGB pixels wrong");
        if (gradient && std::memcmp(sample(3,3),sample(4,3),4)==0)
            throw std::runtime_error("Direct-XR gradient source was not spatially sampled");
        for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
            if(std::memcmp(sample(x,y),sample(x+32,y),4))
                throw std::runtime_error("Native combined Mono image differed between eyes");
        std::vector<uint8_t> direct_pixels;
        if (gradient) {
            direct_pixels.resize(static_cast<size_t>(64)*32*4);
            for (UINT y=0;y<32;++y)
                std::memcpy(direct_pixels.data()+static_cast<size_t>(y)*64*4,
                    sample(0,y),static_cast<size_t>(64)*4);
        }
        readback->Unmap(0,nullptr);
        if (gradient) {
            // Hold target format and sources fixed for direct/copy route equality.
            check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
            auto fallback_desc=texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
            fallback_desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
            native_frame.config.settings.direct_xr_output=false;
            auto fallback_output=resource(device.Get(),fallback_desc,
                D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
            if(!compositor.record_native(device.Get(),cmd.Get(),primary.texture.Get(),secondary.texture.Get(),
                    fallback_output.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                    D3D12_RESOURCE_STATE_RENDER_TARGET,native_frame,
                    std::make_shared<const int>(9),frequency))
                throw std::runtime_error("Forced copy output failed: "+compositor.error());
            if(compositor.gpu_milliseconds()>=0.f)
                throw std::runtime_error("Route switch reused old GPU timing");
            if(compositor.last_native_direct_xr())
                throw std::runtime_error("Disabled direct-XR option selected raster route");
            transition(cmd.Get(),fallback_output.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION fallback_from{
                fallback_output.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
            D3D12_TEXTURE_COPY_LOCATION fallback_to{
                readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            fallback_to.PlacedFootprint=foot;
            cmd->CopyTextureRegion(&fallback_to,0,0,0,&fallback_from,nullptr);
            check(cmd->Close());queue->ExecuteCommandLists(1,native_lists);
            const UINT64 signal=++native_signal;
            check(queue->Signal(fence.Get(),signal));
            event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
            check(fence->SetEventOnCompletion(signal,event));
            if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
                throw std::runtime_error("Forced copy output GPU fence timeout");
            CloseHandle(event);
            check(readback->Map(0,&read,&mapped));
            for (UINT y=0;y<32;++y) for (UINT x=0;x<64;++x) {
                const auto* expected=direct_pixels.data()+(static_cast<size_t>(y)*64+x)*4;
                if(std::memcmp(sample(x,y),expected,4))
                    throw std::runtime_error("Direct-XR output differed from compatibility copy pixels");
            }
            readback->Unmap(0,nullptr);

            native_frame.config.settings.direct_xr_output=true;
            // The same fenced-slot resources and descriptors should be
            // reusable without rewriting SRVs/RTVs on the next frames.
            const auto stable_srv_refreshes=compositor.srv_descriptor_refresh_count();
            const auto stable_rtv_refreshes=compositor.xr_rtv_refresh_count();
            for (int repeat=0;repeat<2;++repeat) {
                check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
                transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,
                    D3D12_RESOURCE_STATE_RENDER_TARGET);
                if(!compositor.record_native(device.Get(),cmd.Get(),primary.texture.Get(),
                        secondary.texture.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                        D3D12_RESOURCE_STATE_RENDER_TARGET,native_frame,
                        std::make_shared<const int>(10+repeat),0))
                    throw std::runtime_error("Cached Native descriptor reuse failed: "+compositor.error());
                if(compositor.gpu_milliseconds()>=0.f)
                    throw std::runtime_error("Disabled GPU timing retained an old sample");
                if(compositor.srv_descriptor_refresh_count()!=stable_srv_refreshes ||
                   compositor.xr_rtv_refresh_count()!=stable_rtv_refreshes)
                    throw std::runtime_error("Stable Native source/XR descriptors were rewritten");
                transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                    D3D12_RESOURCE_STATE_COPY_SOURCE);
                check(cmd->Close());queue->ExecuteCommandLists(1,native_lists);
                const UINT64 stable_signal=++native_signal;
                check(queue->Signal(fence.Get(),stable_signal));event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
                check(fence->SetEventOnCompletion(stable_signal,event));
                if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
                    throw std::runtime_error("Cached Native descriptor reuse fence timeout");
                CloseHandle(event);
            }

            // A new XR texture changes only the slot RTV descriptor. Source
            // SRVs remain valid for the same Native pair and sampling format.
            check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
            auto alternate_xr=resource(device.Get(),
                texture(64,32,D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
                D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_RENDER_TARGET);
            if(!compositor.record_native(device.Get(),cmd.Get(),primary.texture.Get(),
                    secondary.texture.Get(),alternate_xr.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
                    D3D12_RESOURCE_STATE_RENDER_TARGET,native_frame,
                    std::make_shared<const int>(12),0))
                throw std::runtime_error("Changed XR target descriptor refresh failed: "+compositor.error());
            if(compositor.srv_descriptor_refresh_count()!=stable_srv_refreshes ||
               compositor.xr_rtv_refresh_count()!=stable_rtv_refreshes+1)
                throw std::runtime_error("Changed XR target refreshed the wrong descriptor set");
            check(cmd->Close());queue->ExecuteCommandLists(1,native_lists);
            const UINT64 changed_target_signal=++native_signal;
            check(queue->Signal(fence.Get(),changed_target_signal));event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
            check(fence->SetEventOnCompletion(changed_target_signal,event));
            if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
                throw std::runtime_error("Changed XR target descriptor fence timeout");
            CloseHandle(event);
        }
    }
    // A typed Native source that cannot use the prewarmed sampling format must
    // continue through the gather/copy fallback, with cached atlas SRVs.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET);
    const auto fallback_layout=uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.5f,.5f);
    if(!fallback_layout) throw std::runtime_error("Invalid gather fallback layout");
    auto incompatible_primary=native_source(device.Get(),cmd.Get(),32,32,{0,0,255,255},false,0,
        DXGI_FORMAT_B8G8R8A8_UNORM);
    auto fallback_secondary=native_source(device.Get(),cmd.Get(),32,32,{255,0,0,255});
    ID3D12CommandList* gather_lists[]{cmd.Get()};
    uevr::duoview::ViewFrame fallback_frame{};
    fallback_frame.config={{1,29},*fallback_layout,{.5f,.5f},{},1};
    fallback_frame.config.settings.fovea_view=0;
    if(!compositor.record_native(device.Get(),cmd.Get(),incompatible_primary.texture.Get(),
            fallback_secondary.texture.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
            D3D12_RESOURCE_STATE_RENDER_TARGET,fallback_frame,
            std::make_shared<const int>(29),0) || compositor.last_native_direct_xr())
        throw std::runtime_error("Typed Native source mismatch did not use the gather fallback: "+compositor.error());
    const auto gathered_srv_refreshes=compositor.srv_descriptor_refresh_count();
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION gathered_from{stereo.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    D3D12_TEXTURE_COPY_LOCATION gathered_to{readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    gathered_to.PlacedFootprint=foot;
    cmd->CopyTextureRegion(&gathered_to,0,0,0,&gathered_from,nullptr);check(cmd->Close());
    queue->ExecuteCommandLists(1,gather_lists);
    const UINT64 gather_signal=++native_signal;
    check(queue->Signal(fence.Get(),gather_signal));event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    check(fence->SetEventOnCompletion(gather_signal,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
        throw std::runtime_error("Native gather fallback fence timeout");
    CloseHandle(event);
    check(readback->Map(0,&read,&mapped));
    if(sample(16,16)[2]<220 || sample(16,16)[0]>25 ||
       sample(1,1)[0]<220 || sample(1,1)[2]>25)
        throw std::runtime_error("Native gather fallback pixels differ from direct sampling");
    for(UINT y=0;y<32;++y) for(UINT x=0;x<32;++x)
        if(std::memcmp(sample(x,y),sample(x+32,y),4))
            throw std::runtime_error("Native gather fallback eye-copy mismatch");
    readback->Unmap(0,nullptr);
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET);
    if(!compositor.record_native(device.Get(),cmd.Get(),incompatible_primary.texture.Get(),
            fallback_secondary.texture.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,
            D3D12_RESOURCE_STATE_RENDER_TARGET,fallback_frame,
            std::make_shared<const int>(30),0) ||
       compositor.srv_descriptor_refresh_count()!=gathered_srv_refreshes)
        throw std::runtime_error("Repeated Native gather rewrote its cached atlas descriptors: "+compositor.error());
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    check(cmd->Close());queue->ExecuteCommandLists(1,gather_lists);
    const UINT64 gather_repeat_signal=++native_signal;
    check(queue->Signal(fence.Get(),gather_repeat_signal));event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    check(fence->SetEventOnCompletion(gather_repeat_signal,event));
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
        throw std::runtime_error("Repeated Native gather cache fence timeout");
    CloseHandle(event);

    // A layout can request a fovea larger than Joey's single-eye capture. The
    // production path must reject it before recording any GPU commands.
    check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
    transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    auto undersized_source=native_source(device.Get(),cmd.Get(),8,8,{0,0,255,255});
    auto complete_source=native_source(device.Get(),cmd.Get(),32,32,{255,0,0,255});
    auto oversized_layout=uevr::duoview::make_layout(32,32,.75f,.25f,.25f,2.f,.5f,.5f);
    if(!oversized_layout) throw std::runtime_error("Invalid oversized Native test layout");
    uevr::duoview::ViewFrame oversized{};
    oversized.config={{1,30},*oversized_layout,{.5f,.5f},{},1};
    oversized.config.settings.fovea_view=0;
    if(compositor.record_native(device.Get(),cmd.Get(),undersized_source.texture.Get(),complete_source.texture.Get(),
            stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET,
            oversized,std::make_shared<const int>(8),frequency) || compositor.recorded_commands())
        throw std::runtime_error("Native source smaller than selected rectangle was accepted/recorded");
    if(info_queue) {
        for(UINT64 i=0;i<info_queue->GetNumStoredMessages();++i) {
            SIZE_T size{};check(info_queue->GetMessage(i,nullptr,&size));
            std::vector<uint8_t> bytes(size);
            auto* message=reinterpret_cast<D3D12_MESSAGE*>(bytes.data());
            check(info_queue->GetMessage(i,message,&size));
            if(message->Severity==D3D12_MESSAGE_SEVERITY_ERROR ||
               message->Severity==D3D12_MESSAGE_SEVERITY_CORRUPTION)
                throw std::runtime_error(std::string("D3D12 WARP validation: ")+message->pDescription);
        }
    }

    std::cout << "Production raster and Native gather: direct/fallback pixels, cached descriptors, UNORM/sRGB, and source bounds PASS\n";
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }

