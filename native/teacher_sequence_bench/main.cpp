#include <Windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl/client.h>

#include <array>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>

#include "Runtime.h"
#include "BenchmarkContract.h"

using Microsoft::WRL::ComPtr;

namespace
{
void Check(HRESULT value, const char* operation)
{
    if (FAILED(value))
        throw std::runtime_error(std::string(operation) + " HRESULT=" + std::to_string(value));
}

struct EyeSpec
{
    std::filesystem::path color;
    std::filesystem::path depth;
    std::filesystem::path motion;
    std::filesystem::path output;
    float motionScaleX = 0.0f;
    float motionScaleY = 0.0f;
};

struct FrameSpec
{
    std::uint32_t frameId = 0;
    std::array<EyeSpec, 2> eyes;
};

struct EyeResources
{
    ComPtr<ID3D12Resource> color;
    ComPtr<ID3D12Resource> depth;
    ComPtr<ID3D12Resource> motion;
    ComPtr<ID3D12Resource> output;
};

struct Bench
{
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commands;
    ComPtr<ID3D12Fence> fence;
    HANDLE event = nullptr;
    UINT64 serial = 0;
    std::vector<ComPtr<ID3D12Resource>> uploads;

    ~Bench()
    {
        if (event)
            CloseHandle(event);
    }

    void Initialize()
    {
        ComPtr<IDXGIFactory6> factory;
        Check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "DXGI factory");
        for (UINT index = 0;; ++index) {
            ComPtr<IDXGIAdapter1> adapter;
            if (factory->EnumAdapterByGpuPreference(
                    index, DXGI_GPU_PREFERENCE_HIGH_PERFORMANCE, IID_PPV_ARGS(&adapter)) ==
                DXGI_ERROR_NOT_FOUND)
                break;
            DXGI_ADAPTER_DESC1 description{};
            adapter->GetDesc1(&description);
            if (description.VendorId != 0x10de || description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE)
                continue;
            if (SUCCEEDED(D3D12CreateDevice(
                    adapter.Get(), D3D_FEATURE_LEVEL_12_0, IID_PPV_ARGS(&device)))) {
                std::wcout << L"GPU: " << description.Description << std::endl;
                break;
            }
        }
        if (!device)
            throw std::runtime_error("NVIDIA D3D12 device unavailable");

        D3D12_COMMAND_QUEUE_DESC queueDescription{};
        queueDescription.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
        Check(device->CreateCommandQueue(&queueDescription, IID_PPV_ARGS(&queue)), "queue");
        Check(device->CreateCommandAllocator(queueDescription.Type, IID_PPV_ARGS(&allocator)), "allocator");
        Check(device->CreateCommandList(
                  0, queueDescription.Type, allocator.Get(), nullptr, IID_PPV_ARGS(&commands)),
              "commands");
        Check(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "fence");
        event = CreateEventW(nullptr, FALSE, FALSE, nullptr);
        if (!event)
            throw std::runtime_error("fence event");
    }

    void Submit()
    {
        Check(commands->Close(), "close");
        ID3D12CommandList* lists[] = {commands.Get()};
        queue->ExecuteCommandLists(1, lists);
        Check(queue->Signal(fence.Get(), ++serial), "signal");
        if (fence->GetCompletedValue() < serial) {
            Check(fence->SetEventOnCompletion(serial, event), "fence event");
            if (WaitForSingleObject(event, 30000) != WAIT_OBJECT_0)
                throw std::runtime_error("GPU fence timeout");
        }
    }

    void Reset()
    {
        Check(allocator->Reset(), "allocator reset");
        Check(commands->Reset(allocator.Get(), nullptr), "command reset");
    }

    ComPtr<ID3D12Resource> Buffer(
        UINT64 size, D3D12_HEAP_TYPE heapType, D3D12_RESOURCE_STATES state)
    {
        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = heapType;
        D3D12_RESOURCE_DESC description{};
        description.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER;
        description.Width = size;
        description.Height = 1;
        description.DepthOrArraySize = 1;
        description.MipLevels = 1;
        description.SampleDesc.Count = 1;
        description.Layout = D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> result;
        Check(device->CreateCommittedResource(
                  &heap,
                  D3D12_HEAP_FLAG_NONE,
                  &description,
                  state,
                  nullptr,
                  IID_PPV_ARGS(&result)),
              "buffer");
        return result;
    }

    void Barrier(ID3D12Resource* resource, D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after)
    {
        D3D12_RESOURCE_BARRIER barrier{};
        barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
        barrier.Transition = {
            resource, D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES, before, after};
        commands->ResourceBarrier(1, &barrier);
    }

    ComPtr<ID3D12Resource> Texture(
        UINT width,
        UINT height,
        DXGI_FORMAT format,
        const std::filesystem::path& raw = {})
    {
        D3D12_RESOURCE_DESC description{};
        description.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
        description.Width = width;
        description.Height = height;
        description.DepthOrArraySize = 1;
        description.MipLevels = 1;
        description.Format = format;
        description.SampleDesc.Count = 1;
        description.Flags = D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;

        D3D12_HEAP_PROPERTIES heap{};
        heap.Type = D3D12_HEAP_TYPE_DEFAULT;
        ComPtr<ID3D12Resource> result;
        Check(device->CreateCommittedResource(
                  &heap,
                  D3D12_HEAP_FLAG_NONE,
                  &description,
                  D3D12_RESOURCE_STATE_COMMON,
                  nullptr,
                  IID_PPV_ARGS(&result)),
              "texture");

        if (!raw.empty()) {
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
            UINT rows = 0;
            UINT64 rowBytes = 0;
            UINT64 total = 0;
            device->GetCopyableFootprints(
                &description, 0, 1, 0, &footprint, &rows, &rowBytes, &total);
            if (std::filesystem::file_size(raw) != rowBytes * rows)
                throw std::runtime_error("raw texture size mismatch: " + raw.string());

            auto upload = Buffer(total, D3D12_HEAP_TYPE_UPLOAD, D3D12_RESOURCE_STATE_GENERIC_READ);
            void* mapped = nullptr;
            D3D12_RANGE readRange{0, 0};
            Check(upload->Map(0, &readRange, &mapped), "upload map");
            std::ifstream file(raw, std::ios::binary);
            for (UINT row = 0; row < rows; ++row)
                file.read(
                    static_cast<char*>(mapped) + footprint.Offset + row * footprint.Footprint.RowPitch,
                    static_cast<std::streamsize>(rowBytes));
            if (!file)
                throw std::runtime_error("raw texture read failed: " + raw.string());
            upload->Unmap(0, nullptr);

            D3D12_TEXTURE_COPY_LOCATION destination{};
            destination.pResource = result.Get();
            destination.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            D3D12_TEXTURE_COPY_LOCATION source{};
            source.pResource = upload.Get();
            source.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
            source.PlacedFootprint = footprint;
            Barrier(result.Get(), D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_DEST);
            commands->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
            Barrier(result.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_COMMON);
            uploads.push_back(upload);
        }
        return result;
    }

    void Save(ID3D12Resource* texture, const std::filesystem::path& path)
    {
        Reset();
        const auto description = texture->GetDesc();
        D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
        UINT rows = 0;
        UINT64 rowBytes = 0;
        UINT64 total = 0;
        device->GetCopyableFootprints(
            &description, 0, 1, 0, &footprint, &rows, &rowBytes, &total);
        auto readback = Buffer(total, D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);

        D3D12_TEXTURE_COPY_LOCATION source{};
        source.pResource = texture;
        source.Type = D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION destination{};
        destination.pResource = readback.Get();
        destination.Type = D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination.PlacedFootprint = footprint;
        Barrier(texture, D3D12_RESOURCE_STATE_COMMON, D3D12_RESOURCE_STATE_COPY_SOURCE);
        commands->CopyTextureRegion(&destination, 0, 0, 0, &source, nullptr);
        Barrier(texture, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_COMMON);
        Submit();

        void* mapped = nullptr;
        D3D12_RANGE range{0, static_cast<SIZE_T>(total)};
        Check(readback->Map(0, &range, &mapped), "readback map");
        std::ofstream file(path, std::ios::binary);
        for (UINT row = 0; row < rows; ++row)
            file.write(
                static_cast<char*>(mapped) + footprint.Offset + row * footprint.Footprint.RowPitch,
                static_cast<std::streamsize>(rowBytes));
        readback->Unmap(0, nullptr);
        if (!file)
            throw std::runtime_error("output write failed: " + path.string());
    }
};

std::string ReadLine(std::ifstream& config, const char* name)
{
    std::string value;
    if (!std::getline(config, value) || value.empty())
        throw std::runtime_error(std::string("missing ") + name);
    return value;
}

FrameSpec ReadFrame(std::ifstream& config)
{
    FrameSpec frame;
    {
        std::istringstream line(ReadLine(config, "frame id"));
        if (!(line >> frame.frameId))
            throw std::runtime_error("invalid frame id");
    }
    for (std::size_t eye = 0; eye < frame.eyes.size(); ++eye) {
        auto& item = frame.eyes[eye];
        item.color = ReadLine(config, "color path");
        item.depth = ReadLine(config, "depth path");
        item.motion = ReadLine(config, "motion path");
        {
            std::istringstream line(ReadLine(config, "motion scale"));
            if (!(line >> item.motionScaleX >> item.motionScaleY))
                throw std::runtime_error("invalid motion scale");
        }
        item.output = ReadLine(config, "output path");
    }
    return frame;
}
} // namespace

int wmain(int argc, wchar_t** argv)
{
    try {
        if (argc != 2)
            throw std::runtime_error("Usage: teacher_sequence_bench.exe inputs.txt");
        std::ifstream config{std::filesystem::path(argv[1])};
        if (!config)
            throw std::runtime_error("cannot open config");

        std::istringstream header(ReadLine(config, "header"));
        UINT frameCount = 0;
        UINT colorWidth = 0;
        UINT colorHeight = 0;
        UINT inputWidth = 0;
        UINT inputHeight = 0;
        UINT outputWidth = 0;
        UINT outputHeight = 0;
        UINT guideWidth = 0;
        UINT guideHeight = 0;
        if (!(header >> frameCount >> colorWidth >> colorHeight >> inputWidth >> inputHeight >>
              outputWidth >> outputHeight >> guideWidth >> guideHeight) || frameCount == 0) {
            throw std::runtime_error(
                "header must contain frame_count color_width color_height input_width input_height "
                "output_width output_height guide_width guide_height");
        }

        const std::filesystem::path outputRoot = CheckedBenchmarkOutput(ReadLine(config, "output root"));
        const std::filesystem::path dllPath = ReadLine(config, "DLSS-NR DLL");
        const std::filesystem::path corePath = ReadLine(config, "NGX core");

        NeuralRendering::Tuning tuning;
        {
            std::istringstream line(ReadLine(config, "tuning"));
            unsigned autoMask = 0;
            unsigned uiCorrection = 0;
            if (!(line >> tuning.intensity >> tuning.localToneStrength >> tuning.localStructureStrength >>
                  tuning.skinStructureStrength >> tuning.style >> autoMask >> uiCorrection)) {
                throw std::runtime_error("tuning must contain intensity tone structure skin style auto_mask ui_correction");
            }
            tuning.useAutoMask = autoMask != 0;
            tuning.uiCorrection = uiCorrection != 0;
        }

        std::vector<FrameSpec> frames;
        frames.reserve(frameCount);
        for (UINT index = 0; index < frameCount; ++index)
            frames.push_back(ReadFrame(config));

        std::filesystem::create_directories(outputRoot);
        Bench bench;
        bench.Initialize();
        HMODULE core = LoadLibraryExW(
            corePath.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
        if (!core || !GetProcAddress(core, "NVSDK_NGX_D3D12_AllocateParameters"))
            throw std::runtime_error("driver NGX parameter API unavailable");

        auto& runtime = NeuralRendering::Runtime::Instance();
        if (!runtime.Probe(dllPath) || !runtime.Initialize(bench.device.Get(), outputRoot / "ngx"))
            throw std::runtime_error(runtime.Detail());
        std::cout << "Runtime " << runtime.Version() << " initialized" << std::endl;

        D3D12_QUERY_HEAP_DESC queryDescription{};
        queryDescription.Type = D3D12_QUERY_HEAP_TYPE_TIMESTAMP;
        queryDescription.Count = 4;
        ComPtr<ID3D12QueryHeap> queries;
        Check(bench.device->CreateQueryHeap(&queryDescription, IID_PPV_ARGS(&queries)), "timestamp heap");
        auto queryResult = bench.Buffer(
            4 * sizeof(UINT64), D3D12_HEAP_TYPE_READBACK, D3D12_RESOURCE_STATE_COPY_DEST);
        UINT64 frequency = 0;
        Check(bench.queue->GetTimestampFrequency(&frequency), "timestamp frequency");

        std::ofstream timings(outputRoot / "timings.csv");
        timings << "sequence_index,frame_id,warm,left_gpu_ms,right_gpu_ms,pair_gpu_ms,pair_wall_ms\n";

        for (std::size_t frameIndex = 0; frameIndex < frames.size(); ++frameIndex) {
            const auto& frame = frames[frameIndex];
            std::array<EyeResources, 2> resources;
            if (frameIndex != 0)
                bench.Reset();
            for (std::size_t eye = 0; eye < resources.size(); ++eye) {
                const auto& spec = frame.eyes[eye];
                resources[eye].color = bench.Texture(
                    colorWidth, colorHeight, DXGI_FORMAT_R8G8B8A8_UNORM, spec.color);
                resources[eye].depth = bench.Texture(
                    guideWidth, guideHeight, DXGI_FORMAT_R32_FLOAT, spec.depth);
                resources[eye].motion = bench.Texture(
                    guideWidth, guideHeight, DXGI_FORMAT_R16G16_FLOAT, spec.motion);
                resources[eye].output = bench.Texture(
                    outputWidth, outputHeight, DXGI_FORMAT_R8G8B8A8_UNORM);
            }
            bench.Submit();
            bench.uploads.clear();

            const auto started = std::chrono::steady_clock::now();
            bench.Reset();
            for (std::size_t eye = 0; eye < resources.size(); ++eye) {
                auto& item = resources[eye];
                const auto& spec = frame.eyes[eye];
                bench.Barrier(
                    item.color.Get(),
                    D3D12_RESOURCE_STATE_COMMON,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                bench.Barrier(
                    item.depth.Get(),
                    D3D12_RESOURCE_STATE_COMMON,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                bench.Barrier(
                    item.motion.Get(),
                    D3D12_RESOURCE_STATE_COMMON,
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
                bench.Barrier(
                    item.output.Get(),
                    D3D12_RESOURCE_STATE_COMMON,
                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
                bench.commands->EndQuery(
                    queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, static_cast<UINT>(eye * 2));
                if (!runtime.Execute(
                        bench.commands.Get(),
                        static_cast<std::uint32_t>(eye),
                        item.color.Get(),
                        item.depth.Get(),
                        item.motion.Get(),
                        item.output.Get(),
                        MakeBenchmarkGuide(inputWidth, inputHeight, outputWidth, outputHeight,
                            guideWidth, guideHeight, spec.motionScaleX, spec.motionScaleY),
                        tuning,
                        frameIndex == 0)) {
                    throw std::runtime_error(runtime.Detail());
                }
                bench.commands->EndQuery(
                    queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, static_cast<UINT>(eye * 2 + 1));
                bench.Barrier(
                    item.color.Get(),
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_COMMON);
                bench.Barrier(
                    item.depth.Get(),
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_COMMON);
                bench.Barrier(
                    item.motion.Get(),
                    D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE,
                    D3D12_RESOURCE_STATE_COMMON);
                bench.Barrier(
                    item.output.Get(),
                    D3D12_RESOURCE_STATE_UNORDERED_ACCESS,
                    D3D12_RESOURCE_STATE_COMMON);
            }
            bench.commands->ResolveQueryData(
                queries.Get(), D3D12_QUERY_TYPE_TIMESTAMP, 0, 4, queryResult.Get(), 0);
            bench.Submit();
            const double wall = std::chrono::duration<double, std::milli>(
                                    std::chrono::steady_clock::now() - started)
                                    .count();

            UINT64* timestamp = nullptr;
            D3D12_RANGE range{0, 4 * sizeof(UINT64)};
            Check(queryResult->Map(0, &range, reinterpret_cast<void**>(&timestamp)), "timestamp map");
            const double left = 1000.0 * (timestamp[1] - timestamp[0]) / frequency;
            const double right = 1000.0 * (timestamp[3] - timestamp[2]) / frequency;
            const double pair = 1000.0 * (timestamp[3] - timestamp[0]) / frequency;
            queryResult->Unmap(0, nullptr);
            timings << frameIndex << ',' << frame.frameId << ',' << 1 << ',' << left << ',' << right << ','
                    << pair << ',' << wall << '\n';
            timings.flush();

            for (std::size_t eye = 0; eye < resources.size(); ++eye) {
                std::filesystem::create_directories(frame.eyes[eye].output.parent_path());
                bench.Save(resources[eye].output.Get(), frame.eyes[eye].output);
                bench.uploads.clear();
            }
            std::cout << "frame " << frame.frameId << " pair GPU " << pair << " wall " << wall << std::endl;
        }

        std::ofstream meta(outputRoot / "runtime.txt");
        meta << runtime.Version() << "\n" << runtime.SuccessfulFrames() << "\n" << frequency << "\n";
        runtime.Shutdown();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAILED: " << error.what() << std::endl;
        return 1;
    }
}
