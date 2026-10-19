#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <d3dcompiler.h>
#include <dxgi1_6.h>
#include <wrl/client.h>
#include "QuadViewGeometry.hpp"
#include "QuadViewD3D12.hpp"
#include <array>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <string>

using Microsoft::WRL::ComPtr;

static void require(HRESULT result, const char* operation) {
    if (FAILED(result)) throw std::runtime_error(std::string(operation) + ": " + std::to_string(result));
}

static D3D12_RESOURCE_DESC texture(uint32_t width, uint32_t height, D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC result{};
    result.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    result.Width = width;
    result.Height = height;
    result.DepthOrArraySize = result.MipLevels = 1;
    result.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    result.SampleDesc.Count = 1;
    result.Flags = flags;
    return result;
}

static D3D12_RESOURCE_DESC buffer(uint64_t size) {
    auto result = texture(1, 1, D3D12_RESOURCE_FLAG_NONE);
    result.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    result.Width = size;
    result.Format = DXGI_FORMAT_UNKNOWN;
    result.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    return result;
}

static ComPtr<ID3D12Resource> resource(ID3D12Device* device, D3D12_RESOURCE_DESC description,
                                      D3D12_HEAP_TYPE type, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES properties{};
    properties.Type = type;
    properties.CreationNodeMask = properties.VisibleNodeMask = 1;
    ComPtr<ID3D12Resource> result;
    require(device->CreateCommittedResource(&properties, D3D12_HEAP_FLAG_NONE, &description,
        state, nullptr, IID_PPV_ARGS(&result)), "CreateCommittedResource");
    return result;
}

static void transition(ID3D12GraphicsCommandList* commands, ID3D12Resource* texture,
                       D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = texture;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    commands->ResourceBarrier(1, &barrier);
}

struct alignas(16) Constants {
    uint32_t eye_and_atlas[4];
    uint32_t rectangles[4][4];
    float crop[4];
    float options[4];
};
static_assert(sizeof(Constants) == 112);

using Color = std::array<uint8_t, 4>;
static Color source_color(unsigned view, unsigned x, unsigned y) {
    if (view == 0) return {240, 10, 20, 255};
    if (view == 1) return {20, 230, 30, 255};
    if (view == 2) return {static_cast<uint8_t>(40 + x * 5), static_cast<uint8_t>(20 + y * 4), 200, 255};
    return {200, static_cast<uint8_t>(40 + x * 3), static_cast<uint8_t>(20 + y * 5), 255};
}

int main(int argc, char** argv) try {
    if (argc != 2 && argc != 3) throw std::runtime_error("Pass QuadViewComposite.hlsl path and optional --srgb");
    const bool srgb_output = argc == 3;
    constexpr uint32_t W = 32, H = 32, AW = 64;
    const auto layout = uevr::quadview::make_layout(W, H, .5f, .5f, .25f, 1.f, .375f, .5f);
    if (!layout) throw std::runtime_error("Invalid test layout");
    ComPtr<ID3D12Debug> debug_layer;
    const bool debug_enabled = SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug_layer)));
    if (debug_enabled) debug_layer->EnableDebugLayer();
    else std::cout << "D3D12 debug layer unavailable; pixel checks remain active.\n";
    ComPtr<IDXGIFactory4> factory;
    require(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "CreateDXGIFactory1");
    ComPtr<IDXGIAdapter> adapter;
    require(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)), "EnumWarpAdapter");
    ComPtr<ID3D12Device> device;
    require(D3D12CreateDevice(adapter.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "D3D12CreateDevice");
    ComPtr<ID3D12InfoQueue> info_queue;
    if (debug_enabled) require(device.As(&info_queue), "Query debug info queue");
    D3D12_COMMAND_QUEUE_DESC queue_description{};
    queue_description.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    require(device->CreateCommandQueue(&queue_description, IID_PPV_ARGS(&queue)), "CreateCommandQueue");
    ComPtr<ID3D12CommandAllocator> allocator;
    require(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&allocator)), "CreateCommandAllocator");
    ComPtr<ID3D12GraphicsCommandList> commands;
    require(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(), nullptr,
        IID_PPV_ARGS(&commands)), "CreateCommandList");

    auto atlas = resource(device.Get(), texture(AW, H, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET),
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_COPY_DEST);
    auto output_description = texture(AW, H, D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    if (srgb_output) output_description.Format = DXGI_FORMAT_R8G8B8A8_UNORM_SRGB;
    auto output = resource(device.Get(), output_description,
        D3D12_HEAP_TYPE_DEFAULT, D3D12_RESOURCE_STATE_RENDER_TARGET);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    uint64_t byte_count{};
    const auto atlas_description = atlas->GetDesc();
    device->GetCopyableFootprints(&atlas_description, 0, 1, 0, &footprint, nullptr, nullptr, &byte_count);
    auto upload = resource(device.Get(), buffer(byte_count), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    auto readback = resource(device.Get(), buffer(byte_count), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
    auto constant_buffer = resource(device.Get(), buffer(256), D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
    void* mapped{};
    D3D12_RANGE no_read{0, 0};
    require(upload->Map(0, &no_read, &mapped), "Map upload");
    std::memset(mapped, 0, static_cast<size_t>(byte_count));
    for (uint32_t y = 0; y < H; ++y) for (uint32_t x = 0; x < AW; ++x) {
        Color color{255, 0, 255, 255};
        for (unsigned view = 0; view < 4; ++view) {
            const auto& rect = layout->views[view];
            if (x >= rect.x && x < rect.x + rect.width && y >= rect.y && y < rect.y + rect.height)
                color = source_color(view, x - rect.x, y - rect.y);
        }
        std::memcpy(static_cast<uint8_t*>(mapped) + y * footprint.Footprint.RowPitch + x * 4, color.data(), 4);
    }
    upload->Unmap(0, nullptr);
    D3D12_TEXTURE_COPY_LOCATION upload_location{};
    upload_location.pResource = upload.Get();
    upload_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    upload_location.PlacedFootprint = footprint;
    D3D12_TEXTURE_COPY_LOCATION atlas_location{};
    atlas_location.pResource = atlas.Get();
    atlas_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    commands->CopyTextureRegion(&atlas_location, 0, 0, 0, &upload_location, nullptr);
    transition(commands.Get(), atlas.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);

    D3D12_DESCRIPTOR_HEAP_DESC heap_description{};
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    heap_description.NumDescriptors = 1;
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> srv_heap;
    require(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&srv_heap)), "Create SRV heap");
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = atlas_description.Format;
    srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2D;
    srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.Texture2D.MipLevels = 1;
    device->CreateShaderResourceView(atlas.Get(), &srv, srv_heap->GetCPUDescriptorHandleForHeapStart());
    heap_description.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    heap_description.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_NONE;
    ComPtr<ID3D12DescriptorHeap> rtv_heap;
    require(device->CreateDescriptorHeap(&heap_description, IID_PPV_ARGS(&rtv_heap)), "Create RTV heap");
    const auto rtv = rtv_heap->GetCPUDescriptorHandleForHeapStart();
    device->CreateRenderTargetView(output.Get(), nullptr, rtv);

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
    D3D12_ROOT_SIGNATURE_DESC root_description{};
    root_description.NumParameters = 2;
    root_description.pParameters = parameters;
    root_description.NumStaticSamplers = 1;
    root_description.pStaticSamplers = &sampler;
    root_description.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    ComPtr<ID3DBlob> serialized, errors;
    require(D3D12SerializeRootSignature(&root_description, D3D_ROOT_SIGNATURE_VERSION_1,
        &serialized, &errors), "Serialize root signature");
    ComPtr<ID3D12RootSignature> root;
    require(device->CreateRootSignature(0, serialized->GetBufferPointer(), serialized->GetBufferSize(),
        IID_PPV_ARGS(&root)), "CreateRootSignature");
    const auto shader_path = std::filesystem::path(argv[1]).wstring();
    const auto compile = [&](const char* entry, const char* profile) {
        ComPtr<ID3DBlob> result, diagnostics;
        const auto status = D3DCompileFromFile(shader_path.c_str(), nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
            entry, profile, D3DCOMPILE_ENABLE_STRICTNESS | D3DCOMPILE_WARNINGS_ARE_ERRORS, 0,
            &result, &diagnostics);
        if (FAILED(status) && diagnostics)
            throw std::runtime_error(std::string(static_cast<const char*>(diagnostics->GetBufferPointer()), diagnostics->GetBufferSize()));
        require(status, "Compile compositor shader");
        return result;
    };
    const auto vs = compile("VSMain", "vs_5_0"), ps = compile("PSMain", "ps_5_0");
    D3D12_GRAPHICS_PIPELINE_STATE_DESC pipeline_description{};
    pipeline_description.pRootSignature = root.Get();
    pipeline_description.VS = {vs->GetBufferPointer(), vs->GetBufferSize()};
    pipeline_description.PS = {ps->GetBufferPointer(), ps->GetBufferSize()};
    pipeline_description.BlendState.RenderTarget[0].RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    auto& blend = pipeline_description.BlendState.RenderTarget[0];
    blend.SrcBlend = blend.SrcBlendAlpha = D3D12_BLEND_ONE;
    blend.DestBlend = blend.DestBlendAlpha = D3D12_BLEND_ZERO;
    blend.BlendOp = blend.BlendOpAlpha = D3D12_BLEND_OP_ADD;
    blend.LogicOp = D3D12_LOGIC_OP_NOOP;
    pipeline_description.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    pipeline_description.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    pipeline_description.RasterizerState.DepthClipEnable = TRUE;
    pipeline_description.DepthStencilState.DepthWriteMask = D3D12_DEPTH_WRITE_MASK_ZERO;
    pipeline_description.DepthStencilState.DepthFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    auto& stencil = pipeline_description.DepthStencilState.FrontFace;
    stencil.StencilFailOp = stencil.StencilDepthFailOp = stencil.StencilPassOp = D3D12_STENCIL_OP_KEEP;
    stencil.StencilFunc = D3D12_COMPARISON_FUNC_ALWAYS;
    pipeline_description.DepthStencilState.BackFace = stencil;
    pipeline_description.SampleMask = UINT_MAX;
    pipeline_description.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    pipeline_description.NumRenderTargets = 1;
    pipeline_description.RTVFormats[0] = output_description.Format;
    pipeline_description.SampleDesc.Count = 1;
    ComPtr<ID3D12PipelineState> pipeline;
    require(device->CreateGraphicsPipelineState(&pipeline_description, IID_PPV_ARGS(&pipeline)), "CreateGraphicsPipelineState");
    uevr::quadview::dx12::Compositor production;
    if (!production.prewarm(device.Get(), atlas_description.Format, output_description.Format))
        throw std::runtime_error(production.error());
    ComPtr<ID3D12Fence> fence;
    require(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "CreateFence");
    struct Event {
        HANDLE value{CreateEventW(nullptr, FALSE, FALSE, nullptr)};
        ~Event() { if (value) CloseHandle(value); }
    } event;
    if (!event.value) throw std::runtime_error("CreateEventW failed");
    Constants constants{{W, H, AW, H}, {}, {.125f, .25f, .625f, .75f}, {0, 0, 0, 0}};
    constants.options[2] = srgb_output ? 1.f : 0.f;
    for (unsigned i = 0; i < 4; ++i) {
        const auto& rect = layout->views[i];
        constants.rectangles[i][0] = rect.x;
        constants.rectangles[i][1] = rect.y;
        constants.rectangles[i][2] = rect.width;
        constants.rectangles[i][3] = rect.height;
    }

    D3D12_RESOURCE_STATES atlas_state = D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE;
    for (unsigned pass = 0; pass < 6; ++pass) {
        const unsigned mode = pass % 3;
        if (pass != 0) {
            require(allocator->Reset(), "Reset allocator");
            require(commands->Reset(allocator.Get(), nullptr), "Reset commands");
            transition(commands.Get(), output.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);
        }
        constants.options[1] = static_cast<float>(mode);
        require(constant_buffer->Map(0, &no_read, &mapped), "Map constants");
        std::memcpy(mapped, &constants, sizeof(constants));
        constant_buffer->Unmap(0, nullptr);
        commands->SetPipelineState(pipeline.Get());
        commands->SetGraphicsRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[]{srv_heap.Get()};
        commands->SetDescriptorHeaps(1, heaps);
        commands->SetGraphicsRootConstantBufferView(0, constant_buffer->GetGPUVirtualAddress());
        commands->SetGraphicsRootDescriptorTable(1, srv_heap->GetGPUDescriptorHandleForHeapStart());
        const D3D12_VIEWPORT viewport{0, 0, static_cast<float>(AW), static_cast<float>(H), 0, 1};
        const D3D12_RECT scissor{0, 0, AW, H};
        commands->RSSetViewports(1, &viewport);
        commands->RSSetScissorRects(1, &scissor);
        commands->OMSetRenderTargets(1, &rtv, FALSE, nullptr);
        commands->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        std::weak_ptr<unsigned> packet_lifetime;
        D3D12_RESOURCE_STATES output_state = D3D12_RESOURCE_STATE_RENDER_TARGET;
        if (pass < 3) {
            commands->DrawInstanced(3, 1, 0, 0);
        } else {
            auto owner = std::make_shared<unsigned>(pass);
            packet_lifetime = owner;
            const auto expected_source_state = pass == 3 ? D3D12_RESOURCE_STATE_RENDER_TARGET :
                pass == 4 ? D3D12_RESOURCE_STATE_COMMON : D3D12_RESOURCE_STATE_GENERIC_READ;
            transition(commands.Get(), atlas.Get(), atlas_state, expected_source_state);
            atlas_state = expected_source_state;
            if (pass == 4) {
                transition(commands.Get(), output.Get(), output_state, D3D12_RESOURCE_STATE_COPY_DEST);
                output_state = D3D12_RESOURCE_STATE_COPY_DEST;
            }
            auto overlapping = *layout;
            overlapping.views[2] = overlapping.views[0];
            if (production.record(commands.Get(), atlas.Get(), output.Get(), overlapping, 0.f, mode,
                atlas_state, output_state, owner))
                throw std::runtime_error("Production compositor accepted overlapping atlas regions");
            if (!production.record(commands.Get(), atlas.Get(), output.Get(), *layout, 0.f, mode,
                atlas_state, output_state, owner))
                throw std::runtime_error(production.error());
            owner.reset();
            if (packet_lifetime.expired()) throw std::runtime_error("Production compositor lost packet before slot retirement");
        }
        transition(commands.Get(), output.Get(), output_state, D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION readback_location{};
        readback_location.pResource = readback.Get();
        readback_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        readback_location.PlacedFootprint = footprint;
        D3D12_TEXTURE_COPY_LOCATION output_location{};
        output_location.pResource = output.Get();
        output_location.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        commands->CopyTextureRegion(&readback_location, 0, 0, 0, &output_location, nullptr);
        require(commands->Close(), "Close commands");
        ID3D12CommandList* lists[]{commands.Get()};
        queue->ExecuteCommandLists(1, lists);
        require(queue->Signal(fence.Get(), pass + 1), "Signal fence");
        require(fence->SetEventOnCompletion(pass + 1, event.value), "SetEventOnCompletion");
        if (WaitForSingleObject(event.value, 10000) != WAIT_OBJECT_0)
            throw std::runtime_error("WARP execution timed out");
        if (info_queue) {
            const auto message_count = info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
            for (UINT64 index = 0; index < message_count; ++index) {
                SIZE_T size{};
                require(info_queue->GetMessage(index, nullptr, &size), "Read debug message size");
                auto storage = std::make_unique<uint8_t[]>(size);
                auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.get());
                require(info_queue->GetMessage(index, message, &size), "Read debug message");
                if (message->Severity <= D3D12_MESSAGE_SEVERITY_ERROR)
                    throw std::runtime_error(std::string("D3D12 validation: ") + message->pDescription);
            }
            info_queue->ClearStoredMessages();
        }
        D3D12_RANGE read_range{0, static_cast<SIZE_T>(byte_count)};
        require(readback->Map(0, &read_range, &mapped), "Map readback");
        for (uint32_t y = 0; y < H; ++y) for (uint32_t x = 0; x < AW; ++x) {
            const unsigned eye = x / W, local_x = x % W;
            const bool inside = local_x >= 4 && local_x < 20 && y >= 8 && y < 24;
            Color expected = mode == 2 ? Color{10, 10, 10, 255} : source_color(eye, 0, 0);
            if (mode != 1 && inside) expected = source_color(eye + 2, local_x - 4, y - 8);
            const auto* pixel = static_cast<const uint8_t*>(mapped) + y * footprint.Footprint.RowPitch + x * 4;
            for (unsigned channel = 0; channel < 4; ++channel) {
                if (std::abs(int(pixel[channel]) - int(expected[channel])) > 1)
                    throw std::runtime_error("Stereo shader mismatch mode=" + std::to_string(mode) +
                        " x=" + std::to_string(x) + " y=" + std::to_string(y));
            }
        }
        D3D12_RANGE no_write{0, 0};
        readback->Unmap(0, &no_write);
        if (pass >= 3) {
            if (packet_lifetime.expired()) throw std::runtime_error("Production packet owner disappeared before explicit retirement");
            production.on_slot_retired();
            if (!packet_lifetime.expired()) throw std::runtime_error("Production packet owner leaked after retirement");
        }
    }
    std::cout << "QuadView WARP: shader and production compositor stereo isolation, off-center ROI, 1:1 focus gradients, atlas clamping, debug views and fence-slot ownership passed.\n";
    return 0;
} catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
}
