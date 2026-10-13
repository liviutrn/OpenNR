#pragma once
#include "DuoViewMonoCopyD3D12.hpp"
namespace uevr::duoview::dx12 {
inline bool copy_owned_image(ID3D12GraphicsCommandList* cmd, ID3D12Device* device,
    ID3D12Resource* source, ID3D12Resource* destination, D3D12_RESOURCE_STATES src_state) {
    if (!cmd || !device || !source || !destination || source==destination) return false;
    const auto s=source->GetDesc(),d=destination->GetDesc();
    if (s.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || d.Dimension!=s.Dimension ||
        s.Width!=d.Width || s.Height!=d.Height || s.DepthOrArraySize!=1 || d.DepthOrArraySize!=1 ||
        s.MipLevels!=1 || d.MipLevels!=1 || s.SampleDesc.Count!=1 || d.SampleDesc.Count!=1 ||
        !bgra8(s.Format) || !bgra8(d.Format)) return false;
    ComPtr<ID3D12Device> sd,dd;
    if (FAILED(source->GetDevice(IID_PPV_ARGS(&sd))) || FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) ||
        sd.Get()!=device || dd.Get()!=device) return false;
    D3D12_RESOURCE_BARRIER barriers[2]{}; UINT count{};
    auto barrier=[&](ID3D12Resource* r,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
        if (before==after) return;
        auto& b=barriers[count++]; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        b.Transition={r,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};
    };
    barrier(source,src_state,D3D12_RESOURCE_STATE_COPY_SOURCE);
    barrier(destination,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_DEST);
    if (count) cmd->ResourceBarrier(count,barriers);
    cmd->CopyResource(destination,source);
    for(UINT i=0;i<count;++i) std::swap(barriers[i].Transition.StateBefore,barriers[i].Transition.StateAfter);
    if (count) cmd->ResourceBarrier(count,barriers);
    return true;
}
}
