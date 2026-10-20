#pragma once

#include <d3d12.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include "QuadViewShaderBytecode.hpp"
#include <array>
#include <cmath>
#include <cstring>
#include <memory>
#include <utility>

namespace uevr::quadview::dx12 {

using Microsoft::WRL::ComPtr;

struct alignas(16) ShaderConstants {
    uint32_t eye_and_atlas[4]{};
    uint32_t rectangles[4][4]{};
    float crops[2][4]{};
    float options[4]{};
    float sharpen[4]{};
};
static_assert(sizeof(ShaderConstants) == 144);

// Each instance belongs to one fence-retired OpenXR command slot. Descriptor
// and upload storage cannot be reused until the owning slot's fence retires.
class Compositor {
public:
    Compositor() = default;
    Compositor(const Compositor&) = delete;
    Compositor& operator=(const Compositor&) = delete;
    ~Compositor() { if (constants_ && mapped_) constants_->Unmap(0, nullptr); }

    const char* error() const { return error_; }
    bool prepared() const { return device_ && root_ && pipeline_ && mapped_; }
    bool commands_recorded() const { return recorded_; }

    bool prewarm(ID3D12Device* device, DXGI_FORMAT source_srv_format, DXGI_FORMAT output_format,
                 UINT64 timestamp_frequency = 0) {
        if (!device || source_srv_format == DXGI_FORMAT_UNKNOWN || output_format == DXGI_FORMAT_UNKNOWN)
            return fail("Invalid prewarm device or formats");
        if (owner_) return fail("Cannot recreate an in-flight compositor");
        if (prepared() && device_.Get() == device && source_format_ == source_srv_format && output_format_ == output_format) {
            setup_timing(device,timestamp_frequency);
            return true;
        }
        if (mapped_ && constants_) constants_->Unmap(0, nullptr);
        mapped_ = nullptr;
        constants_.Reset(); root_.Reset(); pipeline_.Reset(); srv_heap_.Reset(); rtv_heap_.Reset();
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f;
        device_ = device;
        source_format_ = source_srv_format;
        output_format_ = output_format;

        D3D12_FEATURE_DATA_FORMAT_SUPPORT source_support{source_srv_format};
        D3D12_FEATURE_DATA_FORMAT_SUPPORT output_support{output_format};
        if (FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &source_support, sizeof(source_support))) ||
            FAILED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &output_support, sizeof(output_support))) ||
            !(source_support.Support1 & D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE) ||
            !(output_support.Support1 & D3D12_FORMAT_SUPPORT1_RENDER_TARGET))
            return fail("Unsupported source sampling or output render-target format");

        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 1;
        D3D12_ROOT_PARAMETER parameters[2]{};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_CBV;
        parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[1].DescriptorTable.NumDescriptorRanges = 1;
        parameters[1].DescriptorTable.pDescriptorRanges = &range;
        parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_STATIC_SAMPLER_DESC sampler{};
        sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        sampler.MaxAnisotropy = 1;
        sampler.MaxLOD = D3D12_FLOAT32_MAX;
        sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        D3D12_ROOT_SIGNATURE_DESC signature{};
        signature.NumParameters = 2;
        signature.pParameters = parameters;
        signature.NumStaticSamplers = 1;
        signature.pStaticSamplers = &sampler;
        signature.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
        ComPtr<ID3DBlob> serialized, diagnostics;
        if (FAILED(D3D12SerializeRootSignature(&signature, D3D_ROOT_SIGNATURE_VERSION_1, &serialized, &diagnostics)) ||
            FAILED(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(), IID_PPV_ARGS(&root_))))
            return fail("Could not create QuadView root signature");

        D3D12_GRAPHICS_PIPELINE_STATE_DESC description{};
        description.pRootSignature = root_.Get();
        description.VS = {shaders::vertex, sizeof(shaders::vertex)};
        description.PS = {shaders::pixel, sizeof(shaders::pixel)};
        auto& blend = description.BlendState.RenderTarget[0];
        blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        description.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        description.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        description.RasterizerState.DepthClipEnable = TRUE;
        description.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        description.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        auto& stencil = description.DepthStencilState.FrontFace;
        stencil.StencilFailOp = stencil.StencilDepthFailOp = stencil.StencilPassOp = D3D12_STENCIL_OP_KEEP;
        stencil.StencilFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        description.DepthStencilState.BackFace = stencil;
        description.SampleMask = UINT32_MAX;
        description.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        description.NumRenderTargets = 1;
        description.RTVFormats[0] = output_format;
        description.SampleDesc.Count = 1;
        if (FAILED(device->CreateGraphicsPipelineState(&description, IID_PPV_ARGS(&pipeline_))))
            return fail("Could not create QuadView raster pipeline");

        D3D12_DESCRIPTOR_HEAP_DESC heap{};
        heap.NumDescriptors = 1;
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&srv_heap_)))) return fail("Could not create QuadView SRV heap");
        heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        heap.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        if (FAILED(device->CreateDescriptorHeap(&heap, IID_PPV_ARGS(&rtv_heap_)))) return fail("Could not create QuadView RTV heap");
        D3D12_HEAP_PROPERTIES upload{};
        upload.Type = D3D12_HEAP_TYPE_UPLOAD;
        upload.CreationNodeMask = upload.VisibleNodeMask = 1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width = 256;
        buffer.Height = buffer.DepthOrArraySize = buffer.MipLevels = 1;
        buffer.SampleDesc.Count = 1;
        buffer.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&upload, D3D12_HEAP_FLAG_NONE, &buffer,
            D3D12_RESOURCE_STATE_GENERIC_READ, nullptr, IID_PPV_ARGS(&constants_)))) return fail("Could not create QuadView constants");
        D3D12_RANGE no_read{0, 0};
        if (FAILED(constants_->Map(0, &no_read, &mapped_))) return fail("Could not map QuadView constants");
        constants_->SetName(L"QuadView slot constants");
        root_->SetName(L"QuadView root signature");
        pipeline_->SetName(L"QuadView stereo raster pipeline");
        srv_heap_->SetName(L"QuadView slot SRV");
        rtv_heap_->SetName(L"QuadView slot RTV");
        setup_timing(device,timestamp_frequency);
        error_ = "";
        return true;
    }

    void on_slot_retired() {
        // Call only after the owning command-context fence proves every query
        // and resource reference in this slot has completed.
        read_timing();
        owner_.reset();
        source_.Reset(); destination_.Reset();
        recorded_ = false;
    }
    float gpu_milliseconds() const { return gpu_ms_; }
    UINT64 timing_frequency() const { return frequency_; }
    bool timing_ready() const { return queries_ && timestamps_ && frequency_; }

    bool record(ID3D12GraphicsCommandList* commands, ID3D12Resource* source, ID3D12Resource* destination,
                const Layout& layout, const Settings& settings,
                D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
                std::shared_ptr<const void> owner, UINT64 timestamp_frequency = 0) {
        recorded_ = false;
        if (!prepared() || !commands || !source || !destination || source == destination || !owner)
            return fail("Unprepared compositor or invalid source/destination ownership");
        if (owner_) return fail("Compositor command slot has not retired");
        if (timing_pending_) return fail("Previous timestamp query has not retired");
        const auto checked_settings = reconcile_settings(settings, settings,
            layout.eye_width,layout.eye_height);
        if (!valid_layout(layout) || checked_settings.rejected || !same_settings(checked_settings.settings, settings))
            return fail("Invalid QuadView layout or debug controls");
        const auto input = source->GetDesc(), output = destination->GetDesc();
        if (input.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || output.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            input.Width != layout.atlas_width || input.Height != layout.atlas_height ||
            output.Width != layout.eye_width * 2ull || output.Height != layout.eye_height ||
            input.SampleDesc.Count != 1 || output.SampleDesc.Count != 1 ||
            input.DepthOrArraySize != 1 || output.DepthOrArraySize != 1 ||
            (input.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) ||
            !(output.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) || !compatible_source(output.Format, output_format_) ||
            !compatible_source(input.Format, source_format_)) return fail("Source or destination texture does not match prepared QuadView layout/formats");

        ShaderConstants constants{};
        constants.eye_and_atlas[0] = layout.eye_width; constants.eye_and_atlas[1] = layout.eye_height;
        constants.eye_and_atlas[2] = layout.atlas_width; constants.eye_and_atlas[3] = layout.atlas_height;
        for (unsigned view = 0; view < 4; ++view) {
            const auto& rect = layout.views[view];
            constants.rectangles[view][0] = rect.x; constants.rectangles[view][1] = rect.y;
            constants.rectangles[view][2] = rect.width; constants.rectangles[view][3] = rect.height;
        }
        for (unsigned eye = 0; eye != 2; ++eye) {
            const auto& crop = layout.focus_crops[eye];
            constants.crops[eye][0] = crop.u0; constants.crops[eye][1] = crop.v0;
            constants.crops[eye][2] = crop.u1; constants.crops[eye][3] = crop.v1;
        }
        constants.options[0] = settings.feather_fraction;
        constants.options[1] = static_cast<float>(settings.diagnostic_view);
        const bool output_srgb = output_format_ == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ||
                                 output_format_ == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        const bool encoded_unorm = source_format_ == DXGI_FORMAT_B8G8R8A8_UNORM ||
                                   source_format_ == DXGI_FORMAT_R8G8B8A8_UNORM;
        constants.options[2] = output_srgb && encoded_unorm ? 1.f : 0.f;
        constants.options[3] = settings.debug_border ? 1.f : 0.f;
        constants.sharpen[0] = settings.sharpen_strength;
        constants.sharpen[1] = 1.f + 2.f + (encoded_unorm ? 4.f : 0.f);
        constants.sharpen[2] = .10f;
        constants.sharpen[3] = .02f;
        std::memcpy(mapped_, &constants, sizeof(constants));
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = source_format_;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Texture2D.MipLevels = 1;
        device_->CreateShaderResourceView(source, &srv, srv_heap_->GetCPUDescriptorHandleForHeapStart());
        D3D12_RENDER_TARGET_VIEW_DESC rtv_description{};
        rtv_description.Format = output_format_;
        rtv_description.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        const auto rtv = rtv_heap_->GetCPUDescriptorHandleForHeapStart();
        device_->CreateRenderTargetView(destination, &rtv_description, rtv);
        owner_ = std::move(owner);
        source_ = source; destination_ = destination;
        barrier(commands, source, source_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
        barrier(commands, destination, destination_state, D3D12_RESOURCE_STATE_RENDER_TARGET);
        commands->SetPipelineState(pipeline_.Get());
        commands->SetGraphicsRootSignature(root_.Get());
        ID3D12DescriptorHeap* heaps[]{srv_heap_.Get()};
        commands->SetDescriptorHeaps(1, heaps);
        commands->SetGraphicsRootConstantBufferView(0, constants_->GetGPUVirtualAddress());
        commands->SetGraphicsRootDescriptorTable(1, srv_heap_->GetGPUDescriptorHandleForHeapStart());
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(layout.eye_width * 2), static_cast<float>(layout.eye_height), 0, 1};
        const D3D12_RECT scissor{0, 0, static_cast<LONG>(layout.eye_width * 2), static_cast<LONG>(layout.eye_height)};
        commands->RSSetViewports(1, &viewport);
        commands->RSSetScissorRects(1, &scissor);
        commands->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        commands->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        const bool timed=settings.gpu_timing && timestamp_frequency &&
            timestamp_frequency==frequency_ && timing_ready();
        if (timed) commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0);
        commands->DrawInstanced(3, 1, 0, 0);
        if (timed) {
            commands->EndQuery(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,1);
            commands->ResolveQueryData(queries_.Get(),D3D12_QUERY_TYPE_TIMESTAMP,0,2,timestamps_.Get(),0);
            timing_pending_=true;
        }
        barrier(commands, source, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, source_state);
        barrier(commands, destination, D3D12_RESOURCE_STATE_RENDER_TARGET, destination_state);
        recorded_ = true;
        error_ = "";
        return true;
    }

private:
    bool fail(const char* message) { error_ = message; return false; }
    void read_timing() {
        if (!timing_pending_ || !timestamps_ || !frequency_) return;
        gpu_ms_=-1.f;
        D3D12_RANGE range{0,sizeof(UINT64)*2};
        UINT64* values{};
        if (SUCCEEDED(timestamps_->Map(0,&range,reinterpret_cast<void**>(&values)))) {
            if (values[1]>=values[0])
                gpu_ms_=static_cast<float>(double(values[1]-values[0])*1000.0/double(frequency_));
            D3D12_RANGE no_write{0,0};
            timestamps_->Unmap(0,&no_write);
        }
        timing_pending_=false;
    }
    void setup_timing(ID3D12Device* device, UINT64 frequency) {
        if (!device || !frequency || (queries_ && timestamps_ && frequency_==frequency)) return;
        queries_.Reset(); timestamps_.Reset(); frequency_=0; timing_pending_=false; gpu_ms_=-1.f;
        D3D12_QUERY_HEAP_DESC query{};
        query.Type=D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        query.Count=2;
        if (FAILED(device->CreateQueryHeap(&query,IID_PPV_ARGS(&queries_)))) return;
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type=D3D12_HEAP_TYPE_READBACK;
        heap.CreationNodeMask=heap.VisibleNodeMask=1;
        D3D12_RESOURCE_DESC buffer{};
        buffer.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer.Width=sizeof(UINT64)*2;
        buffer.Height=buffer.DepthOrArraySize=buffer.MipLevels=1;
        buffer.SampleDesc.Count=1;
        buffer.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&buffer,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&timestamps_)))) {
            queries_.Reset();
            return;
        }
        frequency_=frequency;
        queries_->SetName(L"QuadView slot timestamp queries");
        timestamps_->SetName(L"QuadView slot timestamp readback");
    }
    static bool compatible_source(DXGI_FORMAT resource, DXGI_FORMAT view) {
        if (resource == view) return true;
        if (resource == DXGI_FORMAT_R8G8B8A8_TYPELESS) return view == DXGI_FORMAT_R8G8B8A8_UNORM || view == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_B8G8R8A8_TYPELESS) return view == DXGI_FORMAT_B8G8R8A8_UNORM || view == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
        if (resource == DXGI_FORMAT_R10G10B10A2_TYPELESS) return view == DXGI_FORMAT_R10G10B10A2_UNORM;
        if (resource == DXGI_FORMAT_R16G16B16A16_TYPELESS) return view == DXGI_FORMAT_R16G16B16A16_FLOAT;
        return false;
    }
    static bool valid_layout(const Layout& layout) {
        if (!layout.eye_width || !layout.eye_height || layout.eye_width > 8192 || layout.eye_height > 8192 ||
            layout.atlas_width != layout.eye_width * 2 || layout.atlas_height != layout.eye_height) return false;
        for (const auto& c : layout.focus_crops) {
            if (!(std::isfinite(c.u0) && std::isfinite(c.v0) && std::isfinite(c.u1) && std::isfinite(c.v1)) ||
                c.u0 < 0.f || c.v0 < 0.f || c.u1 > 1.f || c.v1 > 1.f || c.u1 <= c.u0 || c.v1 <= c.v0) return false;
        }
        for (unsigned i = 0; i < 4; ++i) {
            const auto& rect = layout.views[i];
            if (!rect.width || !rect.height || uint64_t(rect.x) + rect.width > layout.atlas_width ||
                uint64_t(rect.y) + rect.height > layout.atlas_height) return false;
            for (unsigned j = 0; j < i; ++j) {
                const auto& other = layout.views[j];
                if (uint64_t(rect.x) < uint64_t(other.x) + other.width && uint64_t(other.x) < uint64_t(rect.x) + rect.width &&
                    uint64_t(rect.y) < uint64_t(other.y) + other.height && uint64_t(other.y) < uint64_t(rect.y) + rect.height) return false;
            }
        }
        return true;
    }
    static void barrier(ID3D12GraphicsCommandList* commands, ID3D12Resource* resource,
                         D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
        if (before == after) return;
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition.pResource = resource;
        barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        barrier.Transition.StateBefore = before; barrier.Transition.StateAfter = after;
        commands->ResourceBarrier(1, &barrier);
    }
    ComPtr<ID3D12Device> device_;
    ComPtr<ID3D12RootSignature> root_;
    ComPtr<ID3D12PipelineState> pipeline_;
    ComPtr<ID3D12DescriptorHeap> srv_heap_, rtv_heap_;
    ComPtr<ID3D12Resource> constants_, source_, destination_, timestamps_;
    ComPtr<ID3D12QueryHeap> queries_;
    void* mapped_{};
    std::shared_ptr<const void> owner_;
    DXGI_FORMAT source_format_{DXGI_FORMAT_UNKNOWN}, output_format_{DXGI_FORMAT_UNKNOWN};
    const char* error_{"Compositor not prewarmed"};
    bool recorded_{};
    bool timing_pending_{};
    UINT64 frequency_{};
    float gpu_ms_{-1.f};
};

} // namespace uevr::quadview::dx12
