#include <d3dcompiler.h>
#include <wrl/client.h>
#include <cstdio>
#include <cstring>
#include "shader.hpp"
using Microsoft::WRL::ComPtr;
int main() {
    const char* entries[][2] = {{"VSMain","vs_5_1"},{"PSMain","ps_5_1"}};
    for (const auto& item : entries) {
        ComPtr<ID3DBlob> shader, errors;
        HRESULT hr = D3DCompile(kSharpenShader, std::strlen(kSharpenShader),
            "Glamarye", nullptr, nullptr, item[0], item[1],
            D3DCOMPILE_OPTIMIZATION_LEVEL3 | D3DCOMPILE_WARNINGS_ARE_ERRORS,
            0, &shader, &errors);
        if (FAILED(hr)) {
            if (errors) std::fprintf(stderr, "%s", static_cast<const char*>(errors->GetBufferPointer()));
            std::fprintf(stderr, "%s (%s) failed HRESULT 0x%08X\n", item[0],item[1], unsigned(hr));
            return 1;
        }
        std::printf("Compiled %s (%s) %zu bytes\n", item[0], item[1], shader->GetBufferSize());
    }
    return 0;
}
