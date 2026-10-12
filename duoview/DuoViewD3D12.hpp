#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewMonoCopyD3D12.hpp"
#include "DuoViewShaderSource.hpp"
#include <d3dcompiler.h>
#include <cstring>
#include <string>
#ifdef _MSC_VER
#pragma comment(lib, "d3dcompiler.lib")
#endif

namespace uevr::duoview::dx12 {
using Microsoft::WRL::ComPtr;
struct ShaderConstants {
    uint32_t output[2], atlas[2], fovea[4], periphery[4];
    float crop[4], feather;
    uint32_t border;
    float reserved[2];
};
static_assert(sizeof(ShaderConstants) == 80);

class Compositor {
public:
    // One instance per retired OpenXR command slot; descriptors/resources must
    // stay alive until that slot's GPU fence completes.
    bool record(ID3D12Device* device, ID3D12GraphicsCommandList* cmd,
                ID3D12Resource* atlas, ID3D12Resource* destination,
                D3D12_RESOURCE_STATES atlas_state, const FrameConfig& frame) {
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
        ShaderConstants constants{
            {l.atlas_width / 2, l.atlas_height}, {l.atlas_width, l.atlas_height},
            {l.fovea.x, l.fovea.y, l.fovea.width, l.fovea.height},
            {l.periphery.x, l.periphery.y, l.periphery.width, l.periphery.height},
            {l.u0, l.v0, l.u1, l.v1}, frame.settings.feather_fraction,
            frame.settings.debug_border ? 1u : 0u, {0, 0}};
        D3D12_SHADER_RESOURCE_VIEW_DESC view{};
        view.Format = format;
        view.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        view.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        view.Texture2D.MipLevels = 1;
        device->CreateShaderResourceView(atlas, &view, srv_->GetCPUDescriptorHandleForHeapStart());
        source_ = atlas;
        transition(cmd, atlas, atlas_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        cmd->BeginEvent(0, "DuoView::Composite", 18);
        ID3D12DescriptorHeap* heaps[]{srv_.Get()};
        cmd->SetDescriptorHeaps(1, heaps);
        cmd->SetGraphicsRootSignature(root_.Get());
        cmd->SetPipelineState(pipeline_.Get());
        cmd->SetGraphicsRootDescriptorTable(0, srv_->GetGPUDescriptorHandleForHeapStart());
        cmd->SetGraphicsRoot32BitConstants(1, sizeof(constants) / 4, &constants, 0);
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(width_), static_cast<float>(height_), 0, 1};
        const D3D12_RECT rect{0, 0, static_cast<LONG>(width_), static_cast<LONG>(height_)};
        cmd->RSSetViewports(1, &viewport);
        cmd->RSSetScissorRects(1, &rect);
        const auto handle = rtv_->GetCPUDescriptorHandleForHeapStart();
        cmd->OMSetRenderTargets(1, &handle, FALSE, nullptr);
        cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        cmd->DrawInstanced(3, 1, 0, 0);
        cmd->EndEvent();
        transition(cmd, atlas, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, atlas_state);
        return copy_composite_to_stereo(cmd, device, output_.Get(), destination,
            D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_RENDER_TARGET);
    }
    const std::string& error() const { return error_; }
private:
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
    bool check(HRESULT hr, const char* operation) {
        if (SUCCEEDED(hr)) return true;
        error_ = std::string(operation) + " HRESULT " + std::to_string(static_cast<uint32_t>(hr));
        return false;
    }
    bool compile(ComPtr<ID3DBlob>& blob, const char* entry, const char* profile) {
        ComPtr<ID3DBlob> errors;
        const auto hr = D3DCompile(shader_source, std::strlen(shader_source), "DuoViewCompositeRaster.hlsl",
            nullptr, nullptr, entry, profile, D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &blob, &errors);
        if (FAILED(hr) && errors) error_.assign(static_cast<const char*>(errors->GetBufferPointer()), errors->GetBufferSize());
        return SUCCEEDED(hr);
    }
    bool prepare(ID3D12Device* device, UINT width, UINT height, bool srgb) {
        if (device_.Get() == device && output_ && pipeline_ && root_ && srv_ && rtv_ && width == width_ && height == height_ && srgb == srgb_) return true;
        output_.Reset(); pipeline_.Reset(); root_.Reset(); srv_.Reset(); rtv_.Reset();
        device_ = device; width_ = width; height_ = height; srgb_ = srgb;
        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 1;
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
        ComPtr<ID3DBlob> vertex, pixel;
        if (!compile(vertex, "VSMain", "vs_5_0") || !compile(pixel, "PSMain", "ps_5_0")) return false;
        const auto output_format = srgb ? DXGI_FORMAT_B8G8R8A8_UNORM_SRGB : DXGI_FORMAT_B8G8R8A8_UNORM;
        D3D12_GRAPHICS_PIPELINE_STATE_DESC graphics{};
        graphics.pRootSignature = root_.Get();
        graphics.VS = {vertex->GetBufferPointer(), vertex->GetBufferSize()};
        graphics.PS = {pixel->GetBufferPointer(), pixel->GetBufferSize()};
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
        D3D12_HEAP_PROPERTIES heap{}; heap.Type = D3D12_HEAP_TYPE_DEFAULT; heap.CreationNodeMask = heap.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC texture{};
        texture.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        texture.Width = width; texture.Height = height; texture.DepthOrArraySize = 1; texture.MipLevels = 1;
        texture.Format = DXGI_FORMAT_B8G8R8A8_TYPELESS; texture.SampleDesc.Count = 1;
        texture.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
        if (!check(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &texture,
            D3D12_RESOURCE_STATE_RENDER_TARGET, nullptr, IID_PPV_ARGS(&output_)), "Create output")) return false;
        output_->SetName(L"DuoView::MonoComposite");
        D3D12_DESCRIPTOR_HEAP_DESC hd{}; hd.NumDescriptors = 1; hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&rtv_)), "Create RTV heap")) return false;
        hd.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV; hd.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (!check(device->CreateDescriptorHeap(&hd, IID_PPV_ARGS(&srv_)), "Create SRV heap")) return false;
        D3D12_RENDER_TARGET_VIEW_DESC view{}; view.Format = output_format; view.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        device->CreateRenderTargetView(output_.Get(), &view, rtv_->GetCPUDescriptorHandleForHeapStart());
        return true;
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12Resource> output_, source_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_, rtv_;
    UINT width_{}, height_{};
    bool srgb_{};
    std::string error_;
};
}
