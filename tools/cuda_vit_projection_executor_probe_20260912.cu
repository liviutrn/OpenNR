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

constexpr int kRowsPerBlock = 16;
constexpr int kColsPerWarp = 16;
constexpr int kWarpsPerBlock = 8;
constexpr int kColsPerBlock = kColsPerWarp * kWarpsPerBlock;
constexpr int kThreads = kWarpsPerBlock * 32;

void check_cuda(cudaError_t status, const char* expression) {
    if (status != cudaSuccess) {
        std::cerr << expression << " failed: " << cudaGetErrorString(status) << '\n';
        std::exit(2);
    }
}

void check_cublas(cublasStatus_t status, const char* expression) {
    if (status != CUBLAS_STATUS_SUCCESS) {
        std::cerr << expression << " failed: cublas status "
                  << static_cast<int>(status) << '\n';
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

// Same inexpensive cubic approximation used by the C32 runtime probe.  This
// is intentionally a speed-kernel test, not a claim of bit-exact native math.
__device__ __forceinline__ __half cubic_approx(__half input) {
    const __half minus_four = __float2half(-4.0f);
    const __half plus_four = __float2half(4.0f);
    const __half t = __hmin(__hmax(input, minus_four), plus_four);
    const __half p = __hfma(__hneg(__habs(t)), __float2half(0.055908203125f),
                            __float2half(0.447265625f));
    const __half v = __hfma(t, p, __float2half(0.89453125f));
    return __hmul(input, v);
}

__global__ void cubic_kernel(__half* values, std::size_t count) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x
                            + threadIdx.x;
    if (index < count) {
        values[index] = cubic_approx(values[index]);
    }
}

__global__ void residual_kernel(const __half* product,
                                const __half* initial,
                                __half* output,
                                std::size_t count) {
    const std::size_t index = static_cast<std::size_t>(blockIdx.x) * blockDim.x
                            + threadIdx.x;
    if (index < count) {
        output[index] = __hadd(product[index], initial[index]);
    }
}

// A row-tiled WMMA projection.  Each block owns 16 input rows and 128 output
// columns, reuses a 16x16 input tile across eight output warps, and keeps the
// full K loop and the post-op in one launch.  It supports both large ViT
// projections used by the recovered block:
//   [M,1024] @ [1024,4096] -> cubic [M,4096]
//   [M,4096] @ [4096,1024] + initial -> [M,1024]
// The layout is ordinary row-major [K,N] weights and [M,K] activations.
template <int K, int N, int PostOp>
__global__ __launch_bounds__(kThreads) void fused_projection_kernel(
    const __half* __restrict__ input,
    const __half* __restrict__ weight,
    const __half* __restrict__ initial,
    __half* __restrict__ output,
    int rows) {
    __shared__ __half input_tile[kRowsPerBlock * 16];
    __shared__ float output_tile[kRowsPerBlock * kColsPerBlock];

    const int row_base = static_cast<int>(blockIdx.x) * kRowsPerBlock;
    const int col_base = static_cast<int>(blockIdx.y) * kColsPerBlock;

    const int warp = threadIdx.x / 32;
    const int lane = threadIdx.x % 32;
    (void)lane;

    nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16, float> accumulator;
    if (warp < kWarpsPerBlock) {
        nvcuda::wmma::fill_fragment(accumulator, 0.0f);
    }

    for (int k_base = 0; k_base < K; k_base += 16) {
        const int tile_index = threadIdx.x;
        const int tile_row = tile_index / 16;
        const int tile_col = tile_index % 16;
        const int global_row = row_base + tile_row;
        const int global_k = k_base + tile_col;
        input_tile[tile_index] = (global_row < rows)
            ? input[static_cast<std::size_t>(global_row) * K + global_k]
            : __float2half(0.0f);
        __syncthreads();

        if (warp < kWarpsPerBlock) {
            nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16,
                                   __half, nvcuda::wmma::row_major> a;
            nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16,
                                   __half, nvcuda::wmma::row_major> b;
            nvcuda::wmma::load_matrix_sync(a, input_tile, 16);
            const int col = col_base + warp * kColsPerWarp;
            nvcuda::wmma::load_matrix_sync(
                b, weight + static_cast<std::size_t>(k_base) * N + col,
                N);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        __syncthreads();
    }

    if (warp < kWarpsPerBlock) {
        nvcuda::wmma::store_matrix_sync(
            output_tile + warp * kColsPerWarp, accumulator, kColsPerBlock,
            nvcuda::wmma::mem_row_major);
    }
    __syncthreads();

    for (int output_index = threadIdx.x;
         output_index < kRowsPerBlock * kColsPerBlock;
         output_index += kThreads) {
        const int output_row = output_index / kColsPerBlock;
        const int output_col = output_index % kColsPerBlock;
        const int global_row = row_base + output_row;
        const int global_col = col_base + output_col;
        if (global_row < rows && global_col < N) {
            const std::size_t index = static_cast<std::size_t>(global_row) * N + global_col;
            const __half value = __float2half(output_tile[output_index]);
            if constexpr (PostOp == 1) {
                output[index] = cubic_approx(value);
            } else if constexpr (PostOp == 2) {
                output[index] = __hadd(value, initial[index]);
            } else {
                output[index] = value;
            }
        }
    }
}

template <int K, int N, int PostOp>
void launch_fused(const __half* input,
                  const __half* weight,
                  const __half* initial,
                  __half* output,
                  int rows,
                  cudaStream_t stream) {
    dim3 grid((rows + kRowsPerBlock - 1) / kRowsPerBlock,
              (N + kColsPerBlock - 1) / kColsPerBlock);
    fused_projection_kernel<K, N, PostOp><<<grid, kThreads, 0, stream>>>(
        input, weight, initial, output, rows);
    check_cuda(cudaGetLastError(), "fused_projection_kernel");
}

template <int K, int N, int PostOp>
void launch_separate(cublasHandle_t handle,
                     const __half* input,
                     const __half* weight,
                     const __half* initial,
                     __half* workspace,
                     __half* output,
                     int rows,
                     cudaStream_t stream) {
    // Row-major [M,K] @ [K,N] is the same memory layout as column-major
    // [N,K] @ [K,M], so the cuBLAS dimensions are transposed here without a
    // temporary transpose.
    const float alpha = 1.0f;
    const float beta = 0.0f;
    check_cublas(cublasGemmEx(
        handle, CUBLAS_OP_N, CUBLAS_OP_N, N, rows, K, &alpha,
        weight, CUDA_R_16F, N, input, CUDA_R_16F, K, &beta,
        workspace, CUDA_R_16F, N, CUBLAS_COMPUTE_32F,
        CUBLAS_GEMM_DEFAULT_TENSOR_OP), "cublasGemmEx(projection)");

    if constexpr (PostOp == 1) {
        const int blocks = static_cast<int>((static_cast<std::size_t>(rows) * N + 255) / 256);
        cubic_kernel<<<blocks, 256, 0, stream>>>(workspace,
                                                  static_cast<std::size_t>(rows) * N);
        check_cuda(cudaGetLastError(), "cubic_kernel");
        check_cuda(cudaMemcpyAsync(output, workspace,
                                   static_cast<std::size_t>(rows) * N * sizeof(__half),
                                   cudaMemcpyDeviceToDevice, stream),
                   "cudaMemcpyAsync(expand output)");
    } else if constexpr (PostOp == 2) {
        const int blocks = static_cast<int>((static_cast<std::size_t>(rows) * N + 255) / 256);
        residual_kernel<<<blocks, 256, 0, stream>>>(workspace, initial, output,
                                                    static_cast<std::size_t>(rows) * N);
        check_cuda(cudaGetLastError(), "residual_kernel");
    } else {
        check_cuda(cudaMemcpyAsync(output, workspace,
                                   static_cast<std::size_t>(rows) * N * sizeof(__half),
                                   cudaMemcpyDeviceToDevice, stream),
                   "cudaMemcpyAsync(output)");
    }
}

template <int K, int N, int PostOp>
float time_separate(cublasHandle_t handle,
                    const __half* input,
                    const __half* weight,
                    const __half* initial,
                    __half* workspace,
                    __half* output,
                    int rows,
                    int iterations,
                    cudaStream_t stream) {
    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(separate start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(separate stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(separate start)");
    for (int i = 0; i < iterations; ++i) {
        launch_separate<K, N, PostOp>(handle, input, weight, initial, workspace,
                                      output, rows, stream);
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(separate stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(separate stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop),
               "cudaEventElapsedTime(separate)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    return elapsed / iterations;
}

template <int K, int N, int PostOp>
float time_fused(const __half* input,
                 const __half* weight,
                 const __half* initial,
                 __half* output,
                 int rows,
                 int iterations,
                 cudaStream_t stream) {
    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(fused start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(fused stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(fused start)");
    for (int i = 0; i < iterations; ++i) {
        launch_fused<K, N, PostOp>(input, weight, initial, output, rows, stream);
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(fused stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(fused stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop),
               "cudaEventElapsedTime(fused)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    return elapsed / iterations;
}

template <int K, int N, int PostOp>
void run_case(const std::string& label,
              const std::string& data_directory,
              const std::string& output_directory,
              int rows,
              int iterations,
              cublasHandle_t handle,
              cudaStream_t stream) {
    const std::size_t input_bytes = static_cast<std::size_t>(rows) * K * sizeof(__half);
    const std::size_t weight_bytes = static_cast<std::size_t>(K) * N * sizeof(__half);
    const std::size_t output_bytes = static_cast<std::size_t>(rows) * N * sizeof(__half);

    __half* input = nullptr;
    __half* weight = nullptr;
    __half* initial = nullptr;
    __half* workspace = nullptr;
    __half* separate_output = nullptr;
    __half* fused_output = nullptr;
    check_cuda(cudaMalloc(&input, input_bytes), "cudaMalloc(case input)");
    check_cuda(cudaMalloc(&weight, weight_bytes), "cudaMalloc(case weight)");
    check_cuda(cudaMalloc(&initial, output_bytes), "cudaMalloc(case initial)");
    check_cuda(cudaMalloc(&workspace, output_bytes), "cudaMalloc(case workspace)");
    check_cuda(cudaMalloc(&separate_output, output_bytes), "cudaMalloc(case separate output)");
    check_cuda(cudaMalloc(&fused_output, output_bytes), "cudaMalloc(case fused output)");

    std::vector<__half> host_input(rows * K);
    std::vector<__half> host_weight(static_cast<std::size_t>(K) * N);
    std::vector<__half> host_initial(static_cast<std::size_t>(rows) * N);
    if (data_directory.empty()) {
        std::fill(host_input.begin(), host_input.end(), __float2half(0.01f));
        std::fill(host_weight.begin(), host_weight.end(), __float2half(0.005f));
        std::fill(host_initial.begin(), host_initial.end(), __float2half(0.1f));
    } else {
        load_binary(data_directory + "/" + label + "_input.bin",
                    host_input.data(), input_bytes);
        load_binary(data_directory + "/" + label + "_weight.bin",
                    host_weight.data(), weight_bytes);
        if constexpr (PostOp == 2) {
            load_binary(data_directory + "/" + label + "_initial.bin",
                        host_initial.data(), output_bytes);
        } else {
            std::fill(host_initial.begin(), host_initial.end(), __float2half(0.0f));
        }
    }
    check_cuda(cudaMemcpyAsync(input, host_input.data(), input_bytes,
                               cudaMemcpyHostToDevice, stream),
               "cudaMemcpyAsync(case input)");
    check_cuda(cudaMemcpyAsync(weight, host_weight.data(), weight_bytes,
                               cudaMemcpyHostToDevice, stream),
               "cudaMemcpyAsync(case weight)");
    check_cuda(cudaMemcpyAsync(initial, host_initial.data(), output_bytes,
                               cudaMemcpyHostToDevice, stream),
               "cudaMemcpyAsync(case initial)");
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(case upload)");

    for (int i = 0; i < 3; ++i) {
        launch_separate<K, N, PostOp>(handle, input, weight, initial, workspace,
                                      separate_output, rows, stream);
        launch_fused<K, N, PostOp>(input, weight, initial, fused_output, rows, stream);
    }
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(case warmup)");

    const float separate_ms = time_separate<K, N, PostOp>(
        handle, input, weight, initial, workspace, separate_output,
        rows, iterations, stream);
    const float fused_ms = time_fused<K, N, PostOp>(
        input, weight, initial, fused_output, rows, iterations, stream);

    std::vector<__half> host_fused(static_cast<std::size_t>(rows) * N);
    check_cuda(cudaMemcpy(host_fused.data(), fused_output, output_bytes,
                          cudaMemcpyDeviceToHost),
               "cudaMemcpy(case fused output)");
    bool finite = true;
    for (const __half value : host_fused) {
        if (!std::isfinite(__half2float(value))) {
            finite = false;
            break;
        }
    }
    if (!output_directory.empty()) {
        save_binary(output_directory + "/" + label + "_fused.bin",
                    host_fused.data(), output_bytes);
    }

    std::cout << "  case=" << label << " rows=" << rows << " K=" << K
              << " N=" << N << " separate_ms=" << separate_ms
              << " fused_ms=" << fused_ms
              << " speedup=" << separate_ms / std::max(fused_ms, 1e-9f)
              << " output_finite=" << (finite ? "true" : "false")
              << " first_output=" << __half2float(host_fused.front()) << '\n';

    cudaFree(input);
    cudaFree(weight);
    cudaFree(initial);
    cudaFree(workspace);
    cudaFree(separate_output);
    cudaFree(fused_output);
}

}  // namespace

int main(int argc, char** argv) {
    const int rows = argc > 1 ? std::atoi(argv[1]) : 640;
    const int iterations = argc > 2 ? std::max(1, std::atoi(argv[2])) : 10;
    const std::string data_directory = argc > 3 ? argv[3] : "";
    const std::string output_directory = argc > 4 ? argv[4] : "";
    if (rows <= 0 || rows > std::numeric_limits<int>::max() / 16) {
        std::cerr << "rows must be positive\n";
        return 1;
    }

    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, 0), "cudaGetDeviceProperties");
    cudaStream_t stream = nullptr;
    check_cuda(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking),
               "cudaStreamCreateWithFlags");
    cublasHandle_t handle = nullptr;
    check_cublas(cublasCreate(&handle), "cublasCreate");
    check_cublas(cublasSetStream(handle, stream), "cublasSetStream");
    check_cublas(cublasSetMathMode(handle, CUBLAS_TENSOR_OP_MATH),
                 "cublasSetMathMode");

    std::cout << "cuda_vit_projection_executor_probe\n"
              << "  device=" << properties.name << "\n"
              << "  arch=" << properties.major * 10 + properties.minor << "\n"
              << "  input_mode=" << (data_directory.empty() ? "synthetic" : "recovered_export")
              << " rows=" << rows << " iterations=" << iterations << '\n';

    if (!output_directory.empty()) {
        // The caller owns directory creation; this check keeps the probe from
        // silently claiming it wrote a file when the path is absent.
        std::ofstream test(output_directory + "/.write_test", std::ios::binary | std::ios::trunc);
        if (!test) {
            std::cerr << "cannot write output directory " << output_directory << '\n';
            return 8;
        }
        test.close();
        std::remove((output_directory + "/.write_test").c_str());
    }

    run_case<1024, 4096, 1>("expand", data_directory, output_directory,
                            rows, iterations, handle, stream);
    run_case<4096, 1024, 2>("contract", data_directory, output_directory,
                            rows, iterations, handle, stream);
    run_case<1024, 1024, 2>("projection", data_directory, output_directory,
                            rows, iterations, handle, stream);

    cublasDestroy(handle);
    cudaStreamDestroy(stream);
    return 0;
}
