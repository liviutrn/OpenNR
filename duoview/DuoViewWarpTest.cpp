// Windows DX12 WARP integration test: actually execute DuoViewComposite.hlsl.
// Standalone offscreen shader test, not an injected UEVR renderer.
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <vector>
using Microsoft::WRL::ComPtr;
static void check(HRESULT h, const char* what) {
    if (FAILED(h)) throw std::runtime_error(std::string(what)+" HRESULT "+std::to_string(static_cast<unsigned long>(h)));
}
static D3D12_RESOURCE_DESC texture(uint64_t w,uint32_t h,D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=w; d.Height=h; d.DepthOrArraySize=1; d.MipLevels=1;
    d.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
    d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_UNKNOWN; d.Flags=flags;
    return d;
}
static D3D12_RESOURCE_DESC buffer(uint64_t bytes) {
    D3D12_RESOURCE_DESC d{};
    d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;d.Width=bytes;
    d.Height=1;d.DepthOrArraySize=1;d.MipLevels=1;
    d.SampleDesc.Count=1;d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return d;
}
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES h{}; h.Type=type;h.CreationNodeMask=1;h.VisibleNodeMask=1;return h;
}
static ComPtr<ID3D12Resource> resource(ID3D12Device* d,const D3D12_RESOURCE_DESC& desc,
                                      D3D12_HEAP_TYPE ht,D3D12_RESOURCE_STATES state) {
    ComPtr<ID3D12Resource> r; auto h=heap(ht);
    check(d->CreateCommittedResource(&h,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&r)),"CreateCommittedResource");
    return r;
}
static void barrier(ID3D12GraphicsCommandList* cmd,ID3D12Resource* r,
                    D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource=r; b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore=from;b.Transition.StateAfter=to;cmd->ResourceBarrier(1,&b);
}
struct alignas(16) Config {
    uint32_t output[2],atlas[2];
    uint32_t fovea[4],periphery[4];
    float crop[4];
    float feather;
    uint32_t debug;
    float reserved[2];
};
static_assert(sizeof(Config)==80);
int main() try {
    constexpr uint32_t W=32,H=32,AW=64,AH=32;
    ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"CreateDXGIFactory");
    ComPtr<IDXGIAdapter> warp;check(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"EnumWarpAdapter");
    ComPtr<ID3D12Device> device;
    check(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"CreateDevice");
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"CreateCommandQueue");
    ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"Allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;
    check(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)),"CommandList");
    auto input=resource(device.Get(),texture(AW,AH,D3D12_RESOURCE_FLAG_NONE),
                        D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_COPY_DEST);
    auto output=resource(device.Get(),texture(W,H,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS),
                         D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT srcfoot{},dstfoot{};
    uint64_t srcbytes=0,dstbytes=0;
    const auto srcdesc=input->GetDesc(),dstdesc=output->GetDesc();
    device->GetCopyableFootprints(&srcdesc,0,1,0,&srcfoot,nullptr,nullptr,&srcbytes);
    device->GetCopyableFootprints(&dstdesc,0,1,0,&dstfoot,nullptr,nullptr,&dstbytes);
    auto upload=resource(device.Get(),buffer(srcbytes),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback=resource(device.Get(),buffer(dstbytes),D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    auto constants=resource(device.Get(),buffer(256),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ);
    uint8_t* ptr=nullptr;
    D3D12_RANGE zero{0,0};
    check(upload->Map(0,&zero,reinterpret_cast<void**>(&ptr)),"Map upload");
    std::memset(ptr,0,static_cast<size_t>(srcbytes));
    // Peripheral region x=[16,24), y=[0,8), opaque blue;
    // Fovea x=[0,16), y=[0,16), opaque red.
    for(uint32_t y=0;y<AH;++y)for(uint32_t x=0;x<AW;++x){
        auto* pixel=ptr+y*srcfoot.Footprint.RowPitch+x*4;
        pixel[0]=x<16&&y<16?255:0;pixel[1]=0;
        pixel[2]=x>=16&&x<24&&y<8?255:0;pixel[3]=255;
    }
    upload->Unmap(0,nullptr);
    Config config{};
    config.output[0]=W;config.output[1]=H;config.atlas[0]=AW;config.atlas[1]=AH;
    config.fovea[0]=0;config.fovea[1]=0;config.fovea[2]=16;config.fovea[3]=16;
    config.periphery[0]=16;config.periphery[1]=0;config.periphery[2]=8;config.periphery[3]=8;
    config.crop[0]=.25f;config.crop[1]=.25f;config.crop[2]=.75f;config.crop[3]=.75f;
    config.feather=.12f;
    void* cptr=nullptr;
    check(constants->Map(0,&zero,&cptr),"Map constants");
    std::memcpy(cptr,&config,sizeof(config));
    constants->Unmap(0,nullptr);

    D3D12_DESCRIPTOR_HEAP_DESC heapdesc{};
    heapdesc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;heapdesc.NumDescriptors=2;
    heapdesc.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> descriptors;
    check(device->CreateDescriptorHeap(&heapdesc,IID_PPV_ARGS(&descriptors)),"Shader descriptor heap");
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format=DXGI_FORMAT_R8G8B8A8_UNORM;srv.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
    srv.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Texture2D.MipLevels=1;
    auto cpu=descriptors->GetCPUDescriptorHandleForHeapStart();
    device->CreateShaderResourceView(input.Get(),&srv,cpu);
    auto increment=device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
    cpu.ptr+=increment;
    D3D12_UNORDERED_ACCESS_VIEW_DESC uav{};
    uav.Format=DXGI_FORMAT_R8G8B8A8_UNORM;
    uav.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;
    device->CreateUnorderedAccessView(output.Get(),nullptr,&uav,cpu);

    D3D12_DESCRIPTOR_RANGE ranges[2]{};
    for(int i=0;i<2;++i) {
        ranges[i].RangeType=i==0?D3D12_DESCRIPTOR_RANGE_TYPE_SRV:D3D12_DESCRIPTOR_RANGE_TYPE_UAV;
        ranges[i].NumDescriptors=1;ranges[i].BaseShaderRegister=0;
        ranges[i].OffsetInDescriptorsFromTableStart=D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;
    }
    D3D12_ROOT_PARAMETER params[3]{};
    for(int i=0;i<2;++i){
        params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        params[i].DescriptorTable.NumDescriptorRanges=1;
        params[i].DescriptorTable.pDescriptorRanges=&ranges[i];
        params[i].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
    }
    params[2].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[2].Descriptor.ShaderRegister=0;
    params[2].ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
    D3D12_STATIC_SAMPLER_DESC sampler{};
    sampler.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;
    sampler.AddressU=sampler.AddressV=sampler.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.MaxLOD=D3D12_FLOAT32_MAX;
    sampler.ShaderRegister=0;sampler.ShaderVisibility=D3D12_SHADER_VISIBILITY_ALL;
    D3D12_ROOT_SIGNATURE_DESC rootdesc{};
    rootdesc.NumParameters=3;rootdesc.pParameters=params;
    rootdesc.NumStaticSamplers=1;rootdesc.pStaticSamplers=&sampler;
    rootdesc.Flags=D3D12_ROOT_SIGNATURE_FLAG_NONE;
    ComPtr<ID3DBlob> rootblob,errors;
    const auto hr=D3D12SerializeRootSignature(&rootdesc,D3D_ROOT_SIGNATURE_VERSION_1,
                                              &rootblob,&errors);
    if(FAILED(hr)&&errors) std::cerr<<static_cast<const char*>(errors->GetBufferPointer())<<"\n";
    check(hr,"SerializeRootSignature");
    ComPtr<ID3D12RootSignature> rootsig;
    check(device->CreateRootSignature(0,rootblob->GetBufferPointer(),rootblob->GetBufferSize(),
                                     IID_PPV_ARGS(&rootsig)),"RootSignature");
    std::ifstream in("DuoViewComposite.cso",std::ios::binary);
    if(!in) throw std::runtime_error("DuoViewComposite.cso missing");
    std::vector<char> shader((std::istreambuf_iterator<char>(in)),{});
    if(shader.empty())throw std::runtime_error("Empty compositor CSO");
    D3D12_COMPUTE_PIPELINE_STATE_DESC pso{};
    pso.pRootSignature=rootsig.Get();pso.CS={shader.data(),shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;
    check(device->CreateComputePipelineState(&pso,IID_PPV_ARGS(&pipeline)),"Compute PSO");

    D3D12_TEXTURE_COPY_LOCATION dst{input.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    dst.SubresourceIndex=0;
    D3D12_TEXTURE_COPY_LOCATION src{upload.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    src.PlacedFootprint=srcfoot;
    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    barrier(cmd.Get(),input.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
    ID3D12DescriptorHeap* shaderheaps[]{descriptors.Get()};
    cmd->SetDescriptorHeaps(1,shaderheaps);
    cmd->SetComputeRootSignature(rootsig.Get());
    cmd->SetPipelineState(pipeline.Get());
    auto gpu=descriptors->GetGPUDescriptorHandleForHeapStart();
    cmd->SetComputeRootDescriptorTable(0,gpu);
    gpu.ptr+=increment;
    cmd->SetComputeRootDescriptorTable(1,gpu);
    cmd->SetComputeRootConstantBufferView(2,constants->GetGPUVirtualAddress());
    cmd->Dispatch((W+7)/8,(H+7)/8,1);
    barrier(cmd.Get(),output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION from{output.Get(),D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX};
    from.SubresourceIndex=0;
    D3D12_TEXTURE_COPY_LOCATION to{readback.Get(),D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT};
    to.PlacedFootprint=dstfoot;
    cmd->CopyTextureRegion(&to,0,0,0,&from,nullptr);
    check(cmd->Close(),"Close command list");
    ID3D12CommandList* lists[]{cmd.Get()};
    queue->ExecuteCommandLists(1,lists);
    ComPtr<ID3D12Fence> fence;
    check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"Fence");
    check(queue->Signal(fence.Get(),1),"Signal");
    HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    if(!event)throw std::runtime_error("CreateEvent failed");
    check(fence->SetEventOnCompletion(1,event),"SetEvent");
    if(WaitForSingleObject(event,30000)!=WAIT_OBJECT_0) {
        CloseHandle(event);throw std::runtime_error("WARP fence timeout");
    }
    CloseHandle(event);
    uint8_t* result=nullptr;D3D12_RANGE read{0,static_cast<size_t>(dstbytes)};
    check(readback->Map(0,&read,reinterpret_cast<void**>(&result)),"Map readback");
    auto sample=[&](uint32_t x,uint32_t y) {
        std::array<int,3> rgb{};
        for(int i=0;i<3;++i)rgb[i]=result[y*dstfoot.Footprint.RowPitch+x*4+i];
        return rgb;
    };
    auto center=sample(16,16),corner=sample(1,1),seam=sample(8,16);
    std::cout<<"WARP real shader pixels: center=["<<center[0]<<","<<center[1]<<","<<center[2]
             <<"] corner=["<<corner[0]<<","<<corner[1]<<","<<corner[2]
             <<"] seam=["<<seam[0]<<","<<seam[1]<<","<<seam[2]<<"]\n";
    readback->Unmap(0,nullptr);
    if(!(center[0]>230&&center[2]<25&&corner[0]<25&&corner[2]>230 &&
         seam[0]>5&&seam[0]<250&&seam[2]>5&&seam[2]<250)) {
        throw std::runtime_error("WARP compositor: central, peripheral or feathered-edge pixels wrong");
    }
    std::cout<<"DuoView DX12 WARP dispatch + GPU fence + readback assertions PASSED\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<"DuoView WARP test FAILED: "<<e.what()<<"\n";return 1;}
