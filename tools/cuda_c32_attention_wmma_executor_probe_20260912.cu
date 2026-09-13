#include <cuda_fp16.h>
#include <cuda_runtime.h>
#include <mma.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

namespace {

constexpr int kChannels = 32;
constexpr int kWindow = 8;
constexpr int kWindowTokens = kWindow * kWindow;
constexpr int kQkvChannels = 96;
constexpr int kThreads = 256;
constexpr int kWmmaTile = 16;
constexpr int kWarps = kThreads / 32;

// Dynamic shared-memory layout. The K matrix is first kept row-major in
// k_buffer, then the same qkv_buffer allocation is reused for K^T after QKV
// projection has finished. The score matrix stays float for the QK product;
// probability/AV/projection use half storage for Tensor-Core compatibility.
constexpr int kWindowElements = kWindowTokens * kChannels;
constexpr int kQkvWeightElements = kChannels * kQkvChannels;
constexpr int kProjectionElements = kChannels * kChannels;
constexpr int kBiasElements = kWindowTokens * kWindowTokens;
constexpr int kScoreElements = kWindowTokens * kWindowTokens;

constexpr int kXOffset = 0;
constexpr int kQOffset = kXOffset + kWindowElements;
constexpr int kVOffset = kQOffset + kWindowElements;
constexpr int kQkvOffset = kVOffset + kWindowElements;
constexpr int kProjectionOffset = kQkvOffset + kQkvWeightElements;
constexpr int kBiasOffset = kProjectionOffset + kProjectionElements;
constexpr int kCosineOffset = kBiasOffset + kBiasElements;
constexpr int kHalfBeforeScores = kCosineOffset + kChannels;
constexpr std::size_t kScoreOffsetBytes =
    static_cast<std::size_t>(kHalfBeforeScores) * sizeof(__half);
constexpr std::size_t kProbabilityOffsetBytes =
    kScoreOffsetBytes + static_cast<std::size_t>(kScoreElements) * sizeof(float);
constexpr int kProbabilityOffsetHalf =
    kHalfBeforeScores + kScoreElements * (sizeof(float) / sizeof(__half));
constexpr int kAttendedOffset = kProbabilityOffsetHalf + kScoreElements;
constexpr int kOutputTileOffset = kAttendedOffset + kWindowElements;
constexpr std::size_t kSharedBytes =
    static_cast<std::size_t>(kOutputTileOffset + kWindowElements) * sizeof(__half);

void check_cuda(cudaError_t status, const char* expression) {
    if (status != cudaSuccess) {
        std::cerr << expression << " failed: " << cudaGetErrorString(status) << '\n';
        std::exit(2);
    }
}

void load_binary(const std::string& path, void* destination, std::size_t bytes) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        std::cerr << "cannot open " << path << '\n';
        std::exit(3);
    }
    input.read(static_cast<char*>(destination), static_cast<std::streamsize>(bytes));
    if (input.gcount() != static_cast<std::streamsize>(bytes)) {
        std::cerr << "short read for " << path << ": expected " << bytes
                  << " bytes, got " << input.gcount() << '\n';
        std::exit(4);
    }
}

void save_binary(const std::string& path, const void* source, std::size_t bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        std::cerr << "cannot open output " << path << '\n';
        std::exit(5);
    }
    output.write(static_cast<const char*>(source), static_cast<std::streamsize>(bytes));
    if (!output) {
        std::cerr << "short write for " << path << '\n';
        std::exit(6);
    }
}

__device__ __forceinline__ __half half_add(__half left, __half right) {
    return __float2half_rn(__half2float(left) + __half2float(right));
}

__device__ __forceinline__ __half half_mul(__half left, __half right) {
    return __float2half_rn(__half2float(left) * __half2float(right));
}

// Saturating E4M3FN round trip matching the recovered Triton publication
// boundary. It is retained here so the Tensor-Core probe has the same
// approximate quantization boundary as the scalar control.
__device__ __forceinline__ __half round_fp8_half(__half input) {
    const std::uint32_t bits = __half_as_ushort(input);
    const std::uint32_t sign = bits & 0x8000u;
    const std::uint32_t raw = bits & 0x7FFFu;
    const std::uint32_t magnitude = min(raw, 0x5F00u);
    const std::uint32_t exponent = magnitude >> 10;
    const std::uint32_t significand = (magnitude & 1023u) +
                                      (exponent != 0u ? 1024u : 0u);
    const std::uint32_t shift = max(16u - max(exponent, 1u), 1u);
    const std::uint32_t quotient = significand >> shift;
    const std::uint32_t remainder = significand - (quotient << shift);
    const std::uint32_t midpoint = 1u << (shift - 1u);
    const std::uint32_t rounded = quotient +
        ((remainder > midpoint ||
          (remainder == midpoint && (quotient & 1u) != 0u)) ? 1u : 0u);
    const __half subnormal = __float2half_rn(static_cast<float>(rounded) * 0.001953125f);
    const std::uint32_t subnormal_bits = __half_as_ushort(subnormal);
    const std::uint32_t normal = (magnitude + 63u + ((magnitude >> 7) & 1u)) & 0x7F80u;
    std::uint32_t result = (magnitude < 0x2400u ? subnormal_bits : normal) | sign;
    if (raw > 0x7C00u) {
        result = 0x7F80u | sign;
    }
    return __ushort_as_half(static_cast<unsigned short>(result));
}

// Scalar equivalent of the recovered paired-half exponential used by the
// existing Triton probe. It is not a native NVIDIA math reproduction.
__device__ __forceinline__ __half recovered_exp(__half score) {
    __half affine = __float2half_rn(__half2float(score) * 0.044921875f + 1.30078125f);
    affine = __hmin(__hmax(affine, __float2half(1.03125f)), __float2half(1.5693359375f));
    const std::uint32_t affine_bits = __half_as_ushort(affine);
    const std::uint32_t transformed = (affine_bits << 5u) + 0x7FF88000u;
    return __ushort_as_half(static_cast<unsigned short>(transformed & 0xFFFFu));
}

__device__ __forceinline__ std::size_t global_token_index(
    int window, int local_token, int width) {
    const int windows_x = width / kWindow;
    const int window_y = window / windows_x;
    const int window_x = window % windows_x;
    const int local_y = local_token / kWindow;
    const int local_x = local_token % kWindow;
    const int y = window_y * kWindow + local_y;
    const int x = window_x * kWindow + local_x;
    return static_cast<std::size_t>(y * width + x);
}

// One block owns one 8x8 window. QKV, QK, AV, and output projection use 16x16
// WMMA tiles; normalization, recovered exponential, FP8 boundaries, and the
// final residual remain fused in the same block. This is an independent
// Tensor-Core control, not a claim to reproduce NVIDIA's native kernel.
__global__ __launch_bounds__(kThreads) void fused_c32_wmma_attention_kernel(
    const __half* __restrict__ ffn,
    const __half* __restrict__ qkv_weight,
    const float* __restrict__ attention_scale,
    const __half* __restrict__ bias,
    const __half* __restrict__ projection,
    const __half* __restrict__ cosine,
    __half* __restrict__ output,
    int height,
    int width) {
    extern __shared__ unsigned char shared_bytes[];
    __half* shared = reinterpret_cast<__half*>(shared_bytes);
    __half* x = shared + kXOffset;
    __half* q = shared + kQOffset;
    __half* v = shared + kVOffset;
    __half* qkv = shared + kQkvOffset;
    __half* projection_tile = shared + kProjectionOffset;
    __half* bias_tile = shared + kBiasOffset;
    __half* cosine_tile = shared + kCosineOffset;
    float* scores = reinterpret_cast<float*>(shared_bytes + kScoreOffsetBytes);
    __half* probability = reinterpret_cast<__half*>(shared_bytes + kProbabilityOffsetBytes);
    __half* attended = shared + kAttendedOffset;
    __half* output_tile = shared + kOutputTileOffset;

    const int tid = threadIdx.x;
    const int warp = tid / 32;
    const int window = static_cast<int>(blockIdx.x);
    const std::size_t total_windows = static_cast<std::size_t>(height / kWindow) *
                                      static_cast<std::size_t>(width / kWindow);
    if (static_cast<std::size_t>(window) >= total_windows) {
        return;
    }

    for (int index = tid; index < kWindowElements; index += kThreads) {
        const int local_token = index / kChannels;
        const int channel = index % kChannels;
        x[index] = ffn[global_token_index(window, local_token, width) * kChannels + channel];
    }
    for (int index = tid; index < kQkvWeightElements; index += kThreads) {
        qkv[index] = qkv_weight[index];
    }
    for (int index = tid; index < kProjectionElements; index += kThreads) {
        projection_tile[index] = projection[index];
    }
    for (int index = tid; index < kBiasElements; index += kThreads) {
        bias_tile[index] = bias[index];
    }
    for (int index = tid; index < kChannels; index += kThreads) {
        cosine_tile[index] = cosine[index];
    }
    __syncthreads();

    // QKV: [64,32] @ [32,96] -> Q, K, V. The K output is first staged in
    // row-major form in attended[] and transposed into the reused qkv[] area
    // after all QKV weight reads are complete.
    for (int tile = warp; tile < 24; tile += kWarps) {
        const int row_tile = tile / 6;
        const int col_tile = tile % 6;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16,
                               __half> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, __float2half(0.0f));
        for (int k_base = 0; k_base < kChannels; k_base += kWmmaTile) {
            nvcuda::wmma::load_matrix_sync(
                a, x + row_tile * kWmmaTile * kChannels + k_base, kChannels);
            nvcuda::wmma::load_matrix_sync(
                b, qkv + k_base * kQkvChannels + col_tile * kWmmaTile,
                kQkvChannels);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        __half* destination = nullptr;
        if (col_tile < 2) {
            destination = q + row_tile * kWmmaTile * kChannels +
                          (col_tile % 2) * kWmmaTile;
        } else if (col_tile < 4) {
            destination = attended + row_tile * kWmmaTile * kChannels +
                          (col_tile % 2) * kWmmaTile;
        } else {
            destination = v + row_tile * kWmmaTile * kChannels +
                          (col_tile % 2) * kWmmaTile;
        }
        nvcuda::wmma::store_matrix_sync(destination, accumulator, kChannels,
                                        nvcuda::wmma::mem_row_major);
    }
    __syncthreads();

    // Normalize Q/K, publish their recovered half-FP8 boundary, publish V,
    // and transpose K into qkv[] so it can be used as the B operand of QK.
    const __half scale = __float2half_rn(attention_scale[0]);
    if (tid < kWindowTokens) {
        const int row = tid;
        float q_norm = 0.0f;
        float k_norm = 0.0f;
        for (int channel = 0; channel < kChannels; ++channel) {
            const float q_value = __half2float(q[row * kChannels + channel]);
            const float k_value = __half2float(attended[row * kChannels + channel]);
            q_norm += q_value * q_value;
            k_norm += k_value * k_value;
        }
        const __half q_reciprocal = __float2half_rn(
            rsqrtf(fmaxf(q_norm, 0.00006198883056640625f)));
        const __half k_reciprocal = __float2half_rn(
            rsqrtf(fmaxf(k_norm, 0.00006198883056640625f)));
        for (int channel = 0; channel < kChannels; ++channel) {
            __half q_value = half_mul(q[row * kChannels + channel], q_reciprocal);
            q_value = half_mul(q_value, scale);
            q[row * kChannels + channel] = round_fp8_half(q_value);
            qkv[channel * kWindowTokens + row] = round_fp8_half(
                half_mul(attended[row * kChannels + channel], k_reciprocal));
            v[row * kChannels + channel] = round_fp8_half(v[row * kChannels + channel]);
        }
    }
    __syncthreads();

    // QK: [64,32] @ [32,64] -> float scores. The 16x16 score tiles are
    // immediately post-processed by the 64 row threads below.
    for (int tile = warp; tile < 16; tile += kWarps) {
        const int row_tile = tile / 4;
        const int col_tile = tile % 4;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16,
                               float> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, 0.0f);
        for (int k_base = 0; k_base < kChannels; k_base += kWmmaTile) {
            nvcuda::wmma::load_matrix_sync(
                a, q + row_tile * kWmmaTile * kChannels + k_base, kChannels);
            nvcuda::wmma::load_matrix_sync(
                b, qkv + k_base * kWindowTokens + col_tile * kWmmaTile,
                kWindowTokens);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        nvcuda::wmma::store_matrix_sync(
            scores + row_tile * kWmmaTile * kWindowTokens + col_tile * kWmmaTile,
            accumulator, kWindowTokens, nvcuda::wmma::mem_row_major);
    }
    __syncthreads();

    if (tid < kWindowTokens) {
        const int row = tid;
        float sum = 0.0f;
        for (int key = 0; key < kWindowTokens; ++key) {
            const __half score = __float2half_rn(
                scores[row * kWindowTokens + key] +
                __half2float(bias_tile[row * kWindowTokens + key]));
            const __half weight = recovered_exp(score);
            probability[row * kWindowTokens + key] = weight;
            sum += __half2float(weight);
        }
        const __half reciprocal = __float2half_rn(
            1.0f / __half2float(__float2half_rn(sum)));
        for (int key = 0; key < kWindowTokens; ++key) {
            probability[row * kWindowTokens + key] = round_fp8_half(
                half_mul(probability[row * kWindowTokens + key], reciprocal));
        }
    }
    __syncthreads();

    // AV: [64,64] @ [64,32] -> attended [64,32].
    for (int tile = warp; tile < 8; tile += kWarps) {
        const int row_tile = tile / 2;
        const int col_tile = tile % 2;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16,
                               __half> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, __float2half(0.0f));
        for (int k_base = 0; k_base < kWindowTokens; k_base += kWmmaTile) {
            nvcuda::wmma::load_matrix_sync(
                a, probability + row_tile * kWmmaTile * kWindowTokens + k_base,
                kWindowTokens);
            nvcuda::wmma::load_matrix_sync(
                b, v + k_base * kChannels + col_tile * kWmmaTile, kChannels);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        nvcuda::wmma::store_matrix_sync(
            attended + row_tile * kWmmaTile * kChannels + col_tile * kWmmaTile,
            accumulator, kChannels, nvcuda::wmma::mem_row_major);
    }
    __syncthreads();
    for (int index = tid; index < kWindowElements; index += kThreads) {
        attended[index] = round_fp8_half(attended[index]);
    }
    __syncthreads();

    // Output projection: [64,32] @ [32,32] -> [64,32].
    for (int tile = warp; tile < 8; tile += kWarps) {
        const int row_tile = tile / 2;
        const int col_tile = tile % 2;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_a, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> a;
        nvcuda::wmma::fragment<nvcuda::wmma::matrix_b, 16, 16, 16,
                               __half, nvcuda::wmma::row_major> b;
        nvcuda::wmma::fragment<nvcuda::wmma::accumulator, 16, 16, 16,
                               __half> accumulator;
        nvcuda::wmma::fill_fragment(accumulator, __float2half(0.0f));
        for (int k_base = 0; k_base < kChannels; k_base += kWmmaTile) {
            nvcuda::wmma::load_matrix_sync(
                a, attended + row_tile * kWmmaTile * kChannels + k_base,
                kChannels);
            nvcuda::wmma::load_matrix_sync(
                b, projection_tile + k_base * kChannels + col_tile * kWmmaTile,
                kChannels);
            nvcuda::wmma::mma_sync(accumulator, a, b, accumulator);
        }
        nvcuda::wmma::store_matrix_sync(
            output_tile + row_tile * kWmmaTile * kChannels + col_tile * kWmmaTile,
            accumulator, kChannels, nvcuda::wmma::mem_row_major);
    }
    __syncthreads();
    for (int index = tid; index < kWindowElements; index += kThreads) {
        const int local_token = index / kChannels;
        const int channel = index % kChannels;
        const std::size_t output_row = global_token_index(window, local_token, width);
        output[output_row * kChannels + channel] = half_add(
            output_tile[index], half_mul(x[index], cosine_tile[channel]));
    }
}

void launch_kernel(const __half* ffn,
                   const __half* qkv_weight,
                   const float* attention_scale,
                   const __half* bias,
                   const __half* projection,
                   const __half* cosine,
                   __half* output,
                   int height,
                   int width,
                   cudaStream_t stream) {
    const int windows = (height / kWindow) * (width / kWindow);
    fused_c32_wmma_attention_kernel<<<windows, kThreads, kSharedBytes, stream>>>(
        ffn, qkv_weight, attention_scale, bias, projection, cosine,
        output, height, width);
    check_cuda(cudaGetLastError(), "fused_c32_wmma_attention_kernel");
}

float time_direct(const __half* ffn,
                  const __half* qkv_weight,
                  const float* attention_scale,
                  const __half* bias,
                  const __half* projection,
                  const __half* cosine,
                  __half* output,
                  int height,
                  int width,
                  int iterations,
                  cudaStream_t stream) {
    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(direct start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(direct stop)");
    check_cuda(cudaEventRecord(start, stream), "cudaEventRecord(direct start)");
    for (int i = 0; i < iterations; ++i) {
        launch_kernel(ffn, qkv_weight, attention_scale, bias, projection,
                      cosine, output, height, width, stream);
    }
    check_cuda(cudaEventRecord(stop, stream), "cudaEventRecord(direct stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(direct stop)");
    float elapsed = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed, start, stop), "cudaEventElapsedTime(direct)");
    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    return elapsed / iterations;
}

float time_graph(const __half* ffn,
                 const __half* qkv_weight,
                 const float* attention_scale,
                 const __half* bias,
                 const __half* projection,
                 const __half* cosine,
                 __half* output,
                 int height,
                 int width,
                 int iterations,
                 cudaStream_t stream) {
    check_cuda(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal),
               "cudaStreamBeginCapture");
    launch_kernel(ffn, qkv_weight, attention_scale, bias, projection,
                  cosine, output, height, width, stream);
    cudaGraph_t graph = nullptr;
    check_cuda(cudaStreamEndCapture(stream, &graph), "cudaStreamEndCapture");
    cudaGraphExec_t executable = nullptr;
    check_cuda(cudaGraphInstantiate(&executable, graph, nullptr, nullptr, 0),
               "cudaGraphInstantiate");
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

}  // namespace

int main(int argc, char** argv) {
    if (argc < 6) {
        std::cerr << "usage: " << argv[0]
                  << " <data_dir> <height> <width> <iterations> <output_bin>\n";
        return 1;
    }
    const std::string data_dir = argv[1];
    const int height = std::atoi(argv[2]);
    const int width = std::atoi(argv[3]);
    const int iterations = std::max(1, std::atoi(argv[4]));
    const std::string output_path = argv[5];
    if (height <= 0 || width <= 0 || height % kWindow != 0 || width % kWindow != 0) {
        std::cerr << "height and width must be positive multiples of eight\n";
        return 1;
    }

    const std::size_t tokens = static_cast<std::size_t>(height) * width;
    const std::size_t feature_count = tokens * kChannels;
    std::vector<__half> host_ffn(feature_count);
    std::vector<__half> host_qkv(kQkvWeightElements);
    std::vector<float> host_scale(1);
    std::vector<__half> host_bias(kBiasElements);
    std::vector<__half> host_projection(kProjectionElements);
    std::vector<__half> host_cosine(kChannels);
    std::vector<__half> host_reference(feature_count);
    load_binary(data_dir + "/ffn.bin", host_ffn.data(), host_ffn.size() * sizeof(__half));
    load_binary(data_dir + "/qkv_weight.bin", host_qkv.data(), host_qkv.size() * sizeof(__half));
    load_binary(data_dir + "/attention_scale.bin", host_scale.data(), host_scale.size() * sizeof(float));
    load_binary(data_dir + "/bias.bin", host_bias.data(), host_bias.size() * sizeof(__half));
    load_binary(data_dir + "/projection.bin", host_projection.data(), host_projection.size() * sizeof(__half));
    load_binary(data_dir + "/cosine.bin", host_cosine.data(), host_cosine.size() * sizeof(__half));
    load_binary(data_dir + "/reference.bin", host_reference.data(), host_reference.size() * sizeof(__half));

    __half* device_ffn = nullptr;
    __half* device_qkv = nullptr;
    float* device_scale = nullptr;
    __half* device_bias = nullptr;
    __half* device_projection = nullptr;
    __half* device_cosine = nullptr;
    __half* device_output = nullptr;
    check_cuda(cudaMalloc(&device_ffn, host_ffn.size() * sizeof(__half)), "cudaMalloc(ffn)");
    check_cuda(cudaMalloc(&device_qkv, host_qkv.size() * sizeof(__half)), "cudaMalloc(qkv)");
    check_cuda(cudaMalloc(&device_scale, host_scale.size() * sizeof(float)), "cudaMalloc(scale)");
    check_cuda(cudaMalloc(&device_bias, host_bias.size() * sizeof(__half)), "cudaMalloc(bias)");
    check_cuda(cudaMalloc(&device_projection, host_projection.size() * sizeof(__half)), "cudaMalloc(projection)");
    check_cuda(cudaMalloc(&device_cosine, host_cosine.size() * sizeof(__half)), "cudaMalloc(cosine)");
    check_cuda(cudaMalloc(&device_output, host_ffn.size() * sizeof(__half)), "cudaMalloc(output)");

    cudaStream_t stream = nullptr;
    check_cuda(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking),
               "cudaStreamCreateWithFlags");
    check_cuda(cudaFuncSetAttribute(
                   fused_c32_wmma_attention_kernel,
                   cudaFuncAttributeMaxDynamicSharedMemorySize,
                   static_cast<int>(kSharedBytes)),
               "cudaFuncSetAttribute(shared memory)");
    check_cuda(cudaMemcpyAsync(device_ffn, host_ffn.data(), host_ffn.size() * sizeof(__half),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(ffn)");
    check_cuda(cudaMemcpyAsync(device_qkv, host_qkv.data(), host_qkv.size() * sizeof(__half),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(qkv)");
    check_cuda(cudaMemcpyAsync(device_scale, host_scale.data(), host_scale.size() * sizeof(float),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(scale)");
    check_cuda(cudaMemcpyAsync(device_bias, host_bias.data(), host_bias.size() * sizeof(__half),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(bias)");
    check_cuda(cudaMemcpyAsync(device_projection, host_projection.data(),
                               host_projection.size() * sizeof(__half),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(projection)");
    check_cuda(cudaMemcpyAsync(device_cosine, host_cosine.data(), host_cosine.size() * sizeof(__half),
                               cudaMemcpyHostToDevice, stream), "cudaMemcpyAsync(cosine)");
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(initialization)");

    for (int i = 0; i < 3; ++i) {
        launch_kernel(device_ffn, device_qkv, device_scale, device_bias, device_projection,
                      device_cosine, device_output, height, width, stream);
    }
    check_cuda(cudaStreamSynchronize(stream), "cudaStreamSynchronize(warmup)");
    const float direct_ms = time_direct(device_ffn, device_qkv, device_scale, device_bias,
                                        device_projection, device_cosine, device_output,
                                        height, width, iterations, stream);
    const float graph_ms = time_graph(device_ffn, device_qkv, device_scale, device_bias,
                                      device_projection, device_cosine, device_output,
                                      height, width, iterations, stream);

    std::vector<__half> host_output(feature_count);
    check_cuda(cudaMemcpy(host_output.data(), device_output, host_output.size() * sizeof(__half),
                          cudaMemcpyDeviceToHost), "cudaMemcpy(output)");
    save_binary(output_path, host_output.data(), host_output.size() * sizeof(__half));

    double absolute_sum = 0.0;
    double squared_sum = 0.0;
    float max_error = 0.0f;
    bool finite = true;
    for (std::size_t i = 0; i < host_output.size(); ++i) {
        const float observed = __half2float(host_output[i]);
        const float expected = __half2float(host_reference[i]);
        if (!std::isfinite(observed)) {
            finite = false;
        }
        const float error = std::fabs(observed - expected);
        absolute_sum += error;
        squared_sum += static_cast<double>(error) * error;
        max_error = std::max(max_error, error);
    }
    const double count = static_cast<double>(host_output.size());
    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, 0), "cudaGetDeviceProperties");
    std::cout << std::setprecision(9)
              << "cuda_c32_attention_wmma_executor_probe\n"
              << "  device=" << properties.name << "\n"
              << "  arch=" << properties.major * 10 + properties.minor << "\n"
              << "  shared_bytes=" << kSharedBytes << "\n"
              << "  height=" << height << " width=" << width
              << " tokens=" << tokens << " iterations=" << iterations << "\n"
              << "  direct_ms=" << direct_ms << "\n"
              << "  graph_ms=" << graph_ms << "\n"
              << "  graph_speedup=" << direct_ms / std::max(graph_ms, 1e-9f) << "\n"
              << "  mae_vs_fused_triton=" << absolute_sum / count << "\n"
              << "  rmse_vs_fused_triton=" << std::sqrt(squared_sum / count) << "\n"
              << "  max_abs_vs_fused_triton=" << max_error << "\n"
              << "  output_finite=" << (finite ? "true" : "false") << "\n";

    cudaFree(device_ffn);
    cudaFree(device_qkv);
    cudaFree(device_scale);
    cudaFree(device_bias);
    cudaFree(device_projection);
    cudaFree(device_cosine);
    cudaFree(device_output);
    cudaStreamDestroy(stream);
    return finite ? 0 : 8;
}
