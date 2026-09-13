#include <cuda_fp16.h>
#include <cuda_runtime.h>
#include <cublas_v2.h>
#include <mma.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

constexpr int kChannels = 32;
constexpr int kHidden = 128;
constexpr int kThreads = 256;
constexpr int kWmmaTile = 16;

void check_cuda(cudaError_t status, const char* expression) {
    if (status != cudaSuccess) {
        std::cerr << expression << " failed: " << cudaGetErrorString(status) << '\n';
        std::exit(2);
    }
}

void check_cublas(cublasStatus_t status, const char* expression) {
    if (status != CUBLAS_STATUS_SUCCESS) {
        std::cerr << expression << " failed: cublas status " << static_cast<int>(status) << '\n';
        std::exit(3);
    }
}

void load_binary(const std::string& path, void* destination, std::size_t bytes) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        std::cerr << "cannot open " << path << '\n';
        std::exit(4);
    }
    input.read(static_cast<char*>(destination), static_cast<std::streamsize>(bytes));
    if (input.gcount() != static_cast<std::streamsize>(bytes)) {
        std::cerr << "short read for " << path << ": expected " << bytes
                  << " bytes, got " << input.gcount() << '\n';
        std::exit(5);
    }
}

void save_binary(const std::string& path, const void* source, std::size_t bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        std::cerr << "cannot open output " << path << '\n';
        std::exit(6);
    }
    output.write(static_cast<const char*>(source), static_cast<std::streamsize>(bytes));
    if (!output) {
        std::cerr << "short write for " << path << '\n';
        std::exit(7);
    }
}

__global__ void fill_half_kernel(__half* output, std::size_t count, __half value) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index < count) {
        output[index] = value;
    }
}

// This preserves the observed cubic shape and half boundaries sufficiently for
// a runtime-cost probe. It intentionally does not claim bit-exact native parity.
__device__ __forceinline__ __half cubic_approx(__half input) {
    const __half minus_four = __float2half(-4.0f);
    const __half plus_four = __float2half(4.0f);
    const __half t = __hmin(__hmax(input, minus_four), plus_four);
    const __half p = __hfma(__hneg(__habs(t)), __float2half(0.055908203125f), __float2half(0.447265625f));
    const __half v = __hfma(t, p, __float2half(0.89453125f));
    return __hmul(input, v);
}

__global__ void cubic_kernel(__half* hidden, std::size_t count) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    if (index < count) {
        hidden[index] = cubic_approx(hidden[index]);
    }
}

__global__ void residual_kernel(const __half* input,
                                const __half* contracted,
                                const __half* skip,
                                __half* output,
                                std::size_t tokens) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x + threadIdx.x;
    const std::size_t count = tokens * kChannels;
    if (index < count) {
        const int channel = static_cast<int>(index % kChannels);
        output[index] = __hadd(contracted[index], __hmul(input[index], skip[channel]));
    }
}

// One-block-per-16-token C32 block. This is a deliberately small CUDA proof of
// the fusion shape used by the public Triton adapter: two WMMA GEMMs, the cubic
// boundary, and the residual write share one launch and fixed shared memory.
// It is a speed experiment, not an exact native-reproduction implementation.
__global__ __launch_bounds__(kThreads) void fused_c32_wmma_kernel(
    const __half* __restrict__ input,
    const __half* __restrict__ expansion,
    const __half* __restrict__ contraction,
    const __half* __restrict__ skip,
    __half* __restrict__ output,
    std::size_t tokens) {
    __shared__ __half shared_input[kWmmaTile * kChannels];
    __shared__ float shared_hidden_acc[kWmmaTile * kHidden];
    __shared__ __half shared_hidden[kWmmaTile * kHidden];
    __shared__ float shared_output_acc[kWmmaTile * kChannels];

    const std::size_t first_row = static_cast<std::size_t>(blockIdx.x) * kWmmaTile;
    for (int index = threadIdx.x; index < kWmmaTile * kChannels; index += blockDim.x) {
        const std::size_t row = first_row + static_cast<std::size_t>(index / kChannels);
        const int channel = index % kChannels;
        shared_input[index] = row < tokens ? input[row * kChannels + channel] : __float2half(0.0f);
    }
    __syncthreads();

    const int warp = threadIdx.x / 32;
    if (warp < 8) {
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, kWmmaTile, kWmmaTile, kWmmaTile,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, kWmmaTile, kWmmaTile, kWmmaTile,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, kWmmaTile, kWmmaTile, kWmmaTile,
                               float> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, 0.0f);
        const int output_tile = warp;
        for (int k_tile = 0; k_tile < 2; ++k_tile) {
            nvcuda::wmma::load_matrix_sync(a, shared_input + k_tile * kWmmaTile, kChannels);
            nvcuda::wmma::load_matrix_sync(
                b, expansion + k_tile * kWmmaTile * kHidden + output_tile * kWmmaTile, kHidden);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        nvcuda::wmma::store_matrix_sync(
            shared_hidden_acc + output_tile * kWmmaTile, accumulator, kHidden,
            nvcuda::wmma::mem_row_major);
    }
    __syncthreads();

    for (int index = threadIdx.x; index < kWmmaTile * kHidden; index += blockDim.x) {
        shared_hidden[index] = cubic_approx(__float2half(shared_hidden_acc[index]));
    }
    __syncthreads();

    if (warp < 2) {
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, kWmmaTile, kWmmaTile, kWmmaTile,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, kWmmaTile, kWmmaTile, kWmmaTile,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, kWmmaTile, kWmmaTile, kWmmaTile,
                               float> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, 0.0f);
        const int output_tile = warp;
        for (int k_tile = 0; k_tile < 8; ++k_tile) {
            nvcuda::wmma::load_matrix_sync(a, shared_hidden + k_tile * kWmmaTile, kHidden);
            nvcuda::wmma::load_matrix_sync(
                b, contraction + k_tile * kWmmaTile * kChannels + output_tile * kWmmaTile, kChannels);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        nvcuda::wmma::store_matrix_sync(
            shared_output_acc + output_tile * kWmmaTile, accumulator, kChannels,
            nvcuda::wmma::mem_row_major);
    }
    __syncthreads();

    for (int index = threadIdx.x; index < kWmmaTile * kChannels; index += blockDim.x) {
        const std::size_t row = first_row + static_cast<std::size_t>(index / kChannels);
        const int channel = index % kChannels;
        if (row < tokens) {
            const __half residual = __hmul(shared_input[index], skip[channel]);
            output[row * kChannels + channel] = __hadd(__float2half(shared_output_acc[index]), residual);
        }
    }
}

void launch_fill(__half* output, std::size_t count, float value, cudaStream_t stream) {
    const int blocks = static_cast<int>((count + kThreads - 1) / kThreads);
    fill_half_kernel<<<blocks, kThreads, 0, stream>>>(output, count, __float2half(value));
    check_cuda(cudaGetLastError(), "fill_half_kernel");
}

void launch_cubic(__half* hidden, std::size_t count, cudaStream_t stream) {
    const int blocks = static_cast<int>((count + kThreads - 1) / kThreads);
    cubic_kernel<<<blocks, kThreads, 0, stream>>>(hidden, count);
    check_cuda(cudaGetLastError(), "cubic_kernel");
}

void launch_residual(const __half* input,
                     const __half* contracted,
                     const __half* skip,
                     __half* output,
                     std::size_t tokens,
                     cudaStream_t stream) {
    const std::size_t count = tokens * kChannels;
    const int blocks = static_cast<int>((count + kThreads - 1) / kThreads);
    residual_kernel<<<blocks, kThreads, 0, stream>>>(input, contracted, skip, output, tokens);
    check_cuda(cudaGetLastError(), "residual_kernel");
}

void launch_fused_wmma(const __half* input,
                       const __half* expansion,
                       const __half* contraction,
                       const __half* skip,
                       __half* output,
                       std::size_t tokens,
                       cudaStream_t stream) {
    const int blocks = static_cast<int>((tokens + kWmmaTile - 1) / kWmmaTile);
    fused_c32_wmma_kernel<<<blocks, kThreads, 0, stream>>>(
        input, expansion, contraction, skip, output, tokens);
    check_cuda(cudaGetLastError(), "fused_c32_wmma_kernel");
}

void run_mlp(cublasHandle_t handle,
             const __half* input,
             const __half* expansion,
             const __half* contraction,
             const __half* skip,
             __half* hidden,
             __half* output,
             std::size_t tokens,
             cudaStream_t stream) {
    const int m = kHidden;
    const int n = static_cast<int>(tokens);
    const int k = kChannels;
    const float alpha = 1.0f;
    const float beta = 0.0f;
    check_cublas(cublasGemmEx(handle,
                              CUBLAS_OP_N,
                              CUBLAS_OP_N,
                              m,
                              n,
                              k,
                              &alpha,
                              expansion,
                              CUDA_R_16F,
                              m,
                              input,
                              CUDA_R_16F,
                              k,
                              &beta,
                              hidden,
                              CUDA_R_16F,
                              m,
                              CUBLAS_COMPUTE_32F,
                              CUBLAS_GEMM_DEFAULT_TENSOR_OP),
                "cublasGemmEx(expansion)");
    launch_cubic(hidden, tokens * kHidden, stream);
    check_cublas(cublasGemmEx(handle,
                              CUBLAS_OP_N,
                              CUBLAS_OP_N,
                              kChannels,
                              n,
                              kHidden,
                              &alpha,
                              contraction,
                              CUDA_R_16F,
                              kChannels,
                              hidden,
                              CUDA_R_16F,
                              kHidden,
                              &beta,
                              output,
                              CUDA_R_16F,
                              kChannels,
                              CUBLAS_COMPUTE_32F,
                              CUBLAS_GEMM_DEFAULT_TENSOR_OP),
                "cublasGemmEx(contraction)");
    launch_residual(input, output, skip, output, tokens, stream);
}

float time_direct(cublasHandle_t handle,
                  const __half* input,
                  const __half* expansion,
                  const __half* contraction,
                  const __half* skip,
                  __half* hidden,
                  __half* output,
                  std::size_t tokens,
                  int iterations,
                  cudaStream_t stream) {
    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(direct start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(direct stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(direct start)");
    for (int i = 0; i < iterations; ++i) {
        run_mlp(handle, input, expansion, contraction, skip, hidden, output, tokens, stream);
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(direct stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(direct stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop), "cudaEventElapsedTime(direct)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    return elapsed / iterations;
}

float time_graph(cublasHandle_t handle,
                 const __half* input,
                 const __half* expansion,
                 const __half* contraction,
                 const __half* skip,
                 __half* hidden,
                 __half* output,
                 std::size_t tokens,
                 int iterations,
                 cudaStream_t stream) {
    check_cuda(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal), "cudaStreamBeginCapture");
    run_mlp(handle, input, expansion, contraction, skip, hidden, output, tokens, stream);
    cudaGraph_t graph = nullptr;
    check_cuda(cudaStreamEndCapture(stream, &graph), "cudaStreamEndCapture");
    cudaGraphExec_t executable = nullptr;
    check_cuda(cudaGraphInstantiate(&executable, graph, nullptr, nullptr, 0), "cudaGraphInstantiate");
    check_cuda(cudaGraphLaunch(executable, stream), "cudaGraphLaunch(warmup)");
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(graph warmup)");

    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(graph start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(graph stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(graph start)");
    for (int i = 0; i < iterations; ++i) {
        check_cuda(cudaGraphLaunch(executable, stream), "cudaGraphLaunch");
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(graph stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(graph stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop), "cudaEventElapsedTime(graph)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    cudaGraphExecDestroy(executable);
    cudaGraphDestroy(graph);
    return elapsed / iterations;
}

float time_fused_wmma(const __half* input,
                      const __half* expansion,
                      const __half* contraction,
                      const __half* skip,
                      __half* output,
                      std::size_t tokens,
                      int iterations,
                      cudaStream_t stream) {
    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(fused start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(fused stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(fused start)");
    for (int i = 0; i < iterations; ++i) {
        launch_fused_wmma(input, expansion, contraction, skip, output, tokens, stream);
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(fused stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(fused stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop), "cudaEventElapsedTime(fused)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    return elapsed / iterations;
}

float time_fused_wmma_graph(const __half* input,
                            const __half* expansion,
                            const __half* contraction,
                            const __half* skip,
                            __half* output,
                            std::size_t tokens,
                            int iterations,
                            cudaStream_t stream) {
    check_cuda(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal), "cudaStreamBeginCapture(fused)");
    launch_fused_wmma(input, expansion, contraction, skip, output, tokens, stream);
    cudaGraph_t graph = nullptr;
    check_cuda(cudaStreamEndCapture(stream, &graph), "cudaStreamEndCapture(fused)");
    cudaGraphExec_t executable = nullptr;
    check_cuda(cudaGraphInstantiate(&executable, graph, nullptr, nullptr, 0), "cudaGraphInstantiate(fused)");
    check_cuda(cudaGraphLaunch(executable, stream), "cudaGraphLaunch(fused warmup)");
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(fused warmup)");

    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(fused graph start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(fused graph stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(fused graph start)");
    for (int i = 0; i < iterations; ++i) {
        check_cuda(cudaGraphLaunch(executable, stream), "cudaGraphLaunch(fused)");
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(fused graph stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(fused graph stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop), "cudaEventElapsedTime(fused graph)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    cudaGraphExecDestroy(executable);
    cudaGraphDestroy(graph);
    return elapsed / iterations;
}

}  // namespace

int main(int argc, char** argv) {
    const std::size_t tokens = argc > 1 ? static_cast<std::size_t>(std::stoull(argv[1])) : static_cast<std::size_t>(1920) * 1080;
    const int iterations = argc > 2 ? std::max(1, std::atoi(argv[2])) : 20;
    const std::string data_directory = argc > 3 ? argv[3] : "";
    const std::string output_path = argc > 4 ? argv[4] : "";
    if (tokens == 0 || tokens > static_cast<std::size_t>(std::numeric_limits<int>::max())) {
        std::cerr << "tokens must fit in a positive 32-bit cuBLAS dimension\n";
        return 1;
    }

    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, 0), "cudaGetDeviceProperties");
    cudaStream_t stream = nullptr;
    check_cuda(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking), "cudaStreamCreateWithFlags");

    cublasHandle_t handle = nullptr;
    check_cublas(cublasCreate(&handle), "cublasCreate");
    check_cublas(cublasSetStream(handle, stream), "cublasSetStream");
    check_cublas(cublasSetMathMode(handle, CUBLAS_TENSOR_OP_MATH), "cublasSetMathMode");

    const std::size_t input_count = tokens * kChannels;
    const std::size_t hidden_count = tokens * kHidden;
    __half* input = nullptr;
    __half* expansion = nullptr;
    __half* contraction = nullptr;
    __half* skip = nullptr;
    __half* hidden = nullptr;
    __half* output = nullptr;
    check_cuda(cudaMalloc(&input, input_count * sizeof(__half)), "cudaMalloc(input)");
    check_cuda(cudaMalloc(&expansion, kChannels * kHidden * sizeof(__half)), "cudaMalloc(expansion)");
    check_cuda(cudaMalloc(&contraction, kHidden * kChannels * sizeof(__half)), "cudaMalloc(contraction)");
    check_cuda(cudaMalloc(&skip, kChannels * sizeof(__half)), "cudaMalloc(skip)");
    check_cuda(cudaMalloc(&hidden, hidden_count * sizeof(__half)), "cudaMalloc(hidden)");
    check_cuda(cudaMalloc(&output, input_count * sizeof(__half)), "cudaMalloc(output)");

    std::vector<__half> host_input;
    std::vector<__half> host_expansion;
    std::vector<__half> host_contraction;
    std::vector<__half> host_skip;
    if (data_directory.empty()) {
        // Small deterministic values avoid overflow while keeping all paths live.
        launch_fill(input, input_count, 0.01f, stream);
        launch_fill(expansion, kChannels * kHidden, 0.02f, stream);
        launch_fill(contraction, kHidden * kChannels, 0.02f, stream);
        launch_fill(skip, kChannels, 1.0f, stream);
    } else {
        host_input.resize(input_count);
        host_expansion.resize(kChannels * kHidden);
        host_contraction.resize(kHidden * kChannels);
        host_skip.resize(kChannels);
        load_binary(data_directory + "/input.bin", host_input.data(), host_input.size() * sizeof(__half));
        load_binary(data_directory + "/expansion.bin", host_expansion.data(), host_expansion.size() * sizeof(__half));
        load_binary(data_directory + "/contraction.bin", host_contraction.data(), host_contraction.size() * sizeof(__half));
        load_binary(data_directory + "/skip.bin", host_skip.data(), host_skip.size() * sizeof(__half));
        check_cuda(cudaMemcpyAsync(input, host_input.data(), host_input.size() * sizeof(__half), cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(input)");
        check_cuda(cudaMemcpyAsync(expansion, host_expansion.data(), host_expansion.size() * sizeof(__half), cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(expansion)");
        check_cuda(cudaMemcpyAsync(contraction, host_contraction.data(), host_contraction.size() * sizeof(__half), cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(contraction)");
        check_cuda(cudaMemcpyAsync(skip, host_skip.data(), host_skip.size() * sizeof(__half), cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(skip)");
    }
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(initialization)");

    // Warm up clocks, cuBLAS algorithm selection, and the custom kernels.
    if (data_directory.empty()) {
        for (int i = 0; i < 3; ++i) {
            run_mlp(handle, input, expansion, contraction, skip, hidden, output, tokens, stream);
        }
    }
    for (int i = 0; i < 3; ++i) {
        launch_fused_wmma(input, expansion, contraction, skip, output, tokens, stream);
    }
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(warmup)");

    float direct_ms = 0.0f;
    float graph_ms = 0.0f;
    if (data_directory.empty()) {
        direct_ms = time_direct(handle, input, expansion, contraction, skip, hidden, output, tokens, iterations, stream);
        graph_ms = time_graph(handle, input, expansion, contraction, skip, hidden, output, tokens, iterations, stream);
    }
    const float fused_direct_ms = time_fused_wmma(input, expansion, contraction, skip, output, tokens, iterations, stream);
    const float fused_graph_ms = time_fused_wmma_graph(input, expansion, contraction, skip, output, tokens, iterations, stream);
    std::vector<__half> host_output(input_count);
    check_cuda(cudaMemcpy(host_output.data(), output, host_output.size() * sizeof(__half), cudaMemcpyDeviceToHost), "cudaMemcpy(output)");
    if (!output_path.empty()) {
        save_binary(output_path, host_output.data(), host_output.size() * sizeof(__half));
    }
    bool output_finite = true;
    for (const __half value : host_output) {
        if (!std::isfinite(__half2float(value))) {
            output_finite = false;
            break;
        }
    }

    std::cout << "cuda_c32_mlp_executor_probe\n"
              << "  device=" << properties.name << "\n"
              << "  arch=" << properties.major * 10 + properties.minor << "\n"
              << "  input_mode=" << (data_directory.empty() ? "synthetic" : "recovered_export") << "\n"
              << "  tokens=" << tokens << " channels=" << kChannels << " hidden=" << kHidden << " iterations=" << iterations << "\n"
              << "  cublas_direct_ms=" << direct_ms << "\n"
              << "  cublas_graph_ms=" << graph_ms << "\n"
              << "  cublas_graph_speedup=" << (data_directory.empty() ? direct_ms / std::max(graph_ms, 1e-9f) : 0.0f) << "\n"
              << "  fused_wmma_ms=" << fused_direct_ms << "\n"
              << "  fused_wmma_graph_ms=" << fused_graph_ms << "\n"
              << "  fused_vs_cublas_speedup=" << (data_directory.empty() ? direct_ms / std::max(fused_graph_ms, 1e-9f) : 0.0f) << "\n"
              << "  output_finite=" << (output_finite ? "true" : "false") << "\n"
              << "  first_output=" << __half2float(host_output.front()) << "\n";

    cudaFree(input);
    cudaFree(expansion);
    cudaFree(contraction);
    cudaFree(skip);
    cudaFree(hidden);
    cudaFree(output);
    cublasDestroy(handle);
    cudaStreamDestroy(stream);
    return 0;
}
