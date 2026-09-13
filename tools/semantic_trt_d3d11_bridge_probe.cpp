// Isolated native TensorRT/CUDA/D3D11 bridge probe.
//
// This deliberately does not link to or modify Community Shaders. It verifies
// the resource shape needed by a future opt-in renderer backend: D3D11 buffers
// are registered with CUDA, their mapped device pointers are bound to the
// fixed FP16 TensorRT engine, and recurrent state remains device-resident.

#include <NvInferRuntime.h>
#include <cuda_d3d11_interop.h>
#include <cuda_runtime_api.h>

#include <d3d11.h>
#include <dxgi.h>
#include <wrl/client.h>

#define NOMINMAX
#include <Windows.h>

#ifdef min
#undef min
#endif
#ifdef max
#undef max
#endif

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

namespace
{
    using Microsoft::WRL::ComPtr;

    class Logger final : public nvinfer1::ILogger
    {
    public:
        void log(Severity severity, nvinfer1::AsciiChar const* message) noexcept override
        {
            if (severity <= Severity::kWARNING && message)
                std::cerr << "[TensorRT] " << message << '\n';
        }
    };

    class CudaGuard
    {
    public:
        static void Check(cudaError_t error, const char* operation)
        {
            if (error != cudaSuccess)
                throw std::runtime_error(std::string(operation) + ": " + cudaGetErrorString(error));
        }
    };

    struct MappedBuffer
    {
        ComPtr<ID3D11Buffer> resource;
        cudaGraphicsResource* graphics = nullptr;
        std::size_t bytes = 0;
        void* devicePointer = nullptr;

        MappedBuffer() = default;
        MappedBuffer(const MappedBuffer&) = delete;
        MappedBuffer& operator=(const MappedBuffer&) = delete;
        MappedBuffer(MappedBuffer&& other) noexcept
            : resource(std::move(other.resource)), graphics(other.graphics), bytes(other.bytes), devicePointer(other.devicePointer)
        {
            other.graphics = nullptr;
            other.devicePointer = nullptr;
            other.bytes = 0;
        }
        MappedBuffer& operator=(MappedBuffer&& other) noexcept
        {
            if (this != &other) {
                Reset();
                resource = std::move(other.resource);
                graphics = other.graphics;
                bytes = other.bytes;
                devicePointer = other.devicePointer;
                other.graphics = nullptr;
                other.devicePointer = nullptr;
                other.bytes = 0;
            }
            return *this;
        }
        ~MappedBuffer() { Reset(); }

        void Reset()
        {
            if (graphics) {
                cudaGraphicsUnregisterResource(graphics);
                graphics = nullptr;
            }
            devicePointer = nullptr;
            resource.Reset();
            bytes = 0;
        }
    };

    struct EngineShape
    {
        std::string name;
        std::size_t elements = 0;
        std::size_t bytes = 0;
    };

    std::vector<std::uint8_t> ReadFile(const wchar_t* path)
    {
        std::ifstream input(path, std::ios::binary | std::ios::ate);
        if (!input)
            throw std::runtime_error("could not open engine");
        const auto size = input.tellg();
        input.seekg(0);
        std::vector<std::uint8_t> data(static_cast<std::size_t>(size));
        input.read(reinterpret_cast<char*>(data.data()), size);
        if (!input)
            throw std::runtime_error("could not read engine");
        return data;
    }

    std::size_t ElementCount(nvinfer1::Dims dims)
    {
        std::size_t count = 1;
        for (int32_t index = 0; index < dims.nbDims; ++index) {
            if (dims.d[index] <= 0)
                throw std::runtime_error("dynamic or invalid engine tensor shape");
            count *= static_cast<std::size_t>(dims.d[index]);
        }
        return count;
    }

    std::string DimsString(nvinfer1::Dims dims)
    {
        std::string value = "[";
        for (int32_t index = 0; index < dims.nbDims; ++index) {
            if (index)
                value += ',';
            value += std::to_string(dims.d[index]);
        }
        value += ']';
        return value;
    }

    MappedBuffer CreateMappedBuffer(ID3D11Device* device, std::size_t bytes, const char* name)
    {
        if (!device || bytes == 0)
            throw std::runtime_error(std::string("invalid buffer size for ") + name);
        if (bytes > std::numeric_limits<UINT>::max())
            throw std::runtime_error(std::string("buffer too large for ") + name);

        D3D11_BUFFER_DESC description{};
        description.ByteWidth = static_cast<UINT>(bytes);
        description.Usage = D3D11_USAGE_DEFAULT;
        description.BindFlags = 0;
        description.CPUAccessFlags = 0;
        description.MiscFlags = D3D11_RESOURCE_MISC_SHARED;
        description.StructureByteStride = 0;

        MappedBuffer result;
        HRESULT hr = device->CreateBuffer(&description, nullptr, result.resource.GetAddressOf());
        if (FAILED(hr))
            throw std::runtime_error(std::string("D3D11 CreateBuffer failed for ") + name);

        CudaGuard::Check(cudaGraphicsD3D11RegisterResource(
                             &result.graphics, result.resource.Get(), cudaGraphicsRegisterFlagsNone),
            "cudaGraphicsD3D11RegisterResource");
        result.bytes = bytes;
        return result;
    }

    void MapBuffers(cudaStream_t stream, std::vector<MappedBuffer*>& buffers)
    {
        std::vector<cudaGraphicsResource*> resources;
        resources.reserve(buffers.size());
        for (auto* buffer : buffers)
            resources.push_back(buffer->graphics);
        CudaGuard::Check(cudaGraphicsMapResources(static_cast<int>(resources.size()), resources.data(), stream),
            "cudaGraphicsMapResources");
        for (auto* buffer : buffers) {
            std::size_t mappedBytes = 0;
            CudaGuard::Check(cudaGraphicsResourceGetMappedPointer(&buffer->devicePointer, &mappedBytes, buffer->graphics),
                "cudaGraphicsResourceGetMappedPointer");
            if (mappedBytes < buffer->bytes)
                throw std::runtime_error("mapped D3D11 buffer is smaller than the engine tensor");
        }
    }

    void UnmapBuffers(cudaStream_t stream, const std::vector<MappedBuffer*>& buffers)
    {
        std::vector<cudaGraphicsResource*> resources;
        resources.reserve(buffers.size());
        for (auto* buffer : buffers)
            resources.push_back(buffer->graphics);
        CudaGuard::Check(cudaGraphicsUnmapResources(static_cast<int>(resources.size()), resources.data(), stream),
            "cudaGraphicsUnmapResources");
        for (auto* buffer : buffers)
            buffer->devicePointer = nullptr;
    }

    std::uint64_t NowNanoseconds()
    {
        return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count());
    }

    double Percentile(std::vector<double> values, double percentile)
    {
        if (values.empty())
            return 0.0;
        std::sort(values.begin(), values.end());
        const double position = (values.size() - 1) * percentile;
        const auto lower = static_cast<std::size_t>(position);
        const auto upper = std::min(lower + 1, values.size() - 1);
        return values[lower] + (values[upper] - values[lower]) * (position - lower);
    }
}

int wmain(int argc, wchar_t** argv)
{
    if (argc != 3) {
        std::wcerr << L"usage: semantic_trt_d3d11_bridge_probe.exe <nvinfer_10.dll> <engine>\n";
        return 2;
    }

    HMODULE tensorRtModule = nullptr;
    nvinfer1::IRuntime* runtime = nullptr;
    nvinfer1::ICudaEngine* engine = nullptr;
    nvinfer1::IExecutionContext* execution = nullptr;
    ComPtr<ID3D11Device> device;
    ComPtr<ID3D11DeviceContext> context;
    cudaStream_t stream = nullptr;
    std::vector<MappedBuffer> ownedBuffers;
    std::vector<MappedBuffer*> mappedBuffers;

    try {
        D3D_FEATURE_LEVEL featureLevel{};
        const D3D_FEATURE_LEVEL levels[] = { D3D_FEATURE_LEVEL_12_0, D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
        UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
        HRESULT hr = D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, flags,
            levels, static_cast<UINT>(std::size(levels)), D3D11_SDK_VERSION,
            device.GetAddressOf(), &featureLevel, context.GetAddressOf());
        if (FAILED(hr))
            throw std::runtime_error("D3D11CreateDevice failed");
        if (featureLevel < D3D_FEATURE_LEVEL_11_0)
            throw std::runtime_error("D3D11 feature level 11.0 is required");

        CudaGuard::Check(cudaD3D11SetDirect3DDevice(device.Get()), "cudaD3D11SetDirect3DDevice");
        CudaGuard::Check(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");

        const auto engineBlob = ReadFile(argv[2]);
        tensorRtModule = LoadLibraryW(argv[1]);
        if (!tensorRtModule)
            throw std::runtime_error("LoadLibraryW failed for TensorRT");
        using CreateRuntime = void*(__cdecl*)(void*, std::int32_t) noexcept;
        auto create = reinterpret_cast<CreateRuntime>(GetProcAddress(tensorRtModule, "createInferRuntime_INTERNAL"));
        if (!create)
            throw std::runtime_error("createInferRuntime_INTERNAL is missing");

        Logger logger;
        runtime = static_cast<nvinfer1::IRuntime*>(create(&logger, NV_TENSORRT_VERSION));
        if (!runtime)
            throw std::runtime_error("TensorRT runtime creation failed");
        engine = runtime->deserializeCudaEngine(engineBlob.data(), engineBlob.size());
        if (!engine)
            throw std::runtime_error("TensorRT engine deserialization failed");
        execution = engine->createExecutionContext();
        if (!execution)
            throw std::runtime_error("TensorRT execution context creation failed");

        std::unordered_map<std::string, EngineShape> shapes;
        for (int32_t index = 0; index < engine->getNbIOTensors(); ++index) {
            const char* name = engine->getIOTensorName(index);
            const auto mode = engine->getTensorIOMode(name);
            const auto dtype = engine->getTensorDataType(name);
            if (dtype != nvinfer1::DataType::kHALF)
                throw std::runtime_error(std::string("engine tensor is not FP16: ") + name);
            const auto dims = engine->getTensorShape(name);
            shapes.emplace(name, EngineShape{ name, ElementCount(dims), ElementCount(dims) * sizeof(std::uint16_t) });
            std::cout << "tensor=" << name << " mode="
                      << (mode == nvinfer1::TensorIOMode::kINPUT ? "input" : "output")
                      << " shape=" << DimsString(dims) << " bytes=" << ElementCount(dims) * sizeof(std::uint16_t) << '\n';
        }

        const char* required[] = {
            "rgb", "guides", "context", "hidden", "previous",
            "prediction", "next_hidden", "next_previous"
        };
        for (const auto* name : required) {
            if (!shapes.contains(name))
                throw std::runtime_error(std::string("required engine tensor is missing: ") + name);
        }

        const std::pair<const char*, const char*> bufferSpecs[] = {
            { "rgb", "rgb" },
            { "guides", "guides" },
            { "context", "context" },
            { "prediction", "prediction" },
            { "hiddenA", "hidden" },
            { "hiddenB", "hidden" },
            { "previousA", "previous" },
            { "previousB", "previous" },
        };
        std::unordered_map<std::string, MappedBuffer*> buffers;
        ownedBuffers.reserve(std::size(bufferSpecs));
        for (const auto& [label, shapeName] : bufferSpecs) {
            ownedBuffers.push_back(CreateMappedBuffer(device.Get(), shapes.at(shapeName).bytes, label));
            buffers.emplace(label, &ownedBuffers.back());
        }
        mappedBuffers.reserve(ownedBuffers.size());
        for (auto& buffer : ownedBuffers)
            mappedBuffers.push_back(&buffer);

        std::vector<MappedBuffer*> allBuffers = mappedBuffers;

        auto bind = [&](MappedBuffer* hiddenInput, MappedBuffer* previousInput,
                        MappedBuffer* hiddenOutput, MappedBuffer* previousOutput) {
            const std::pair<const char*, void*> addresses[] = {
                { "rgb", buffers.at("rgb")->devicePointer },
                { "guides", buffers.at("guides")->devicePointer },
                { "context", buffers.at("context")->devicePointer },
                { "hidden", hiddenInput->devicePointer },
                { "previous", previousInput->devicePointer },
                { "prediction", buffers.at("prediction")->devicePointer },
                { "next_hidden", hiddenOutput->devicePointer },
                { "next_previous", previousOutput->devicePointer },
            };
            for (const auto& [name, address] : addresses) {
                if (!execution->setTensorAddress(name, address))
                    throw std::runtime_error(std::string("setTensorAddress failed: ") + name);
            }
        };

        auto executeFrame = [&](MappedBuffer* hiddenInput, MappedBuffer* previousInput,
                                MappedBuffer* hiddenOutput, MappedBuffer* previousOutput,
                                bool resetState) {
            const auto start = NowNanoseconds();
            MapBuffers(stream, allBuffers);
            bind(hiddenInput, previousInput, hiddenOutput, previousOutput);
            if (resetState) {
                CudaGuard::Check(cudaMemsetAsync(buffers.at("rgb")->devicePointer, 0, shapes.at("rgb").bytes, stream), "zero rgb");
                CudaGuard::Check(cudaMemsetAsync(buffers.at("guides")->devicePointer, 0, shapes.at("guides").bytes, stream), "zero guides");
                CudaGuard::Check(cudaMemsetAsync(buffers.at("context")->devicePointer, 0, shapes.at("context").bytes, stream), "zero context");
                CudaGuard::Check(cudaMemsetAsync(hiddenInput->devicePointer, 0, shapes.at("hidden").bytes, stream), "zero hidden");
                CudaGuard::Check(cudaMemsetAsync(previousInput->devicePointer, 0, shapes.at("previous").bytes, stream), "zero previous");
            }
            if (!execution->enqueueV3(stream))
                throw std::runtime_error("TensorRT enqueueV3 failed");
            CudaGuard::Check(cudaStreamSynchronize(stream), "frame synchronization");
            UnmapBuffers(stream, allBuffers);
            return static_cast<double>(NowNanoseconds() - start) / 1'000'000.0;
        };

        MappedBuffer* hiddenInput = buffers.at("hiddenA");
        MappedBuffer* hiddenOutput = buffers.at("hiddenB");
        MappedBuffer* previousInput = buffers.at("previousA");
        MappedBuffer* previousOutput = buffers.at("previousB");

        const double firstResetMs = executeFrame(hiddenInput, previousInput, hiddenOutput, previousOutput, true);
        std::swap(hiddenInput, hiddenOutput);
        std::swap(previousInput, previousOutput);

        const std::size_t warmup = 5;
        const std::size_t iterations = 40;
        std::vector<double> warmupTimings;
        warmupTimings.reserve(warmup);
        for (std::size_t index = 0; index < warmup; ++index) {
            warmupTimings.push_back(executeFrame(hiddenInput, previousInput, hiddenOutput, previousOutput, false));
            std::swap(hiddenInput, hiddenOutput);
            std::swap(previousInput, previousOutput);
        }

        std::vector<double> timings;
        timings.reserve(iterations);
        for (std::size_t index = 0; index < iterations; ++index) {
            timings.push_back(executeFrame(hiddenInput, previousInput, hiddenOutput, previousOutput, false));
            std::swap(hiddenInput, hiddenOutput);
            std::swap(previousInput, previousOutput);
        }

        std::vector<std::uint16_t> prediction(shapes.at("prediction").elements);
        MapBuffers(stream, allBuffers);
        CudaGuard::Check(cudaMemcpyAsync(prediction.data(), buffers.at("prediction")->devicePointer,
                            shapes.at("prediction").bytes, cudaMemcpyDeviceToHost, stream),
            "copy prediction");
        CudaGuard::Check(cudaStreamSynchronize(stream), "prediction synchronization");
        UnmapBuffers(stream, allBuffers);
        const bool finite = std::all_of(prediction.begin(), prediction.end(), [](std::uint16_t bits) {
            return ((bits >> 10) & 0x1F) != 0x1F;
        });

        const auto minmax = std::minmax_element(timings.begin(), timings.end());
        const auto warmupMinmax = std::minmax_element(warmupTimings.begin(), warmupTimings.end());
        std::cout << "d3d11_cuda_tensorrt_bridge=passed\n";
        std::cout << "feature_level=" << std::hex << static_cast<unsigned>(featureLevel) << std::dec << '\n';
        std::cout << "first_reset_ms=" << firstResetMs << '\n';
        std::cout << "warmup_median_ms=" << Percentile(warmupTimings, 0.50) << '\n';
        std::cout << "iterations=" << iterations << '\n';
        std::cout << "steady_median_ms=" << Percentile(timings, 0.50) << '\n';
        std::cout << "steady_p95_ms=" << Percentile(timings, 0.95) << '\n';
        std::cout << "steady_p99_ms=" << Percentile(timings, 0.99) << '\n';
        std::cout << "steady_min_ms=" << *minmax.first << '\n';
        std::cout << "steady_max_ms=" << *minmax.second << '\n';
        std::cout << "prediction_finite=" << (finite ? "true" : "false") << '\n';

        cudaStreamDestroy(stream);
        stream = nullptr;
        delete execution;
        delete engine;
        delete runtime;
        FreeLibrary(tensorRtModule);
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "d3d11_cuda_tensorrt_bridge=failed: " << error.what() << '\n';
        if (stream) {
            cudaStreamSynchronize(stream);
            if (!mappedBuffers.empty())
                UnmapBuffers(stream, mappedBuffers);
            cudaStreamDestroy(stream);
        }
        delete execution;
        delete engine;
        delete runtime;
        if (tensorRtModule)
            FreeLibrary(tensorRtModule);
        return 1;
    }
}
