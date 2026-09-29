#include <cuda_fp16.h>
#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

constexpr int kChannels = 32;
constexpr int kWindow = 8;
constexpr int kWindowTokens = kWindow * kWindow;
constexpr int kQkvChannels = 96;
constexpr int kThreads = 256;

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
// boundary. The result is decoded back to FP16 because the logical graph stores
// the published value in a half tensor after the FP8 round trip.
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

// The recovered C32 window path uses a packed half-affine exponential. This is
// the scalar equivalent of the even lane in the paired Triton implementation.
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

// One block owns one 8x8 attention window. QKV projection, normalization,
// recovered exponential/weight publication, weighted V, output projection,
// and residual are kept within the block's shared-memory working set. This is
// an independent speed experiment, not NVIDIA's native kernel.
__global__ void fused_c32_attention_kernel(
    const __half* __restrict__ ffn,
    const __half* __restrict__ qkv_weight,
    const float* __restrict__ attention_scale,
    const __half* __restrict__ bias,
    const __half* __restrict__ projection,
    const __half* __restrict__ cosine,
    __half* __restrict__ output,
    int height,
    int width) {
    __shared__ __half x_shared[kWindowTokens * kChannels];
    __shared__ __half qkv_shared[kChannels * kQkvChannels];
    __shared__ __half q_shared[kWindowTokens * kChannels];
    __shared__ __half k_shared[kWindowTokens * kChannels];
    __shared__ __half v_shared[kWindowTokens * kChannels];
    __shared__ __half projection_shared[kChannels * kChannels];
    __shared__ __half bias_shared[kWindowTokens * kWindowTokens];
    __shared__ __half cosine_shared[kChannels];
    __shared__ __half probability_shared[kWindowTokens * kWindowTokens];

    const int tid = threadIdx.x;
    const int window = static_cast<int>(blockIdx.x);
    const std::size_t total_windows = static_cast<std::size_t>(height / kWindow) *
                                      static_cast<std::size_t>(width / kWindow);
    if (static_cast<std::size_t>(window) >= total_windows) {
        return;
    }

    for (int index = tid; index < kWindowTokens * kChannels; index += kThreads) {
        const int local_token = index / kChannels;
        const int channel = index % kChannels;
        x_shared[index] = ffn[global_token_index(window, local_token, width) * kChannels + channel];
    }
    for (int index = tid; index < kChannels * kQkvChannels; index += kThreads) {
        qkv_shared[index] = qkv_weight[index];
    }
    for (int index = tid; index < kChannels * kChannels; index += kThreads) {
        projection_shared[index] = projection[index];
    }
    for (int index = tid; index < kWindowTokens * kWindowTokens; index += kThreads) {
        bias_shared[index] = bias[index];
    }
    for (int index = tid; index < kChannels; index += kThreads) {
        cosine_shared[index] = cosine[index];
    }
    __syncthreads();

    // Project the 64 tokens to Q/K/V. Each thread computes multiple output
    // elements; the weights and input are shared by the whole window.
    for (int index = tid; index < kWindowTokens * kQkvChannels; index += kThreads) {
        const int row = index / kQkvChannels;
        const int channel = index % kQkvChannels;
        float accumulator = 0.0f;
        for (int k = 0; k < kChannels; ++k) {
            accumulator += __half2float(x_shared[row * kChannels + k]) *
                           __half2float(qkv_shared[k * kQkvChannels + channel]);
        }
        const __half value = __float2half_rn(accumulator);
        if (channel < kChannels) {
            q_shared[row * kChannels + channel] = value;
        } else if (channel < 2 * kChannels) {
            k_shared[row * kChannels + channel - kChannels] = value;
        } else {
            v_shared[row * kChannels + channel - 2 * kChannels] = value;
        }
    }
    __syncthreads();

    const __half scale = __float2half_rn(attention_scale[0]);
    if (tid < kWindowTokens) {
        const int row = tid;
        float q_norm = 0.0f;
        float k_norm = 0.0f;
        for (int channel = 0; channel < kChannels; ++channel) {
            const float q_value = __half2float(q_shared[row * kChannels + channel]);
            const float k_value = __half2float(k_shared[row * kChannels + channel]);
            q_norm += q_value * q_value;
            k_norm += k_value * k_value;
        }
        const __half q_reciprocal = __float2half_rn(rsqrtf(fmaxf(q_norm, 0.00006198883056640625f)));
        const __half k_reciprocal = __float2half_rn(rsqrtf(fmaxf(k_norm, 0.00006198883056640625f)));
        for (int channel = 0; channel < kChannels; ++channel) {
            __half q_value = half_mul(q_shared[row * kChannels + channel], q_reciprocal);
            q_value = half_mul(q_value, scale);
            q_shared[row * kChannels + channel] = round_fp8_half(q_value);
            k_shared[row * kChannels + channel] = round_fp8_half(
                half_mul(k_shared[row * kChannels + channel], k_reciprocal));
            v_shared[row * kChannels + channel] = round_fp8_half(v_shared[row * kChannels + channel]);
        }
    }
    __syncthreads();

    // Compute and publish one normalized attention row per thread. The
    // probability matrix is shared so the following weighted-V phase can reuse
    // it without an intermediate global-memory write.
    if (tid < kWindowTokens) {
        float sum = 0.0f;
        for (int key = 0; key < kWindowTokens; ++key) {
            float dot = 0.0f;
            for (int channel = 0; channel < kChannels; ++channel) {
                dot += __half2float(q_shared[tid * kChannels + channel]) *
                       __half2float(k_shared[key * kChannels + channel]);
            }
            const __half score = __float2half_rn(
                dot + __half2float(bias_shared[tid * kWindowTokens + key]));
            const __half weight = recovered_exp(score);
            probability_shared[tid * kWindowTokens + key] = weight;
            sum += __half2float(weight);
        }
        const __half denominator = __float2half_rn(sum);
        const __half reciprocal = __float2half_rn(1.0f / __half2float(denominator));
        for (int key = 0; key < kWindowTokens; ++key) {
            probability_shared[tid * kWindowTokens + key] = round_fp8_half(
                half_mul(probability_shared[tid * kWindowTokens + key], reciprocal));
        }
    }
    __syncthreads();

    if (tid < kWindowTokens) {
        __half attended[kChannels];
        for (int channel = 0; channel < kChannels; ++channel) {
            float accumulator = 0.0f;
            for (int key = 0; key < kWindowTokens; ++key) {
                accumulator += __half2float(probability_shared[tid * kWindowTokens + key]) *
                               __half2float(v_shared[key * kChannels + channel]);
            }
            attended[channel] = round_fp8_half(__float2half_rn(accumulator));
        }

        const std::size_t output_row = global_token_index(window, tid, width);
        for (int channel = 0; channel < kChannels; ++channel) {
            float accumulator = 0.0f;
            for (int k = 0; k < kChannels; ++k) {
                accumulator += __half2float(attended[k]) *
                               __half2float(projection_shared[k * kChannels + channel]);
            }
            const __half branch = __float2half_rn(accumulator);
            const __half residual = half_mul(
                x_shared[tid * kChannels + channel], cosine_shared[channel]);
            output[output_row * kChannels + channel] = half_add(branch, residual);
        }
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
    fused_c32_attention_kernel<<<windows, kThreads, 0, stream>>>(
        ffn, qkv_weight, attention_scale, bias, projection, cosine, output, height, width);
    check_cuda(cudaGetLastError(), "fused_c32_attention_kernel");
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
        launch_kernel(ffn, qkv_weight, attention_scale, bias, projection, cosine,
                      output, height, width, stream);
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
    launch_kernel(ffn, qkv_weight, attention_scale, bias, projection, cosine,
                  output, height, width, stream);
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
    const std::size_t ffn_count = tokens * kChannels;
    std::vector<__half> host_ffn(ffn_count);
    std::vector<__half> host_qkv(kChannels * kQkvChannels);
    std::vector<float> host_scale(1);
    std::vector<__half> host_bias(kWindowTokens * kWindowTokens);
    std::vector<__half> host_projection(kChannels * kChannels);
    std::vector<__half> host_cosine(kChannels);
    std::vector<__half> host_reference(ffn_count);
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

    std::vector<__half> host_output(ffn_count);
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
              << "cuda_c32_attention_executor_probe\n"
              << "  device=" << properties.name << "\n"
              << "  arch=" << properties.major * 10 + properties.minor << "\n"
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
