#pragma once
// Stage 9 — safe single-width BGRA8 Mono image -> OpenXR double-wide copy.
// This is purpose-built for DuoView's full-FOV *composited* image.
// It does not alter Joey's original MonoD3D12::copy_scene contract.
// Call from the existing OpenXR DX12 copy command-list callback, after the
// compositor completes on the SAME queue or a properly waited dependency.
// Own both source/output resources until the swapchain consumer fence retires.
#include <cstdint>
#include <d3d12.h>
#include <wrl/client.h>
#include <utility>

namespace uevr::duoview::dx12 {

inline bool bgra8(DXGI_FORMAT f) {
    return f==DXGI_FORMAT_B8G8R8A8_UNORM ||
           f==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
           f==DXGI_FORMAT_B8G8R8A8_TYPELESS;
}

inline bool stereo_destination_valid(const D3D12_RESOURCE_DESC& d, UINT64 eye_width, UINT height) {
    return eye_width && eye_width<=16384 && height &&
        d.Dimension==D3D12_RESOURCE_DIMENSION_TEXTURE2D &&
        d.Width==eye_width*2 && d.Height==height &&
        d.DepthOrArraySize==1 && d.MipLevels==1 &&
        d.SampleDesc.Count==1 && d.SampleDesc.Quality==0 &&
        bgra8(d.Format) && (d.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
}

inline bool copy_composite_to_stereo(ID3D12GraphicsCommandList* cmd,
                                    ID3D12Device* device,
                                    ID3D12Resource* mono_composite,
                                    ID3D12Resource* openxr_doublewide,
                                    D3D12_RESOURCE_STATES mono_state,
                                    D3D12_RESOURCE_STATES destination_state) {
    if(!cmd || !device || !mono_composite || !openxr_doublewide ||
       mono_composite==openxr_doublewide ||
       cmd->GetType()!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
       FAILED(device->GetDeviceRemovedReason())) return false;

    const auto s=mono_composite->GetDesc();
    const auto d=openxr_doublewide->GetDesc();
    if(s.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
       s.DepthOrArraySize!=1 || s.MipLevels!=1 ||
       s.SampleDesc.Count!=1 || s.SampleDesc.Quality!=0 ||
       !bgra8(s.Format) || !(s.Flags&D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
       !stereo_destination_valid(d,s.Width,s.Height)) return false;

    Microsoft::WRL::ComPtr<ID3D12Device> sd,dd,cd;
    if(FAILED(mono_composite->GetDevice(IID_PPV_ARGS(&sd))) ||
       FAILED(openxr_doublewide->GetDevice(IID_PPV_ARGS(&dd))) ||
       FAILED(cmd->GetDevice(IID_PPV_ARGS(&cd))) ||
       sd.Get()!=device || dd.Get()!=device || cd.Get()!=device) return false;

    D3D12_RESOURCE_BARRIER transitions[2]{};
    UINT count=0;
    auto add_barrier=[&](ID3D12Resource* r,D3D12_RESOURCE_STATES before,
                         D3D12_RESOURCE_STATES after) {
        if(before==after) return;
        auto& b=transitions[count++];
        b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};
    };
    add_barrier(mono_composite,mono_state,D3D12_RESOURCE_STATE_COPY_SOURCE);
    add_barrier(openxr_doublewide,destination_state,D3D12_RESOURCE_STATE_COPY_DEST);
    if(count) cmd->ResourceBarrier(count,transitions);

    const D3D12_TEXTURE_COPY_LOCATION from{mono_composite,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    const D3D12_TEXTURE_COPY_LOCATION to{openxr_doublewide,D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX,{0}};
    const UINT w=static_cast<UINT>(s.Width);
    const D3D12_BOX box{0,0,0,w,s.Height,1};
    cmd->CopyTextureRegion(&to,0,0,0,&from,&box);
    cmd->CopyTextureRegion(&to,w,0,0,&from,&box);

    for(UINT i=0;i<count;++i) {
        std::swap(transitions[i].Transition.StateBefore,
                  transitions[i].Transition.StateAfter);
    }
    if(count) cmd->ResourceBarrier(count,transitions);
    return true;
}
} // namespace uevr::duoview::dx12
