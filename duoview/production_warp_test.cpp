#include <windows.h>
#include "DuoViewD3D12.hpp"
#include <dxgi1_6.h>
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
    if (!compositor.prewarm(device.Get(),32,32,false,frequency)) throw std::runtime_error("Timing prewarm failed");
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
    std::cout << "Production shader, BGRA8 raster, moved gaze, retired-slot reuse, GPU timestamps: 2048 exact pixel pairs PASS\n";
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n';return 1; }
