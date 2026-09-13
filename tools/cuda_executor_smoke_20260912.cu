#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <random>
#include <vector>

namespace {

constexpr int kElements = 1 << 24;
constexpr int kThreads = 256;

__global__ void fused_affine_relu(const float* __restrict__ input,
                                  const float* __restrict__ scale,
                                  const float* __restrict__ bias,
                                  float* __restrict__ output,
                                  int n) {
    const int index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < n) {
        const float value = input[index] * scale[index & 31] + bias[index & 31];
        output[index] = value > 0.0f ? value : 0.0f;
    }
}

void check_cuda(cudaError_t status, const char* expression) {
    if (status != cudaSuccess) {
        std::cerr << expression << " failed: " << cudaGetErrorString(status) << '\n';
        std::exit(2);
    }
}

}  // namespace

int main() {
    std::vector<float> host_input(kElements, 0.25f);
    std::vector<float> host_output(kElements, 0.0f);
    std::vector<float> host_scale(32, 1.25f);
    std::vector<float> host_bias(32, -0.1f);

    float* device_input = nullptr;
    float* device_scale = nullptr;
    float* device_bias = nullptr;
    float* device_output = nullptr;
    check_cuda(cudaMalloc(&device_input, host_input.size() * sizeof(float)), "cudaMalloc(input)");
    check_cuda(cudaMalloc(&device_scale, host_scale.size() * sizeof(float)), "cudaMalloc(scale)");
    check_cuda(cudaMalloc(&device_bias, host_bias.size() * sizeof(float)), "cudaMalloc(bias)");
    check_cuda(cudaMalloc(&device_output, host_output.size() * sizeof(float)), "cudaMalloc(output)");
    check_cuda(cudaMemcpy(device_input, host_input.data(), host_input.size() * sizeof(float), cudaMemcpyHostToDevice), "cudaMemcpy(input)");
    check_cuda(cudaMemcpy(device_scale, host_scale.data(), host_scale.size() * sizeof(float), cudaMemcpyHostToDevice), "cudaMemcpy(scale)");
    check_cuda(cudaMemcpy(device_bias, host_bias.data(), host_bias.size() * sizeof(float), cudaMemcpyHostToDevice), "cudaMemcpy(bias)");

    const int blocks = (kElements + kThreads - 1) / kThreads;
    for (int i = 0; i < 20; ++i) {
        fused_affine_relu<<<blocks, kThreads>>>(device_input, device_scale, device_bias, device_output, kElements);
    }
    check_cuda(cudaGetLastError(), "warmup launch");
    check_cuda(cudaDeviceSynchronize(), "warmup synchronize");

    cudaEvent_t start = nullptr;
    cudaEvent_t stop = nullptr;
    check_cuda(cudaEventCreate(&start), "cudaEventCreate(start)");
    check_cuda(cudaEventCreate(&stop), "cudaEventCreate(stop)");
    constexpr int kIterations = 100;
    check_cuda(cudaEventRecord(start), "cudaEventRecord(start)");
    for (int i = 0; i < kIterations; ++i) {
        fused_affine_relu<<<blocks, kThreads>>>(device_input, device_scale, device_bias, device_output, kElements);
    }
    check_cuda(cudaEventRecord(stop), "cudaEventRecord(stop)");
    check_cuda(cudaEventSynchronize(stop), "cudaEventSynchronize(stop)");
    float elapsed_ms = 0.0f;
    check_cuda(cudaEventElapsedTime(&elapsed_ms, start, stop), "cudaEventElapsedTime");

    check_cuda(cudaMemcpy(host_output.data(), device_output, host_output.size() * sizeof(float), cudaMemcpyDeviceToHost), "cudaMemcpy(output)");
    const float expected = 0.25f * 1.25f - 0.1f;
    const float max_error = std::abs(*std::max_element(host_output.begin(), host_output.end(), [](float a, float b) { return std::abs(a) < std::abs(b); }) - expected);
    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, 0), "cudaGetDeviceProperties");
    std::cout << "cuda_executor_smoke\n"
              << "  device=" << properties.name << "\n"
              << "  arch=" << properties.major * 10 + properties.minor << "\n"
              << "  elements=" << kElements << " iterations=" << kIterations << "\n"
              << "  kernel_ms=" << (elapsed_ms / kIterations) << "\n"
              << "  max_error=" << max_error << "\n";

    cudaEventDestroy(start);
    cudaEventDestroy(stop);
    cudaFree(device_input);
    cudaFree(device_scale);
    cudaFree(device_bias);
    cudaFree(device_output);
    return 0;
}
