#pragma once

#include <array>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <optional>
#include <string_view>
#include <utility>

#include <d3d12.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include <spdlog/spdlog.h>

#include "DuoViewRestartDiagnostics.hpp"

namespace uevr::duoview_restart::dx12 {

using Microsoft::WRL::ComPtr;

enum class Mode : uint8_t { disabled, fixed, step, ramp, alternating, invalid };

struct RecordResult {
    bool command_recorded{};
    FallbackReason reason{FallbackReason::none};
};

inline constexpr uint32_t descriptor_capacity = 16;
inline constexpr uint32_t device_capacity = 2;
inline constexpr uint32_t replay_period_frames = 90;
inline constexpr float peripheral_sample_scale = 4.0f;

inline Mode requested_mode() noexcept {
    static const Mode mode = [] {
        const char* raw = std::getenv("UEVR_STABLE_SOURCE_MASK");
        if (raw == nullptr || *raw == '\0' || std::strcmp(raw, "off") == 0) { return Mode::disabled; }
        const std::string_view value{raw};
        if (value == "fixed") { return Mode::fixed; }
        if (value == "step") { return Mode::step; }
        if (value == "ramp") { return Mode::ramp; }
        if (value == "alternating") { return Mode::alternating; }
        return Mode::invalid;
    }();
    return mode;
}

inline bool diagnostics_enabled() noexcept {
    static const bool enabled = [] {
        const char* raw = std::getenv("UEVR_DUOVIEW_DIAGNOSTICS");
        return raw != nullptr && std::strcmp(raw, "1") == 0;
    }();
    return enabled;
}

inline const char* mode_name(Mode mode) noexcept {
    switch (mode) {
    case Mode::disabled: return "disabled";
    case Mode::fixed: return "stable_source_moving_mask_fixed";
    case Mode::step: return "stable_source_moving_mask_step";
    case Mode::ramp: return "stable_source_moving_mask_ramp";
    case Mode::alternating: return "stable_source_moving_mask_alternating";
    case Mode::invalid: return "invalid";
    }
    return "invalid";
}

inline ReplayPattern replay_pattern(Mode mode) noexcept {
    switch (mode) {
    case Mode::fixed: return ReplayPattern::fixed;
    case Mode::step: return ReplayPattern::step;
    case Mode::ramp: return ReplayPattern::ramp;
    case Mode::alternating: return ReplayPattern::alternating;
    default: return ReplayPattern::fixed;
    }
}

inline const char* reason_name(FallbackReason reason) noexcept {
    switch (reason) {
    case FallbackReason::none: return "none";
    case FallbackReason::mode_not_mono: return "mode_not_mono";
    case FallbackReason::diagnostic_disabled: return "diagnostic_disabled";
    case FallbackReason::unsupported_device_or_queue: return "unsupported_device_or_queue";
    case FallbackReason::invalid_extent_or_format: return "invalid_extent_or_format";
    case FallbackReason::unsupported_color_view_format: return "unsupported_color_view_format";
    case FallbackReason::shader_resource_denied: return "shader_resource_denied";
    case FallbackReason::descriptor_slot_limit: return "descriptor_slot_limit";
    case FallbackReason::pipeline_unavailable: return "pipeline_unavailable";
    case FallbackReason::warmup_frame: return "warmup_frame";
    case FallbackReason::invalid_diagnostic_configuration: return "invalid_diagnostic_configuration";
    case FallbackReason::submission_not_accepted: return "copy_submission_not_accepted";
    case FallbackReason::source_frame_unavailable: return "source_frame_unavailable";
    case FallbackReason::source_or_destination_state_unavailable: return "source_or_destination_state_unavailable";
    case FallbackReason::command_context_unavailable: return "command_context_unavailable";
    case FallbackReason::command_context_not_retired: return "command_context_not_retired";
    case FallbackReason::producer_callback_not_invoked: return "producer_callback_not_invoked";
    case FallbackReason::no_copy_command_recorded: return "no_copy_command_recorded";
    case FallbackReason::independent_view_state_unproven: return "independent_view_state_unproven";
    }
    return "unknown_reason";
}

inline DXGI_FORMAT view_format(DXGI_FORMAT format) noexcept {
    switch (format) {
    case DXGI_FORMAT_B8G8R8A8_UNORM:
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
        return format;
    default:
        return DXGI_FORMAT_UNKNOWN;
    }
}

struct TargetSlot {
    ComPtr<ID3D12Fence> command_fence;
    uint32_t descriptor_index{};
};

struct DeviceState {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12RootSignature> root_signature;
    std::array<ComPtr<ID3D12PipelineState>, 2> pipelines{};
    ComPtr<ID3D12DescriptorHeap> shader_heap;
    ComPtr<ID3D12DescriptorHeap> render_target_heap;
    UINT shader_descriptor_size{};
    UINT rtv_descriptor_size{};
    uint32_t next_descriptor{};
    std::array<TargetSlot, descriptor_capacity> targets{};
    bool initialization_attempted{};
    bool ready{};
    bool srgb_supported{};
    bool unorm_supported{};

    bool initialize(ID3D12Device* requested_device) {
        initialization_attempted = true;
        device = requested_device;
        D3D12_DESCRIPTOR_HEAP_DESC shader_heap_desc{};
        shader_heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
        shader_heap_desc.NumDescriptors = descriptor_capacity;
        shader_heap_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
        if (FAILED(device->CreateDescriptorHeap(&shader_heap_desc, IID_PPV_ARGS(&shader_heap)))) { return false; }
        D3D12_DESCRIPTOR_HEAP_DESC rtv_heap_desc{};
        rtv_heap_desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
        rtv_heap_desc.NumDescriptors = descriptor_capacity;
        rtv_heap_desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
        if (FAILED(device->CreateDescriptorHeap(&rtv_heap_desc, IID_PPV_ARGS(&render_target_heap)))) { return false; }
        shader_descriptor_size = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV);
        rtv_descriptor_size = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
        unorm_supported = format_supported(DXGI_FORMAT_B8G8R8A8_UNORM);
        srgb_supported = format_supported(DXGI_FORMAT_B8G8R8A8_UNORM_SRGB);
        if (shader_descriptor_size == 0 || rtv_descriptor_size == 0 || !create_pipeline()) { return false; }
        shader_heap->SetName(L"UEVR Stable Source Mask SRV Heap");
        render_target_heap->SetName(L"UEVR Stable Source Mask RTV Heap");
        root_signature->SetName(L"UEVR Stable Source Mask Root Signature");
        for (auto& pso : pipelines) { if (pso) { pso->SetName(L"UEVR Stable Source Mask PSO"); } }
        return true;
    }

    bool format_supported(DXGI_FORMAT format) {
        D3D12_FEATURE_DATA_FORMAT_SUPPORT support{format};
        return SUCCEEDED(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &support, sizeof(support))) &&
            (support.Support1 & D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE) &&
            (support.Support1 & D3D12_FORMAT_SUPPORT1_RENDER_TARGET);
    }

    ID3D12PipelineState* pipeline_for(DXGI_FORMAT format) const noexcept {
        return pipelines[format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ? 1 : 0].Get();
    }

    bool create_pipeline() {
        D3D12_DESCRIPTOR_RANGE range{};
        range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV;
        range.NumDescriptors = 1;
        range.BaseShaderRegister = 0;
        range.OffsetInDescriptorsFromTableStart = D3D12_DESCRIPTOR_RANGE_OFFSET_APPEND;

        std::array<D3D12_ROOT_PARAMETER, 2> parameters{};
        parameters[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
        parameters[0].DescriptorTable.NumDescriptorRanges = 1;
        parameters[0].DescriptorTable.pDescriptorRanges = &range;
        parameters[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        parameters[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
        parameters[1].Constants.ShaderRegister = 0;
        parameters[1].Constants.RegisterSpace = 0;
        parameters[1].Constants.Num32BitValues = 8;
        parameters[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;

        std::array<D3D12_STATIC_SAMPLER_DESC, 2> samplers{};
        for (std::size_t i = 0; i != samplers.size(); ++i) {
            auto& sampler = samplers[i];
            sampler.Filter = i == 0 ? D3D12_FILTER_MIN_MAG_MIP_LINEAR : D3D12_FILTER_MIN_MAG_MIP_POINT;
            sampler.AddressU = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.AddressV = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
            sampler.MipLODBias = 0.f;
            sampler.MaxAnisotropy = 1;
            sampler.ComparisonFunc = D3D12_COMPARISON_FUNC_NEVER;
            sampler.BorderColor = D3D12_STATIC_BORDER_COLOR_TRANSPARENT_BLACK;
            sampler.MinLOD = 0.f;
            sampler.MaxLOD = D3D12_FLOAT32_MAX;
            sampler.ShaderRegister = i;
            sampler.RegisterSpace = 0;
            sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
        }

        D3D12_ROOT_SIGNATURE_DESC root_desc{};
        root_desc.NumParameters = static_cast<UINT>(parameters.size());
        root_desc.pParameters = parameters.data();
        root_desc.NumStaticSamplers = static_cast<UINT>(samplers.size());
        root_desc.pStaticSamplers = samplers.data();
        root_desc.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
        ComPtr<ID3DBlob> root_bytes, errors;
        if (FAILED(D3D12SerializeRootSignature(&root_desc, D3D_ROOT_SIGNATURE_VERSION_1,
            &root_bytes, &errors)) || !root_bytes ||
            FAILED(device->CreateRootSignature(0, root_bytes->GetBufferPointer(), root_bytes->GetBufferSize(),
                IID_PPV_ARGS(&root_signature)))) { return false; }

        static constexpr char shader[] = R"hlsl(
Texture2D<float4> Source : register(t0);
SamplerState LinearClamp : register(s0);
SamplerState PointClamp : register(s1);
cbuffer Replay : register(b0) {
    float4 Mask;   // center U/V, radius U/V
    float4 SourceInfo; // source width/height, peripheral scale, feather
};
struct Vertex { float4 position : SV_Position; float2 uv : TEXCOORD0; };
Vertex VSMain(uint vertex : SV_VertexID) {
    float2 uv = float2((vertex << 1) & 2, vertex & 2);
    Vertex output;
    output.position = float4(uv * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
    output.uv = uv;
    return output;
}
float4 PSMain(Vertex input) : SV_Target0 {
    float2 uv = saturate(input.uv);
    float eyeWidth = SourceInfo.x * 0.5;
    float sourceHeight = SourceInfo.y;
    float2 minimum = float2(0.5 / SourceInfo.x, 0.5 / sourceHeight);
    float2 maximum = float2((eyeWidth - 0.5) / SourceInfo.x, (sourceHeight - 0.5) / sourceHeight);
    float2 fullUV = clamp(float2(uv.x * 0.5, uv.y), minimum, maximum);
    float2 lowExtent = max(float2(1.0, 1.0), floor(float2(eyeWidth, sourceHeight) / SourceInfo.z));
    float2 lowUV = (floor(uv * lowExtent) + 0.5) / lowExtent;
    float2 reducedUV = clamp(float2(lowUV.x * 0.5, lowUV.y), minimum, maximum);
    float4 fullDetail = Source.SampleLevel(LinearClamp, fullUV, 0.0);
    float4 peripheral = Source.SampleLevel(PointClamp, reducedUV, 0.0);
    float distanceFromMask = length((uv - Mask.xy) / Mask.zw);
    float feather = max(SourceInfo.w, 0.0001);
    float focusWeight = 1.0 - smoothstep(1.0 - feather, 1.0 + feather, distanceFromMask);
    return lerp(peripheral, fullDetail, focusWeight);
}
)hlsl";
        ComPtr<ID3DBlob> vertex_bytes, pixel_bytes;
        constexpr UINT flags = D3DCOMPILE_ENABLE_STRICTNESS;
        if (FAILED(D3DCompile(shader, sizeof(shader) - 1, "stable-source-mask", nullptr, nullptr,
            "VSMain", "vs_5_0", flags, 0, &vertex_bytes, &errors)) ||
            FAILED(D3DCompile(shader, sizeof(shader) - 1, "stable-source-mask", nullptr, nullptr,
            "PSMain", "ps_5_0", flags, 0, &pixel_bytes, &errors))) { return false; }

        D3D12_GRAPHICS_PIPELINE_STATE_DESC pso{};
        pso.pRootSignature = root_signature.Get();
        pso.VS = {vertex_bytes->GetBufferPointer(), vertex_bytes->GetBufferSize()};
        pso.PS = {pixel_bytes->GetBufferPointer(), pixel_bytes->GetBufferSize()};
        pso.BlendState.AlphaToCoverageEnable = FALSE;
        pso.BlendState.IndependentBlendEnable = FALSE;
        auto& blend = pso.BlendState.RenderTarget[0];
        blend.BlendEnable = FALSE;
        blend.LogicOpEnable = FALSE;
        blend.SrcBlend = D3D12_BLEND_ONE;
        blend.DestBlend = D3D12_BLEND_ZERO;
        blend.BlendOp = D3D12_BLEND_OP_ADD;
        blend.SrcBlendAlpha = D3D12_BLEND_ONE;
        blend.DestBlendAlpha = D3D12_BLEND_ZERO;
        blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
        blend.LogicOp = D3D12_LOGIC_OP_NOOP;
        blend.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
        pso.SampleMask = UINT_MAX;
        pso.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
        pso.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
        pso.RasterizerState.FrontCounterClockwise = FALSE;
        pso.RasterizerState.DepthBias = D3D12_DEFAULT_DEPTH_BIAS;
        pso.RasterizerState.DepthBiasClamp = D3D12_DEFAULT_DEPTH_BIAS_CLAMP;
        pso.RasterizerState.SlopeScaledDepthBias = D3D12_DEFAULT_SLOPE_SCALED_DEPTH_BIAS;
        pso.RasterizerState.DepthClipEnable = TRUE;
        pso.RasterizerState.MultisampleEnable = FALSE;
        pso.RasterizerState.AntialiasedLineEnable = FALSE;
        pso.RasterizerState.ForcedSampleCount = 0;
        pso.RasterizerState.ConservativeRaster = D3D12_CONSERVATIVE_RASTERIZATION_MODE_OFF;
        pso.DepthStencilState.DepthEnable = FALSE;
        pso.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
        pso.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
        pso.DepthStencilState.StencilEnable = FALSE;
        pso.DepthStencilState.StencilReadMask = D3D12_DEFAULT_STENCIL_READ_MASK;
        pso.DepthStencilState.StencilWriteMask = D3D12_DEFAULT_STENCIL_WRITE_MASK;
        pso.DepthStencilState.FrontFace = {D3D12_STENCIL_OP_KEEP, D3D12_STENCIL_OP_KEEP,
            D3D12_STENCIL_OP_KEEP, D3D12_COMPARISON_FUNC_ALWAYS};
        pso.DepthStencilState.BackFace = pso.DepthStencilState.FrontFace;
        pso.InputLayout = {nullptr, 0};
        pso.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
        pso.NumRenderTargets = 1;
        pso.SampleDesc.Count = 1;
        pso.SampleDesc.Quality = 0;
        pso.DSVFormat = DXGI_FORMAT_UNKNOWN;
        pso.NodeMask = 0;
        pso.Flags = D3D12_PIPELINE_STATE_FLAG_NONE;
        bool created_any_pipeline = false;
        for (std::size_t i = 0; i != pipelines.size(); ++i) {
            if ((i == 0 && !unorm_supported) || (i == 1 && !srgb_supported)) { continue; }
            pso.RTVFormats[0] = i == 0 ? DXGI_FORMAT_B8G8R8A8_UNORM : DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
            if (SUCCEEDED(device->CreateGraphicsPipelineState(&pso, IID_PPV_ARGS(&pipelines[i])))) {
                created_any_pipeline = true;
            }
        }
        return created_any_pipeline;
    }

    std::optional<uint32_t> slot_for(ID3D12Fence* command_fence) {
        if (command_fence == nullptr) { return {}; }
        for (const auto& slot : targets) {
            if (slot.command_fence.Get() == command_fence) { return slot.descriptor_index; }
        }
        if (next_descriptor == descriptor_capacity) { return {}; }
        const auto index = next_descriptor++;
        targets[index].command_fence = command_fence;
        targets[index].descriptor_index = index;
        return index;
    }
};

class StableSourceMask {
public:
    RecordResult record(Mode mode, ID3D12GraphicsCommandList* commands, ID3D12Device* device,
        ID3D12Device* xr_device, ID3D12CommandQueue* command_queue,
        ID3D12CommandQueue* xr_queue,
        ID3D12Resource* source, ID3D12Resource* destination,
        D3D12_RESOURCE_STATES source_state, D3D12_RESOURCE_STATES destination_state,
        uint64_t producer_frame, ID3D12Fence* command_fence, bool descriptor_update_safe) {
        if (mode == Mode::disabled) { return {false, FallbackReason::diagnostic_disabled}; }
        if (mode == Mode::invalid) { return {false, FallbackReason::invalid_diagnostic_configuration}; }
        if (command_fence == nullptr) { return {false, FallbackReason::command_context_unavailable}; }
        if (!descriptor_update_safe) { return {false, FallbackReason::command_context_not_retired}; }
        if (source == nullptr || destination == nullptr) {
            return {false, FallbackReason::source_frame_unavailable};
        }
        if (commands == nullptr || device == nullptr || source == nullptr || destination == nullptr ||
            source == destination || commands->GetType() != D3D12_COMMAND_LIST_TYPE_DIRECT ||
            FAILED(device->GetDeviceRemovedReason())) {
            return {false, FallbackReason::unsupported_device_or_queue};
        }
        if (xr_device != device || command_queue == nullptr || xr_queue == nullptr || command_queue != xr_queue ||
            command_queue->GetDesc().Type != D3D12_COMMAND_LIST_TYPE_DIRECT) {
            return {false, FallbackReason::unsupported_device_or_queue};
        }
        const auto src = source->GetDesc();
        const auto dst = destination->GetDesc();
        const auto source_view = view_format(src.Format);
        const auto target_view = view_format(dst.Format);
        ComPtr<ID3D12Device> source_device, target_device, command_device, queue_device;
        if (src.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || dst.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
            src.Width < 2 || (src.Width & 1u) != 0 || src.Width != dst.Width || src.Height != dst.Height ||
            src.Width > 32768 || src.Height == 0 || src.DepthOrArraySize != 1 || dst.DepthOrArraySize != 1 ||
            src.MipLevels != 1 || dst.MipLevels != 1 || src.SampleDesc.Count != 1 || dst.SampleDesc.Count != 1 ||
            src.SampleDesc.Quality != 0 || dst.SampleDesc.Quality != 0 ||
            !(src.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET) ||
            !(dst.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)) {
            return {false, FallbackReason::invalid_extent_or_format};
        }
        if (source_view == DXGI_FORMAT_UNKNOWN || target_view == DXGI_FORMAT_UNKNOWN || source_view != target_view) {
            return {false, FallbackReason::unsupported_color_view_format};
        }
        if (src.Flags & D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE) {
            return {false, FallbackReason::shader_resource_denied};
        }
        // The caller's known states are authoritative. Do not infer or rewrite
        // either state from the resource's description.
        if (destination_state != D3D12_RESOURCE_STATE_RENDER_TARGET ||
            FAILED(source->GetDevice(IID_PPV_ARGS(&source_device))) ||
            FAILED(destination->GetDevice(IID_PPV_ARGS(&target_device))) ||
            FAILED(commands->GetDevice(IID_PPV_ARGS(&command_device))) ||
            FAILED(command_queue->GetDevice(IID_PPV_ARGS(&queue_device))) ||
            source_device.Get() != device || target_device.Get() != device || command_device.Get() != device ||
            queue_device.Get() != device) {
            return {false, FallbackReason::unsupported_device_or_queue};
        }
        DeviceState* state = nullptr;
        bool created = false;
        for (auto& entry : m_devices) {
            if (entry.device.Get() == device) { state = &entry; break; }
            if (state == nullptr && entry.device == nullptr) { state = &entry; }
        }
        if (state == nullptr) { return {false, FallbackReason::unsupported_device_or_queue}; }
        if (!state->initialization_attempted) {
            created = true;
            if (!state->initialize(device)) { state->ready = false; return {false, FallbackReason::pipeline_unavailable}; }
            state->ready = true;
        }
        if (!state->ready) { return {false, FallbackReason::pipeline_unavailable}; }
        if ((target_view == DXGI_FORMAT_B8G8R8A8_UNORM && !state->unorm_supported) ||
            (target_view == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB && !state->srgb_supported)) {
            return {false, FallbackReason::invalid_extent_or_format};
        }
        auto* pipeline = state->pipeline_for(target_view);
        if (pipeline == nullptr) { return {false, FallbackReason::pipeline_unavailable}; }
        // Device, heaps and PSOs are prepared on an explicit opt-in first frame.
        // That frame uses the original copy path and is excluded from replay.
        if (created) { return {false, FallbackReason::warmup_frame}; }

        uint32_t slot_index = 0;
        // Descriptor reuse is owned by this command context's fence, not by a
        // raw destination pointer that another allocator/context might share.
        const auto slot = state->slot_for(command_fence);
        if (!slot) { return {false, FallbackReason::descriptor_slot_limit}; }
        slot_index = *slot;
        auto shader_handle = state->shader_heap->GetCPUDescriptorHandleForHeapStart();
        shader_handle.ptr += static_cast<SIZE_T>(slot_index) * state->shader_descriptor_size;
        D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
        srv.Format = source_view;
        srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
        srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        srv.Texture2D.MostDetailedMip = 0;
        srv.Texture2D.MipLevels = 1;
        device->CreateShaderResourceView(source, &srv, shader_handle);

        auto rtv_handle = state->render_target_heap->GetCPUDescriptorHandleForHeapStart();
        rtv_handle.ptr += static_cast<SIZE_T>(slot_index) * state->rtv_descriptor_size;
        D3D12_RENDER_TARGET_VIEW_DESC rtv{};
        rtv.Format = target_view;
        rtv.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
        rtv.Texture2D.MipSlice = 0;
        device->CreateRenderTargetView(destination, &rtv, rtv_handle);

        const auto mask = replay_mask(replay_pattern(mode), producer_frame, replay_period_frames);
        if (!mask) { return {false, FallbackReason::source_frame_unavailable}; }
        const float constants[8]{mask->center_u, mask->center_v, mask->radius_u, mask->radius_v,
            static_cast<float>(src.Width), static_cast<float>(src.Height), peripheral_sample_scale, mask->feather};

        D3D12_RESOURCE_BARRIER barriers[2]{};
        UINT barrier_count = 0;
        if (source_state != D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE) {
            auto& barrier = barriers[barrier_count++];
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {source, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                source_state, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE};
        }
        if (destination_state != D3D12_RESOURCE_STATE_RENDER_TARGET) {
            auto& barrier = barriers[barrier_count++];
            barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
            barrier.Transition = {destination, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,
                destination_state, D3D12_RESOURCE_STATE_RENDER_TARGET};
        }
        if (barrier_count != 0) { commands->ResourceBarrier(barrier_count, barriers); }

        ID3D12DescriptorHeap* heaps[]{state->shader_heap.Get()};
        commands->SetDescriptorHeaps(1, heaps);
        commands->SetGraphicsRootSignature(state->root_signature.Get());
        commands->SetPipelineState(pipeline);
        commands->SetGraphicsRoot32BitConstants(1, 8, constants, 0);
        auto gpu_handle = state->shader_heap->GetGPUDescriptorHandleForHeapStart();
        gpu_handle.ptr += static_cast<UINT64>(slot_index) * state->shader_descriptor_size;
        commands->SetGraphicsRootDescriptorTable(0, gpu_handle);
        commands->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);

        commands->OMSetRenderTargets(1, &rtv_handle, FALSE, nullptr);
        const auto eye_width = static_cast<UINT>(src.Width / 2);
        const auto height = src.Height;
        for (UINT eye = 0; eye != 2; ++eye) {
            const D3D12_VIEWPORT viewport{static_cast<float>(eye * eye_width), 0.f,
                static_cast<float>(eye_width), static_cast<float>(height), 0.f, 1.f};
            const D3D12_RECT scissor{static_cast<LONG>(eye * eye_width), 0,
                static_cast<LONG>((eye + 1) * eye_width), static_cast<LONG>(height)};
            commands->RSSetViewports(1, &viewport);
            commands->RSSetScissorRects(1, &scissor);
            commands->DrawInstanced(3, 1, 0, 0);
        }
        for (UINT i = 0; i != barrier_count; ++i) {
            std::swap(barriers[i].Transition.StateBefore, barriers[i].Transition.StateAfter);
        }
        if (barrier_count != 0) { commands->ResourceBarrier(barrier_count, barriers); }
        return {true, FallbackReason::none};
    }

private:
    // OpenXR::copy holds its own mutex while invoking callbacks. The cache is
    // fixed-capacity and process-lifetime so command lists can retain PSO/heaps
    // through teardown; it does not allocate or lock on steady-state frames.
    std::array<DeviceState, device_capacity> m_devices{};
};

inline StableSourceMask& instance() {
    static auto* control = new StableSourceMask{};
    return *control;
}

inline ObservationRing<256>& observations() {
    static ObservationRing<256> ring;
    return ring;
}

inline const char* effective_path_name(EffectivePath path) noexcept {
    switch (path) {
    case EffectivePath::unknown: return "unknown";
    case EffectivePath::mono_copy: return "mono_copy";
    case EffectivePath::stable_source_mask: return "stable_source_moving_mask";
    case EffectivePath::identical_two_views: return "identical_two_views";
    }
    return "unknown";
}

inline void record_observation(const FrameObservation& record, Mode mode) {
    auto& ring = observations();
    ring.try_push(record);
    static uint64_t last_log_frame = 0;
    static bool has_logged = false;
    static EffectivePath last_path = EffectivePath::unknown;
    static FallbackReason last_reason = FallbackReason::none;
    static FallbackReason last_submission_failure = FallbackReason::none;
    const bool changed = record.observed_path != last_path || record.fallback != last_reason ||
        record.submission_failure != last_submission_failure;
    const bool frame_went_backwards = has_logged && record.producer_frame < last_log_frame;
    if (!changed && !frame_went_backwards && record.producer_frame - last_log_frame < 120) { return; }
    last_log_frame = record.producer_frame;
    has_logged = true;
    last_path = record.observed_path;
    last_reason = record.fallback;
    last_submission_failure = record.submission_failure;
    spdlog::info(
        "[DuoViewRestart] copy_frame_counter={} source_generation_observed={} projection_frame={} projection_observed={} gaze_pose_observed={} mask_frame={} requested_method={} effective_method={} requested_control={} observed_copy_path={} control_command_recorded={} mono_copy_command_recorded={} copy_api_returned_successfully={} copy_submission_accepted={} fallback_reason={} submission_failure={} source={}x{} destination={}x{} diagnostics_ring_dropped={} diagnostic_ring_drain=unavailable",
        record.producer_frame,
        record.source_generation_observed ? "true" : "false",
        record.projection_frame,
        record.projection_frame_observed ? "true" : "false",
        record.gaze_pose_observed ? "true" : "false", record.mask_frame,
        record.requested_method, record.effective_method, mode_name(mode),
        effective_path_name(record.observed_path), record.control_command_recorded,
        record.mono_copy_command_recorded, record.copy_api_returned_successfully,
        record.copy_submission_accepted,
        reason_name(record.fallback), reason_name(record.submission_failure),
        record.source_width, record.source_height,
        record.destination_width, record.destination_height, ring.dropped());
}

} // namespace uevr::duoview_restart::dx12
