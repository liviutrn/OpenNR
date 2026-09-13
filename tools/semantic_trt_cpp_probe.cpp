// Isolated TensorRT C++ runtime probe for an already-built semantic engine.
//
// This intentionally does not link against or modify Community Shaders.  It
// verifies that the serialized engine can be loaded through the native
// TensorRT ABI and that its fixed FP16 I/O contract is visible to a future
// CUDA/D3D11 bridge.

#include <NvInferRuntime.h>

#include <Windows.h>

#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

namespace
{
    class Logger final : public nvinfer1::ILogger
    {
    public:
        void log(Severity severity, nvinfer1::AsciiChar const* message) noexcept override
        {
            if (severity <= Severity::kWARNING && message)
                std::cerr << "[TensorRT] " << message << '\n';
        }
    };

    const char* DataTypeName(nvinfer1::DataType type)
    {
        switch (type) {
        case nvinfer1::DataType::kFLOAT:
            return "FP32";
        case nvinfer1::DataType::kHALF:
            return "FP16";
        case nvinfer1::DataType::kINT8:
            return "INT8";
        case nvinfer1::DataType::kINT32:
            return "INT32";
        case nvinfer1::DataType::kBOOL:
            return "BOOL";
        case nvinfer1::DataType::kUINT8:
            return "UINT8";
        default:
            return "OTHER";
        }
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
}

int wmain(int argc, wchar_t** argv)
{
    if (argc != 3) {
        std::wcerr << L"usage: semantic_trt_cpp_probe.exe <nvinfer_10.dll> <engine>\n";
        return 2;
    }

    std::ifstream input(argv[2], std::ios::binary | std::ios::ate);
    if (!input) {
        std::wcerr << L"could not open engine: " << argv[2] << '\n';
        return 3;
    }
    const auto size = input.tellg();
    input.seekg(0);
    std::vector<std::uint8_t> blob(static_cast<std::size_t>(size));
    input.read(reinterpret_cast<char*>(blob.data()), size);
    if (!input) {
        std::wcerr << L"could not read engine\n";
        return 4;
    }

    HMODULE module = LoadLibraryW(argv[1]);
    if (!module) {
        std::wcerr << L"LoadLibraryW failed for TensorRT: " << GetLastError() << '\n';
        return 5;
    }
    using CreateRuntime = void*(__cdecl*)(void*, std::int32_t) noexcept;
    auto create = reinterpret_cast<CreateRuntime>(GetProcAddress(module, "createInferRuntime_INTERNAL"));
    if (!create) {
        std::cerr << "createInferRuntime_INTERNAL is missing\n";
        FreeLibrary(module);
        return 6;
    }

    Logger logger;
    auto* runtime = static_cast<nvinfer1::IRuntime*>(create(&logger, NV_TENSORRT_VERSION));
    if (!runtime) {
        std::cerr << "TensorRT runtime creation failed\n";
        FreeLibrary(module);
        return 7;
    }
    auto* engine = runtime->deserializeCudaEngine(blob.data(), blob.size());
    if (!engine) {
        std::cerr << "TensorRT engine deserialization failed\n";
        delete runtime;
        FreeLibrary(module);
        return 8;
    }

    std::cout << "tensorrt_cpp_probe=passed\n";
    std::cout << "tensorrt_header_version=" << NV_TENSORRT_MAJOR << '.' << NV_TENSORRT_MINOR << '.'
              << NV_TENSORRT_PATCH << "\n";
    std::cout << "io_tensor_count=" << engine->getNbIOTensors() << "\n";
    for (int32_t index = 0; index < engine->getNbIOTensors(); ++index) {
        const char* name = engine->getIOTensorName(index);
        const auto mode = engine->getTensorIOMode(name);
        std::cout << "tensor=" << name << " mode="
                  << (mode == nvinfer1::TensorIOMode::kINPUT ? "input" : "output")
                  << " dtype=" << DataTypeName(engine->getTensorDataType(name))
                  << " shape=" << DimsString(engine->getTensorShape(name)) << '\n';
    }

    delete engine;
    delete runtime;
    FreeLibrary(module);
    return 0;
}
