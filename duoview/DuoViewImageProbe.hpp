#pragma once
// Deferred DX12 pixel evidence. Called only after a retired OpenXR command slot
// has become ready again; never map GPU memory while it may still be in use.
#include "DuoViewDiagnostic.hpp"
#include <d3d12.h>
#include <wrl/client.h>
#include <array>
#include <cstring>

namespace uevr::duoview::diag {
class ImageProbe {
public:
    // Record at a small set of deterministic source frames, with NO GPU stalls.
    void harvest() {
        if (!pending_ || !readback_) return;
        const D3D12_RANGE read_range{0, static_cast<SIZE_T>(kMaxBytes)};
        uint8_t* ptr=nullptr;
        if (SUCCEEDED(readback_->Map(0,&read_range,reinterpret_cast<void**>(&ptr))) && ptr) {
            for(int i=0;i<3;++i) {
                const auto& t=tiles_[i];
                if (!t.valid) continue;
                ImageRecord out{};
                out.frame=pending_frame_;out.qpc=pending_qpc_;
                out.width=kSize;out.height=kSize;out.row_pitch=t.row_pitch;
                out.format=t.format;out.stage=3;out.tile=static_cast<uint32_t>(i);
                out.u=pending_u_;out.v=pending_v_;
                out.raw.resize(static_cast<size_t>(t.row_pitch)*kSize);
                std::memcpy(out.raw.data(),ptr+t.offset,out.raw.size());
                Recorder::get().gpu(std::move(out));
            }
            const D3D12_RANGE no_write{0,0};readback_->Unmap(0,&no_write);
        }
        pending_=false;
    }
    void schedule(ID3D12Device* device,ID3D12GraphicsCommandList* cmd,
                  ID3D12Resource* atlas,ID3D12Resource* composite,
                  const FrameConfig& frame) {
        if (!device || !cmd || !atlas || !composite || pending_) return;
        const uint64_t n=Recorder::get().sequence(frame.key.frame);
        if (!(n==80 || n==125 || n==145 || n==190 || n==245 ||
              n==280 || n==335 || n==365 || n==405 || n==495 ||
              n==510 || n==530)) return;
        const auto ad=atlas->GetDesc(),cd=composite->GetDesc();
        const UINT abpp=bytes_per_pixel(ad.Format);
        if (!abpp || !bytes_per_pixel(cd.Format) ||
            ad.Width<kSize || ad.Height<kSize ||
            cd.Width<kSize || cd.Height<kSize) return;
        if (!readback_) {
            D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_READBACK;
            heap.CreationNodeMask=heap.VisibleNodeMask=1;
            D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
            d.Width=kMaxBytes;d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;
            d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
            if(FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
                    D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&readback_))))return;
        }
        const auto& l=frame.layout;
        // Source regions are the center of the dedicated fovea and periphery
        // atlas rectangles. Composite is sampled at a FIXED screen-space patch,
        // enabling frame-to-frame comparison at one world region.
        const auto center=[](uint32_t start,uint32_t size)->UINT {
            return static_cast<UINT>(start + (size>kSize?(size-kSize)/2:0));
        };
        const UINT f_x=center(l.fovea.x,l.fovea.width),
                   f_y=center(l.fovea.y,l.fovea.height);
        const UINT p_x=center(l.periphery.x,l.periphery.width),
                   p_y=center(l.periphery.y,l.periphery.height);
        const UINT c_x=static_cast<UINT>((cd.Width-kSize)/2),
                   c_y=static_cast<UINT>((cd.Height-kSize)/2);
        if(l.fovea.width<kSize||l.fovea.height<kSize||
           l.periphery.width<kSize||l.periphery.height<kSize)return;
        D3D12_RESOURCE_BARRIER b[2]{};
        auto transition=[&](int idx,ID3D12Resource* res,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
            b[idx].Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            b[idx].Transition={res,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,from,to};
        };
        transition(0,atlas,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE,D3D12_RESOURCE_STATE_COPY_SOURCE);
        transition(1,composite,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
        cmd->ResourceBarrier(2,b);
        tiles_={};
        capture(cmd,0,atlas,ad.Format,abpp,f_x,f_y,0);
        capture(cmd,1,atlas,ad.Format,abpp,p_x,p_y,kChunk);
        capture(cmd,2,composite,cd.Format,bytes_per_pixel(cd.Format),c_x,c_y,2*kChunk);
        transition(0,atlas,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        transition(1,composite,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
        cmd->ResourceBarrier(2,b);
        pending_frame_=frame.key.frame;pending_u_=frame.gaze.u;pending_v_=frame.gaze.v;
        LARGE_INTEGER q{};QueryPerformanceCounter(&q);pending_qpc_=static_cast<uint64_t>(q.QuadPart);
        pending_=true;
    }
private:
    static constexpr uint32_t kSize=128,kChunk=131072,kMaxBytes=3*kChunk;
    struct Tile { uint32_t row_pitch{},format{},offset{};bool valid{}; };
    static UINT bytes_per_pixel(DXGI_FORMAT f){
        switch(f) {
            case DXGI_FORMAT_R16G16B16A16_FLOAT:
            case DXGI_FORMAT_R16G16B16A16_UNORM:return 8;
            case DXGI_FORMAT_R8G8B8A8_UNORM:
            case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
            case DXGI_FORMAT_R8G8B8A8_TYPELESS:
            case DXGI_FORMAT_B8G8R8A8_UNORM:
            case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
            case DXGI_FORMAT_B8G8R8A8_TYPELESS:
            case DXGI_FORMAT_R10G10B10A2_UNORM:return 4;
            default:return 0;
        }
    }
    void capture(ID3D12GraphicsCommandList* cmd,int tile,ID3D12Resource* texture,
                 DXGI_FORMAT fmt,UINT bpp,UINT x,UINT y,UINT offset){
        if (!bpp || bpp*kSize*kSize>kChunk) return;
        const UINT rowpitch=bpp*kSize; // 512 or 1024: aligned to 256 bytes
        D3D12_TEXTURE_COPY_LOCATION dest{};
        dest.pResource=readback_.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        dest.PlacedFootprint.Offset=offset;
        dest.PlacedFootprint.Footprint={fmt,kSize,kSize,1,rowpitch};
        D3D12_TEXTURE_COPY_LOCATION src{};
        src.pResource=texture;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;src.SubresourceIndex=0;
        const D3D12_BOX box{x,y,0,x+kSize,y+kSize,1};
        cmd->CopyTextureRegion(&dest,0,0,0,&src,&box);
        tiles_[tile]={rowpitch,static_cast<uint32_t>(fmt),offset,true};
    }
    Microsoft::WRL::ComPtr<ID3D12Resource> readback_;
    std::array<Tile,3> tiles_{};
    uint64_t pending_frame_{},pending_qpc_{};
    float pending_u_{},pending_v_{};
    bool pending_{};
};
} // namespace uevr::duoview::diag
