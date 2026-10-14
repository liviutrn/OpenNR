#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
#include <d3d12sdklayers.h>
#include <array>
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
    // Legacy offsets must not shift the production color raster.
    check(upload->Map(0,&zero,&mapped));std::memset(mapped,0,bytes);
    for(UINT y=0;y<32;++y) for(UINT x=0;x<16;++x) {
        auto* pixel=static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4;
        pixel[0]=0;pixel[1]=0;pixel[2]=static_cast<uint8_t>(x*16);pixel[3]=255;
    }
    for(UINT y=0;y<32;++y) for(UINT x=16;x<24;++x) {
        auto* pixel=static_cast<uint8_t*>(mapped)+y*foot.Footprint.RowPitch+x*4;
        pixel[0]=255;pixel[1]=0;pixel[2]=0;pixel[3]=255;
    }
    upload->Unmap(0,nullptr);
    frame.layout=*uevr::duoview::make_layout(32,32,.5f,.5f,.25f,1.f,.5f,.5f);
    frame.settings.diagnostic_view=2; // Fovea only
    uint8_t base_red=0, shift_red=0;
    for (int pass=0;pass<2;++pass) {
        check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        if(pass==0) {
            transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_TEXTURE_COPY_LOCATION a_dest{atlas.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
            D3D12_TEXTURE_COPY_LOCATION a_upload{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            a_upload.PlacedFootprint=foot;
            cmd->CopyTextureRegion(&a_dest,0,0,0,&a_upload,nullptr);
            transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
        }
        frame.key.frame=10+pass;
        frame.history_sample_offset={pass==0 ? 0.f : .125f,0.f};
        if(!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),
                D3D12_RESOURCE_STATE_RENDER_TARGET,frame))
            throw std::runtime_error("Cheeky correction raster record failed: "+compositor.error());
        transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
        check(cmd->Close());queue->ExecuteCommandLists(1,lists);
        const UINT64 signal=5+pass;check(queue->Signal(fence.Get(),signal));
        event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        check(fence->SetEventOnCompletion(signal,event));
        if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
            throw std::runtime_error("Cheeky correction GPU fence timeout");
        CloseHandle(event);
        check(readback->Map(0,&read,&mapped));
        const auto red=sample(16,16)[2];
        if(pass==0) base_red=red;else shift_red=red;
        if(sample(16,16)[0]>20 || sample(1,1)[2]>20)
            throw std::runtime_error("Gradient shader sampled wrong atlas region");
        if(std::memcmp(sample(16,16),sample(48,16),4))
            throw std::runtime_error("History correction broke mono stereo-copy parity");
        readback->Unmap(0,nullptr);
    }
    if(shift_red != base_red)
        throw std::runtime_error("Legacy crop-motion input displaced current color");
    UINT64 world_signal=7;
    for (float extent : {.3f,.5f}) for (float density : {1.f,1.5f,2.5f}) {
        for (float gaze_u : {.5f,.625f,.45f}) {
            const auto moving=uevr::duoview::make_layout(32,32,extent,extent,.25f,density,gaze_u,.5f);
            if (!moving) continue;
            frame.layout=*moving;
            frame.key.frame++;
            frame.settings.diagnostic_view=0;
            frame.history_sample_offset={.125f,-.125f};
            check(upload->Map(0,&zero,&mapped));
            std::memset(mapped,0,bytes);
            const auto encode_world=[&](uevr::duoview::Rect r,bool foveal) {
                for(UINT y=0;y<r.height;++y) for(UINT x=0;x<r.width;++x) {
                    const float u=(x+.5f)/r.width;
                    const float v=(y+.5f)/r.height;
                    const float full_u=foveal ? moving->u0+u*extent : u;
                    const float full_v=foveal ? moving->v0+v*extent : v;
                    auto* pixel=static_cast<uint8_t*>(mapped)+
                        (y+r.y)*foot.Footprint.RowPitch+(x+r.x)*4;
                    pixel[0]=0;
                    pixel[1]=static_cast<uint8_t>(std::lround(32.f+160.f*full_v));
                    pixel[2]=static_cast<uint8_t>(std::lround(32.f+160.f*full_u));
                    pixel[3]=255;
                }
            };
            encode_world(moving->fovea,true);
            encode_world(moving->periphery,false);
            upload->Unmap(0,nullptr);
            check(allocator->Reset());check(cmd->Reset(allocator.Get(),nullptr));
            transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
            transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_DEST);
            D3D12_TEXTURE_COPY_LOCATION destination{atlas.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
            D3D12_TEXTURE_COPY_LOCATION source{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
            source.PlacedFootprint=foot;
            cmd->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
            transition(cmd.Get(),atlas.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
            if(!compositor.record(device.Get(),cmd.Get(),atlas.Get(),stereo.Get(),
                    D3D12_RESOURCE_STATE_RENDER_TARGET,frame))
                throw std::runtime_error("Moving-world raster record failed: "+compositor.error());
            transition(cmd.Get(),stereo.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
            cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
            check(cmd->Close());queue->ExecuteCommandLists(1,lists);
            check(queue->Signal(fence.Get(),world_signal));
            event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
            check(fence->SetEventOnCompletion(world_signal++,event));
            if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0)
                throw std::runtime_error("Moving-world GPU fence timeout");
            CloseHandle(event);
            check(readback->Map(0,&read,&mapped));
            for(UINT y=15;y<=17;++y) for(UINT x=16;x<=18;++x) {
                const auto* pixel=sample(x,y);
                const auto red=std::lround(32.+160.*(x+.5)/32.);
                const auto green=std::lround(32.+160.*(y+.5)/32.);
                if(std::abs(int(pixel[2])-int(red))>2 ||
                   std::abs(int(pixel[1])-int(green))>2)
                    throw std::runtime_error("Moving fovea displaced a stationary world pattern");
                if(std::memcmp(pixel,sample(x+32,y),4))
                    throw std::runtime_error("Moving-world stereo-copy mismatch");
            }
            readback->Unmap(0,nullptr);
        }
    }
    std::cout << "Production normal/moved gaze/diagnostics and world-aligned WARP gradient raster PASS\n";
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
