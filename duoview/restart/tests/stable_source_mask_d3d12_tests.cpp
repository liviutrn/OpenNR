#define NOMINMAX
#define WIN32_LEAN_AND_MEAN

#include <Windows.h>
#include <d3d12.h>
#include <d3d12sdklayers.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <exception>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "../backend/StableSourceMaskD3D12.hpp"

namespace {

using Microsoft::WRL::ComPtr;
using namespace uevr::duoview_restart;
using namespace uevr::duoview_restart::dx12;

constexpr uint32_t kEyeWidth = 256;
constexpr uint32_t kHeight = 192;
constexpr uint32_t kSourceWidth = kEyeWidth * 2;
constexpr uint8_t kPoisonBlue = 0;
constexpr uint8_t kPoisonGreen = 255;
constexpr uint8_t kPoisonRed = 0;

class SkipTest final : public std::runtime_error {
public:
    explicit SkipTest(const std::string& message) : std::runtime_error(message) {}
};

void require(bool condition, std::string_view message) {
    if (!condition) { throw std::runtime_error(std::string{message}); }
}

void check_hr(HRESULT result, std::string_view operation) {
    if (FAILED(result)) {
        char detail[160]{};
        std::snprintf(detail, sizeof(detail), "%.*s failed (HRESULT 0x%08lX)",
            static_cast<int>(operation.size()), operation.data(), static_cast<unsigned long>(result));
        throw std::runtime_error(detail);
    }
}

const char* mode_label(Mode mode) {
    switch (mode) {
    case Mode::fixed: return "fixed";
    case Mode::step: return "step";
    case Mode::ramp: return "ramp";
    case Mode::alternating: return "alternating";
    case Mode::disabled: return "disabled";
    case Mode::invalid: return "invalid";
    }
    return "unknown";
}

const char* format_label(DXGI_FORMAT format) {
    return format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ? "BGRA8_SRGB" : "BGRA8_UNORM";
}

bool enable_debug_layer() {
    ComPtr<ID3D12Debug> debug;
    if (FAILED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) { return false; }
    debug->EnableDebugLayer();
    return true;
}

ComPtr<ID3D12Device> create_warp_device(bool debug_layer_enabled) {
    ComPtr<IDXGIFactory4> factory;
    const UINT flags = debug_layer_enabled ? static_cast<UINT>(DXGI_CREATE_FACTORY_DEBUG) : 0u;
    HRESULT factory_result = CreateDXGIFactory2(flags, IID_PPV_ARGS(&factory));
    if (FAILED(factory_result) && flags != 0) {
        factory_result = CreateDXGIFactory2(0, IID_PPV_ARGS(&factory));
    }
    if (FAILED(factory_result)) { throw SkipTest("DXGI factory creation is unavailable"); }

    ComPtr<IDXGIAdapter> warp;
    if (FAILED(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)))) {
        throw SkipTest("DXGI WARP adapter is unavailable");
    }
    ComPtr<ID3D12Device> device;
    if (FAILED(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)))) {
        throw SkipTest("D3D12 WARP device creation is unavailable");
    }
    return device;
}

D3D12_RESOURCE_DESC texture_desc(uint32_t width, uint32_t height, DXGI_FORMAT format,
    D3D12_RESOURCE_FLAGS flags) {
    D3D12_RESOURCE_DESC desc{};
    desc.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Alignment = 0;
    desc.Width = width;
    desc.Height = height;
    desc.DepthOrArraySize = 1;
    desc.MipLevels = 1;
    desc.Format = format;
    desc.SampleDesc.Count = 1;
    desc.SampleDesc.Quality = 0;
    desc.Layout = D3D12_TEXTURE_LAYOUT_UNKNOWN;
    desc.Flags = flags;
    return desc;
}

ComPtr<ID3D12Resource> create_committed(ID3D12Device* device, D3D12_HEAP_TYPE heap_type,
    const D3D12_RESOURCE_DESC& desc, D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = heap_type;
    heap.CPUPageProperty = D3D12_CPU_PAGE_PROPERTY_UNKNOWN;
    heap.MemoryPoolPreference = D3D12_MEMORY_POOL_UNKNOWN;
    heap.CreationNodeMask = 1;
    heap.VisibleNodeMask = 1;
    ComPtr<ID3D12Resource> resource;
    check_hr(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE, &desc, state,
        nullptr, IID_PPV_ARGS(&resource)), "CreateCommittedResource");
    return resource;
}

D3D12_RESOURCE_BARRIER transition(ID3D12Resource* resource,
    D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource = resource;
    barrier.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore = before;
    barrier.Transition.StateAfter = after;
    return barrier;
}

class CommandContext {
public:
    explicit CommandContext(ID3D12Device* device) {
        check_hr(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
            IID_PPV_ARGS(&allocator)), "CreateCommandAllocator");
        check_hr(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, allocator.Get(),
            nullptr, IID_PPV_ARGS(&commands)), "CreateCommandList");
        check_hr(commands->Close(), "Close initial command list");
        check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)),
            "CreateFence");
    }

    bool references_retired() const {
        if (last_submitted_value == 0) { return true; }
        const UINT64 completed = fence->GetCompletedValue();
        require(completed != (std::numeric_limits<UINT64>::max)(),
            "command context fence reports device removal");
        return completed >= last_submitted_value;
    }

    void begin() {
        require(references_retired(), "attempted to reset an in-flight command context");
        check_hr(allocator->Reset(), "Reset command allocator");
        check_hr(commands->Reset(allocator.Get(), nullptr), "Reset graphics command list");
        recording = true;
    }

    void discard() {
        require(recording, "attempted to discard a closed command list");
        check_hr(commands->Close(), "Close discarded command list");
        recording = false;
    }

    void submit(ID3D12CommandQueue* queue) {
        require(recording, "attempted to submit a closed command list");
        check_hr(commands->Close(), "Close command list");
        recording = false;
        ID3D12CommandList* lists[]{commands.Get()};
        queue->ExecuteCommandLists(1, lists);
        ++last_submitted_value;
        check_hr(queue->Signal(fence.Get(), last_submitted_value), "Signal context fence");
    }

    void wait() const {
        if (references_retired()) { return; }
        HANDLE event_handle = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        require(event_handle != nullptr, "CreateEventW failed while waiting for a fence");
        const HRESULT result = fence->SetEventOnCompletion(last_submitted_value, event_handle);
        if (FAILED(result)) {
            CloseHandle(event_handle);
            check_hr(result, "SetEventOnCompletion");
        }
        const DWORD wait_result = WaitForSingleObject(event_handle, INFINITE);
        CloseHandle(event_handle);
        require(wait_result == WAIT_OBJECT_0, "WaitForSingleObject failed while waiting for a fence");
        require(references_retired(), "fence event fired before its target value completed");
    }

    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commands;
    ComPtr<ID3D12Fence> fence;
    UINT64 last_submitted_value{};
    bool recording{};
};

class QueueGate {
public:
    QueueGate(ID3D12Device* device, ID3D12CommandQueue* queue) {
        check_hr(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence_)),
            "Create queue gate fence");
        check_hr(queue->Wait(fence_.Get(), 1), "Queue Wait on gate fence");
        blocked_ = true;
    }

    ~QueueGate() {
        if (blocked_ && fence_) { fence_->Signal(1); }
    }

    void release() {
        if (!blocked_) { return; }
        check_hr(fence_->Signal(1), "Release queue gate fence");
        blocked_ = false;
    }

private:
    ComPtr<ID3D12Fence> fence_;
    bool blocked_{};
};

class RenderTarget {
public:
    RenderTarget(ID3D12Device* device, DXGI_FORMAT format)
        : desc_(texture_desc(kSourceWidth, kHeight, format,
            D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)) {
        target_ = create_committed(device, D3D12_HEAP_TYPE_DEFAULT, desc_,
            D3D12_RESOURCE_STATE_RENDER_TARGET);
        device->GetCopyableFootprints(&desc_, 0, 1, 0, &footprint_, &row_count_,
            &row_size_, &total_bytes_);
        require(row_count_ == kHeight && row_size_ >= static_cast<UINT64>(kSourceWidth) * 4u &&
            total_bytes_ != 0, "unexpected render-target readback footprint");
        D3D12_RESOURCE_DESC buffer_desc{};
        buffer_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        buffer_desc.Width = total_bytes_;
        buffer_desc.Height = 1;
        buffer_desc.DepthOrArraySize = 1;
        buffer_desc.MipLevels = 1;
        buffer_desc.SampleDesc.Count = 1;
        buffer_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        readback_ = create_committed(device, D3D12_HEAP_TYPE_READBACK, buffer_desc,
            D3D12_RESOURCE_STATE_COPY_DEST);
    }

    void append_readback(ID3D12GraphicsCommandList* commands) const {
        auto to_copy = transition(target_.Get(), D3D12_RESOURCE_STATE_RENDER_TARGET,
            D3D12_RESOURCE_STATE_COPY_SOURCE);
        commands->ResourceBarrier(1, &to_copy);
        D3D12_TEXTURE_COPY_LOCATION destination{};
        destination.pResource = readback_.Get();
        destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination.PlacedFootprint = footprint_;
        D3D12_TEXTURE_COPY_LOCATION source{};
        source.pResource = target_.Get();
        source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        source.SubresourceIndex = 0;
        commands->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        auto to_render = transition(target_.Get(), D3D12_RESOURCE_STATE_COPY_SOURCE,
            D3D12_RESOURCE_STATE_RENDER_TARGET);
        commands->ResourceBarrier(1, &to_render);
    }

    std::vector<uint8_t> read_pixels() const {
        D3D12_RANGE read_range{0, static_cast<SIZE_T>(total_bytes_)};
        void* mapped = nullptr;
        check_hr(readback_->Map(0, &read_range, &mapped), "Map readback buffer");
        const auto* bytes = static_cast<const uint8_t*>(mapped);
        std::vector<uint8_t> pixels(static_cast<std::size_t>(kSourceWidth) * kHeight * 4u);
        const std::size_t row_bytes = static_cast<std::size_t>(kSourceWidth) * 4u;
        for (uint32_t y = 0; y < kHeight; ++y) {
            const auto source_offset = static_cast<std::size_t>(footprint_.Offset) +
                static_cast<std::size_t>(y) * footprint_.Footprint.RowPitch;
            std::copy_n(bytes + source_offset, row_bytes,
                pixels.data() + static_cast<std::size_t>(y) * row_bytes);
        }
        const D3D12_RANGE written_range{0, 0};
        readback_->Unmap(0, &written_range);
        return pixels;
    }

    ID3D12Resource* resource() const noexcept { return target_.Get(); }

private:
    D3D12_RESOURCE_DESC desc_{};
    ComPtr<ID3D12Resource> target_;
    ComPtr<ID3D12Resource> readback_;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint_{};
    UINT row_count_{};
    UINT64 row_size_{};
    UINT64 total_bytes_{};
};

std::vector<uint8_t> make_source_pixels() {
    std::vector<uint8_t> pixels(static_cast<std::size_t>(kSourceWidth) * kHeight * 4u);
    for (uint32_t y = 0; y < kHeight; ++y) {
        for (uint32_t x = 0; x < kSourceWidth; ++x) {
            const auto offset = (static_cast<std::size_t>(y) * kSourceWidth + x) * 4u;
            if (x >= kEyeWidth) {
                pixels[offset + 0] = kPoisonBlue;
                pixels[offset + 1] = kPoisonGreen;
                pixels[offset + 2] = kPoisonRed;
                pixels[offset + 3] = 255;
                continue;
            }
            const uint32_t cell_x = x / 4u;
            const uint32_t cell_y = y / 4u;
            const uint32_t local_x = x & 3u;
            const uint32_t local_y = y & 3u;
            const uint32_t hash = (cell_x * 0x9E37u) ^ (cell_y * 0x85EBu) ^
                (cell_x * cell_y * 0x45D9u);
            const uint32_t base_blue = 48u + (hash & 0x3Fu);
            const uint32_t base_green = 48u + ((hash >> 7u) & 0x3Fu);
            const uint32_t base_red = 48u + ((hash >> 14u) & 0x3Fu);
            const bool coarse_plateau = (local_x == 1u || local_x == 2u) &&
                (local_y == 1u || local_y == 2u);
            pixels[offset + 0] = static_cast<uint8_t>(base_blue +
                (coarse_plateau ? 0u : 12u + ((local_x + local_y) & 7u)));
            pixels[offset + 1] = static_cast<uint8_t>(base_green +
                (coarse_plateau ? 0u : 16u + ((3u * local_x + local_y) & 7u)));
            pixels[offset + 2] = static_cast<uint8_t>(base_red +
                (coarse_plateau ? 0u : 20u + ((local_x + 3u * local_y) & 7u)));
            pixels[offset + 3] = 255;
        }
    }
    return pixels;
}

ComPtr<ID3D12Resource> upload_source(ID3D12Device* device, ID3D12CommandQueue* queue,
    CommandContext& context, DXGI_FORMAT format, const std::vector<uint8_t>& pixels) {
    const auto desc = texture_desc(kSourceWidth, kHeight, format,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto source = create_committed(device, D3D12_HEAP_TYPE_DEFAULT, desc,
        D3D12_RESOURCE_STATE_COPY_DEST);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows = 0;
    UINT64 row_size = 0;
    UINT64 total_bytes = 0;
    device->GetCopyableFootprints(&desc, 0, 1, 0, &footprint, &rows, &row_size, &total_bytes);
    require(rows == kHeight && row_size >= static_cast<UINT64>(kSourceWidth) * 4u,
        "unexpected source upload footprint");
    D3D12_RESOURCE_DESC upload_desc{};
    upload_desc.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
    upload_desc.Width = total_bytes;
    upload_desc.Height = 1;
    upload_desc.DepthOrArraySize = 1;
    upload_desc.MipLevels = 1;
    upload_desc.SampleDesc.Count = 1;
    upload_desc.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    auto upload = create_committed(device, D3D12_HEAP_TYPE_UPLOAD, upload_desc,
        D3D12_RESOURCE_STATE_GENERIC_READ);
    D3D12_RANGE no_read{0, 0};
    void* mapped = nullptr;
    check_hr(upload->Map(0, &no_read, &mapped), "Map upload buffer");
    auto* upload_bytes = static_cast<uint8_t*>(mapped);
    const std::size_t row_bytes = static_cast<std::size_t>(kSourceWidth) * 4u;
    for (uint32_t y = 0; y < kHeight; ++y) {
        auto* row = upload_bytes + static_cast<std::size_t>(footprint.Offset) +
            static_cast<std::size_t>(y) * footprint.Footprint.RowPitch;
        const auto* source_row = pixels.data() + static_cast<std::size_t>(y) * row_bytes;
        std::copy_n(source_row, row_bytes, row);
    }
    const D3D12_RANGE written{0, static_cast<SIZE_T>(total_bytes)};
    upload->Unmap(0, &written);

    context.begin();
    D3D12_TEXTURE_COPY_LOCATION destination{};
    destination.pResource = source.Get();
    destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    destination.SubresourceIndex = 0;
    D3D12_TEXTURE_COPY_LOCATION source_location{};
    source_location.pResource = upload.Get();
    source_location.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    source_location.PlacedFootprint = footprint;
    context.commands->CopyTextureRegion(&destination, 0, 0, 0, &source_location, nullptr);
    auto to_sample_later = transition(source.Get(), D3D12_RESOURCE_STATE_COPY_DEST,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    context.commands->ResourceBarrier(1, &to_sample_later);
    context.submit(queue);
    context.wait();
    return source;
}

RecordResult record_mask(StableSourceMask& control, Mode mode, CommandContext& commands,
    ID3D12Device* device, ID3D12CommandQueue* queue, ID3D12Resource* source,
    ID3D12Resource* destination, uint64_t frame, ID3D12Fence* owner_fence,
    bool owner_references_retired) {
    return control.record(mode, commands.commands.Get(), device, device, queue, queue,
        source, destination, D3D12_RESOURCE_STATE_COPY_SOURCE,
        D3D12_RESOURCE_STATE_RENDER_TARGET, frame, owner_fence, owner_references_retired);
}

struct OraclePixel {
    std::array<uint8_t, 4> encoded{};
    float focus_weight{};
    float mask_distance{};
    uint32_t coarse_x{};
    uint32_t coarse_y{};
};

std::size_t pixel_offset(uint32_t x, uint32_t y) {
    return (static_cast<std::size_t>(y) * kSourceWidth + x) * 4u;
}

float decode_srgb(float value) {
    return value <= 0.04045f ? value / 12.92f :
        std::pow((value + 0.055f) / 1.055f, 2.4f);
}

float encode_srgb(float value) {
    value = (std::clamp)(value, 0.0f, 1.0f);
    return value <= 0.0031308f ? value * 12.92f :
        1.055f * std::pow(value, 1.0f / 2.4f) - 0.055f;
}

OraclePixel oracle_pixel(const std::vector<uint8_t>& source, DXGI_FORMAT format,
    const MaskSample& mask, uint32_t x, uint32_t y) {
    const float u = (static_cast<float>(x) + 0.5f) / static_cast<float>(kEyeWidth);
    const float v = (static_cast<float>(y) + 0.5f) / static_cast<float>(kHeight);
    const float dx = (u - mask.center_u) / mask.radius_u;
    const float dy = (v - mask.center_v) / mask.radius_v;
    const float distance = std::sqrt(dx * dx + dy * dy);
    const float feather = (std::max)(mask.feather, 0.0001f);
    const float t = (std::clamp)((distance - (1.0f - feather)) / (2.0f * feather), 0.0f, 1.0f);
    const float smooth = t * t * (3.0f - 2.0f * t);
    const float focus = 1.0f - smooth;

    const float low_width = (std::max)(1.0f,
        std::floor(static_cast<float>(kEyeWidth) / peripheral_sample_scale));
    const float low_height = (std::max)(1.0f,
        std::floor(static_cast<float>(kHeight) / peripheral_sample_scale));
    const float low_u = (std::floor(u * low_width) + 0.5f) / low_width;
    const float low_v = (std::floor(v * low_height) + 0.5f) / low_height;
    const float reduced_u = (std::clamp)(low_u * 0.5f,
        0.5f / static_cast<float>(kSourceWidth),
        (static_cast<float>(kEyeWidth) - 0.5f) / static_cast<float>(kSourceWidth));
    const float reduced_v = (std::clamp)(low_v,
        0.5f / static_cast<float>(kHeight),
        (static_cast<float>(kHeight) - 0.5f) / static_cast<float>(kHeight));
    // Point-sampling at each 4x cell center lands on a boundary between source
    // texels. The deterministic source pattern gives both adjacent texels the
    // same value, so this floor convention is independent of tie-breaking.
    const auto coarse_x = (std::min)(kEyeWidth - 1,
        static_cast<uint32_t>(std::floor(reduced_u * static_cast<float>(kSourceWidth))));
    const auto coarse_y = (std::min)(kHeight - 1,
        static_cast<uint32_t>(std::floor(reduced_v * static_cast<float>(kHeight))));
    const auto full_offset = pixel_offset(x, y);
    const auto coarse_offset = pixel_offset(coarse_x, coarse_y);
    const bool srgb = format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;

    OraclePixel expected{};
    expected.focus_weight = focus;
    expected.mask_distance = distance;
    expected.coarse_x = coarse_x;
    expected.coarse_y = coarse_y;
    for (std::size_t channel = 0; channel < expected.encoded.size(); ++channel) {
        float full = static_cast<float>(source[full_offset + channel]) / 255.0f;
        float coarse = static_cast<float>(source[coarse_offset + channel]) / 255.0f;
        if (srgb && channel < 3) {
            full = decode_srgb(full);
            coarse = decode_srgb(coarse);
        }
        float blended = coarse + (full - coarse) * focus;
        if (srgb && channel < 3) { blended = encode_srgb(blended); }
        expected.encoded[channel] = static_cast<uint8_t>(std::lround(
            (std::clamp)(blended, 0.0f, 1.0f) * 255.0f));
    }
    return expected;
}

bool within_tolerance(const uint8_t* actual, const OraclePixel& expected, int tolerance) {
    for (std::size_t channel = 0; channel < expected.encoded.size(); ++channel) {
        const int a = actual[channel];
        const int e = expected.encoded[channel];
        if (a < e - tolerance || a > e + tolerance) { return false; }
    }
    return true;
}

void verify_sample(const std::vector<uint8_t>& output, const std::vector<uint8_t>& source,
    DXGI_FORMAT format, const MaskSample& mask, uint32_t x, uint32_t y,
    std::string_view purpose, int tolerance) {
    const auto expected = oracle_pixel(source, format, mask, x, y);
    const auto left_offset = pixel_offset(x, y);
    const auto right_offset = pixel_offset(x + kEyeWidth, y);
    require(within_tolerance(output.data() + left_offset, expected, tolerance), purpose);
    require(within_tolerance(output.data() + right_offset, expected, tolerance), purpose);
}

void verify_output(const std::vector<uint8_t>& output, const std::vector<uint8_t>& source,
    DXGI_FORMAT format, Mode mode, uint64_t frame) {
    const auto mask = replay_mask(replay_pattern(mode), frame, replay_period_frames);
    require(mask.has_value(), "test requested a replay mask with invalid parameters");
    const int tolerance = format == DXGI_FORMAT_B8G8R8A8_UNORM_SRGB ? 3 : 2;

    // Compare every WARP pixel with an independent CPU oracle for the shader's
    // full-detail sample, 4x point sample, mask smoothstep, and feather blend.
    float closest_edge_distance = (std::numeric_limits<float>::max)();
    uint32_t edge_x = 0;
    uint32_t edge_y = 0;
    for (uint32_t y = 0; y < kHeight; ++y) {
        for (uint32_t x = 0; x < kEyeWidth; ++x) {
            const auto expected = oracle_pixel(source, format, *mask, x, y);
            closest_edge_distance = (std::min)(closest_edge_distance,
                std::abs(expected.mask_distance - 1.0f));
            if (std::abs(expected.mask_distance - 1.0f) == closest_edge_distance) {
                edge_x = x;
                edge_y = y;
            }
            const auto left = pixel_offset(x, y);
            const auto right = pixel_offset(x + kEyeWidth, y);
            require(within_tolerance(output.data() + left, expected, tolerance),
                "output eye 0 differs from the analytic mask/reduction oracle");
            require(within_tolerance(output.data() + right, expected, tolerance),
                "output eye 1 differs from the analytic mask/reduction oracle");
            for (std::size_t channel = 0; channel < 4; ++channel) {
                require(output[left + channel] == output[right + channel],
                    "two output eyes differ despite sampling the same source region");
            }
            require(!(output[left + 0] == kPoisonBlue && output[left + 1] == kPoisonGreen &&
                output[left + 2] == kPoisonRed),
                "poison from the unused right source half leaked into output");
        }
    }

    const auto center_x = static_cast<uint32_t>(mask->center_u * static_cast<float>(kEyeWidth));
    const auto center_y = static_cast<uint32_t>(mask->center_v * static_cast<float>(kHeight));
    const std::array<std::array<int, 2>, 5> inside_offsets{{
        {{0, 0}}, {{-1, 0}}, {{1, 0}}, {{0, -1}}, {{0, 1}},
    }};
    for (const auto& offset : inside_offsets) {
        const auto x = static_cast<uint32_t>(static_cast<int>(center_x) +
            static_cast<int>(std::lround(static_cast<float>(offset[0]) * mask->radius_u *
                static_cast<float>(kEyeWidth) * 0.4f)));
        const auto y = static_cast<uint32_t>(static_cast<int>(center_y) +
            static_cast<int>(std::lround(static_cast<float>(offset[1]) * mask->radius_v *
                static_cast<float>(kHeight) * 0.4f)));
        const auto expected = oracle_pixel(source, format, *mask, x, y);
        require(expected.focus_weight > 0.999f,
            "chosen interior sample is not fully inside the high-detail mask");
        verify_sample(output, source, format, *mask, x, y,
            "high-detail source sample was not preserved at an interior mask point", tolerance);
    }

    // The chosen world feature stays at the same output coordinate for every
    // producer frame. Its expected source point is recomputed from the same
    // stable texture and that frame's replay mask.
    verify_sample(output, source, format, *mask, 24, 24,
        "fixed source feature did not follow the current replay mask", tolerance);

    constexpr std::array<std::array<uint32_t, 2>, 4> outside_points{{
        {{4, 4}}, {{kEyeWidth - 4, 4}}, {{4, kHeight - 4}},
        {{kEyeWidth - 4, kHeight - 4}},
    }};
    for (const auto& point : outside_points) {
        const auto expected = oracle_pixel(source, format, *mask, point[0], point[1]);
        require(expected.focus_weight < 0.001f,
            "chosen coarse sample is not outside the replay mask");
        verify_sample(output, source, format, *mask, point[0], point[1],
            "outside-mask point did not match the reduced-detail oracle", tolerance);
    }

    const auto edge = oracle_pixel(source, format, *mask, edge_x, edge_y);
    require(edge.focus_weight > 0.0f && edge.focus_weight < 1.0f,
        "output resolution did not produce a sample in the mask feather band");
    verify_sample(output, source, format, *mask, edge_x, edge_y,
        "near-edge feather sample exceeded the encoded-space tolerance", tolerance);

    // Negative control: a shader that ignores the mask and always uses the
    // full-detail source would fail at this deliberately high-frequency point.
    const auto negative_control = oracle_pixel(source, format, *mask, 4, 4);
    const auto full_offset = pixel_offset(4, 4);
    require(negative_control.focus_weight == 0.0f,
        "negative control point unexpectedly intersects the full-detail mask");
    require(!within_tolerance(source.data() + full_offset, negative_control, tolerance),
        "test source pattern does not distinguish full-only output from the coarse oracle");
}

void expect_fallback(RecordResult result, FallbackReason reason, std::string_view message) {
    require(!result.command_recorded, message);
    require(result.reason == reason, message);
}

void test_invalid_inputs(StableSourceMask& control, Mode mode, ID3D12Device* device,
    ID3D12CommandQueue* queue, RenderTarget& valid_target) {
    CommandContext context{device};
    const auto odd_desc = texture_desc(kSourceWidth + 1, kHeight, DXGI_FORMAT_B8G8R8A8_UNORM,
        D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET);
    auto odd_source = create_committed(device, D3D12_HEAP_TYPE_DEFAULT, odd_desc,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    auto odd_target = create_committed(device, D3D12_HEAP_TYPE_DEFAULT, odd_desc,
        D3D12_RESOURCE_STATE_RENDER_TARGET);
    context.begin();
    expect_fallback(record_mask(control, mode, context, device, queue, odd_source.Get(),
        odd_target.Get(), 0, context.fence.Get(), context.references_retired()),
        FallbackReason::invalid_extent_or_format,
        "odd double-wide width must fail as invalid_extent_or_format");
    context.discard();

    const auto denied_desc = texture_desc(kSourceWidth, kHeight, DXGI_FORMAT_B8G8R8A8_UNORM,
        static_cast<D3D12_RESOURCE_FLAGS>(D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET |
            D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE));
    auto denied_source = create_committed(device, D3D12_HEAP_TYPE_DEFAULT, denied_desc,
        D3D12_RESOURCE_STATE_COPY_SOURCE);
    context.begin();
    expect_fallback(record_mask(control, mode, context, device, queue, denied_source.Get(),
        valid_target.resource(), 1, context.fence.Get(), context.references_retired()),
        FallbackReason::shader_resource_denied,
        "DENY_SHADER_RESOURCE source must fail as shader_resource_denied");
    context.discard();
}

void run_mode_and_format(ID3D12Device* device, ID3D12CommandQueue* queue,
    DXGI_FORMAT format, Mode mode) {
    const auto source_pixels = make_source_pixels();
    CommandContext upload_context{device};
    auto source = upload_source(device, queue, upload_context, format, source_pixels);
    RenderTarget target_a{device, format};
    RenderTarget target_b{device, format};
    StableSourceMask control;
    const std::array<uint64_t, 4> frames = mode == Mode::fixed
        ? std::array<uint64_t, 4>{0, 1, 2, 3}
        : mode == Mode::step
            ? std::array<uint64_t, 4>{0, replay_period_frames, replay_period_frames + 1, 2 * replay_period_frames}
            : mode == Mode::ramp
                ? std::array<uint64_t, 4>{0, replay_period_frames / 2, replay_period_frames,
                    replay_period_frames + replay_period_frames / 2}
                : std::array<uint64_t, 4>{0, replay_period_frames, 2 * replay_period_frames,
                    3 * replay_period_frames};

    CommandContext context_a{device};
    context_a.begin();
    const auto warmup = record_mask(control, mode, context_a, device, queue, source.Get(),
        target_a.resource(), frames[0], context_a.fence.Get(), context_a.references_retired());
    expect_fallback(warmup, FallbackReason::warmup_frame,
        "first valid call per device must prepare pipelines and report warmup_frame");
    context_a.discard();

    CommandContext context_b{device};
    context_a.begin();
    const auto first = record_mask(control, mode, context_a, device, queue, source.Get(),
        target_a.resource(), frames[0], context_a.fence.Get(), context_a.references_retired());
    require(first.command_recorded && first.reason == FallbackReason::none,
        "active control frame was not recorded after warmup");
    target_a.append_readback(context_a.commands.Get());
    context_b.begin();
    const auto second = record_mask(control, mode, context_b, device, queue, source.Get(),
        target_b.resource(), frames[1], context_b.fence.Get(), context_b.references_retired());
    require(second.command_recorded && second.reason == FallbackReason::none,
        "second independent command context did not record the control");
    target_b.append_readback(context_b.commands.Get());

    // Hold the queue before both submissions. This makes the owner fence's
    // pending state deterministic even on a fast software adapter.
    QueueGate queue_gate{device, queue};
    context_a.submit(queue);
    context_b.submit(queue);
    require(!context_a.references_retired(), "queued context unexpectedly retired before gate release");
    require(context_a.fence.Get() != context_b.fence.Get(),
        "independent command contexts unexpectedly share an owner fence");

    CommandContext probe{device};
    probe.begin();
    const bool owner_is_retired = context_a.references_retired();
    require(!owner_is_retired, "unsafe descriptor test did not observe a pending owner fence");
    const auto unsafe = record_mask(control, mode, probe, device, queue, source.Get(),
        target_a.resource(), frames[2], context_a.fence.Get(), owner_is_retired);
    expect_fallback(unsafe, FallbackReason::command_context_not_retired,
        "descriptor update must be rejected while its actual owner fence is pending");
    probe.discard();

    queue_gate.release();
    context_a.wait();
    context_b.wait();
    verify_output(target_a.read_pixels(), source_pixels, format, mode, frames[0]);
    verify_output(target_b.read_pixels(), source_pixels, format, mode, frames[1]);

    // Reuse both command contexts only after their own fence values complete.
    // The source is deliberately returned to COPY_SOURCE by the module after
    // each draw, so every subsequent call validates the source-state restore.
    for (std::size_t i = 2; i < frames.size(); ++i) {
        auto& context = (i & 1u) == 0 ? context_a : context_b;
        auto& target = (i & 1u) == 0 ? target_a : target_b;
        context.begin();
        const auto result = record_mask(control, mode, context, device, queue, source.Get(),
            target.resource(), frames[i], context.fence.Get(), context.references_retired());
        require(result.command_recorded && result.reason == FallbackReason::none,
            "reused retired command context failed to record the mask");
        target.append_readback(context.commands.Get());
        context.submit(queue);
        context.wait();
        verify_output(target.read_pixels(), source_pixels, format, mode, frames[i]);
    }

    if (format == DXGI_FORMAT_B8G8R8A8_UNORM && mode == Mode::fixed) {
        test_invalid_inputs(control, mode, device, queue, target_a);
    }
    std::printf("PASS WARP mode=%s format=%s frames=%llu\n", mode_label(mode),
        format_label(format), static_cast<unsigned long long>(frames.size()));
}

void check_debug_errors(ID3D12Device* device, bool debug_layer_enabled) {
    if (!debug_layer_enabled) {
        std::puts("INFO D3D12 debug layer unavailable; GPU output checks still ran");
        return;
    }
    ComPtr<ID3D12InfoQueue> info_queue;
    if (FAILED(device->QueryInterface(IID_PPV_ARGS(&info_queue)))) {
        std::puts("INFO D3D12 debug info queue unavailable; GPU output checks still ran");
        return;
    }
    const UINT64 message_count = info_queue->GetNumStoredMessages();
    UINT64 error_count = 0;
    for (UINT64 i = 0; i < message_count; ++i) {
        SIZE_T message_size = 0;
        if (FAILED(info_queue->GetMessage(i, nullptr, &message_size)) || message_size == 0) { continue; }
        std::vector<uint8_t> storage(message_size);
        auto* message = reinterpret_cast<D3D12_MESSAGE*>(storage.data());
        if (FAILED(info_queue->GetMessage(i, message, &message_size))) { continue; }
        if (message->Severity == D3D12_MESSAGE_SEVERITY_ERROR ||
            message->Severity == D3D12_MESSAGE_SEVERITY_CORRUPTION) {
            ++error_count;
            std::fprintf(stderr, "D3D12 debug error: %s\n", message->pDescription);
        }
    }
    require(error_count == 0, "D3D12 debug layer reported an error or corruption message");
    std::printf("INFO D3D12 debug layer enabled; checked %llu messages\n",
        static_cast<unsigned long long>(message_count));
}

} // namespace

int main() {
    try {
        const bool debug_layer_enabled = enable_debug_layer();
        auto device = create_warp_device(debug_layer_enabled);
        D3D12_COMMAND_QUEUE_DESC queue_desc{};
        queue_desc.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        queue_desc.Priority = D3D12_COMMAND_QUEUE_PRIORITY_NORMAL;
        queue_desc.Flags = D3D12_COMMAND_QUEUE_FLAG_NONE;
        queue_desc.NodeMask = 0;
        ComPtr<ID3D12CommandQueue> queue;
        check_hr(device->CreateCommandQueue(&queue_desc, IID_PPV_ARGS(&queue)),
            "CreateCommandQueue");

        constexpr std::array<DXGI_FORMAT, 2> formats{
            DXGI_FORMAT_B8G8R8A8_UNORM, DXGI_FORMAT_B8G8R8A8_UNORM_SRGB};
        constexpr std::array<Mode, 4> modes{Mode::fixed, Mode::step, Mode::ramp, Mode::alternating};
        for (const auto format : formats) {
            D3D12_FEATURE_DATA_FORMAT_SUPPORT support{};
            support.Format = format;
            check_hr(device->CheckFeatureSupport(D3D12_FEATURE_FORMAT_SUPPORT, &support,
                sizeof(support)), "CheckFeatureSupport for BGRA format");
            const UINT format_flags = static_cast<UINT>(support.Support1);
            const bool sample_supported =
                (format_flags & static_cast<UINT>(D3D12_FORMAT_SUPPORT1_SHADER_SAMPLE)) != 0u;
            const bool render_supported =
                (format_flags & static_cast<UINT>(D3D12_FORMAT_SUPPORT1_RENDER_TARGET)) != 0u;
            require(sample_supported && render_supported,
                "WARP must support sampling and rendering the tested BGRA format");
            for (const auto mode : modes) { run_mode_and_format(device.Get(), queue.Get(), format, mode); }
        }
        check_debug_errors(device.Get(), debug_layer_enabled);
        std::puts("PASS stable-source-mask WARP validation");
        return 0;
    } catch (const SkipTest& skipped) {
        std::printf("SKIP %s\n", skipped.what());
        return 77;
    } catch (const std::exception& error) {
        std::fprintf(stderr, "FAIL %s\n", error.what());
        return 1;
    }
}
