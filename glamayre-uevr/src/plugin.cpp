// Standalone Glamarye Intelligent Sharpen plugin for UEVR / DX12.
// Builds against the public UEVR 2.39 C plugin API; no UEVR or Joey patch required.
// Important: no independent GPU queue or fence; all GPU commands use UEVR's command list.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <d3dcompiler.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <uevr/API.h>
#include <algorithm>
#include <atomic>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <mutex>
#include <string>
#include <vector>
#include "shader.hpp"

using Microsoft::WRL::ComPtr;

namespace {
const UEVR_PluginInitializeParam* g_api = nullptr;
std::atomic<bool> g_enabled{false}, g_big{true}, g_edges{true}, g_split{false};
std::atomic<float> g_strength{0.4f}, g_maxChange{0.10f}, g_bias{0.020f};
std::wstring g_ini;
std::mutex g_gpuMutex;
ID3D12Device* g_device = nullptr;
ComPtr<ID3D12RootSignature> g_root;
ComPtr<ID3DBlob> g_vs, g_ps;
std::atomic<bool> g_gpuError{false};
unsigned long long g_lastReport = 0;
bool g_callbacksRegistered = false;

void logError(const char* message, HRESULT hr) {
    if (g_api && g_api->functions && g_api->functions->log_error)
        g_api->functions->log_error("Glamarye UEVR: %s (HRESULT %08X)", message, unsigned(hr));
}
bool succeeded(HRESULT hr, const char* what) {
    if (SUCCEEDED(hr)) return true;
    if (!g_gpuError.exchange(true)) logError(what, hr);
    return false;
}
float bound(float v, float lo, float hi) {
    if (!(v >= lo)) return lo;
    return std::min(v, hi);
}
void readConfig() {
    if (!g_api || !g_api->functions || !g_api->functions->get_persistent_dir) return;
    auto fn = g_api->functions->get_persistent_dir;
    unsigned n = fn(nullptr, 0);
    if (!n || n > 32760) return;
    std::wstring dir(n + 2, L'\0');
    fn(dir.data(), unsigned(dir.size()));
    dir.resize(std::wcslen(dir.c_str()));
    if (dir.empty()) return;
    if (dir.back() != L'\\') dir += L'\\';
    g_ini = dir + L"GlamaryeUEVR.ini";
    auto getInt = [](const wchar_t* key, int def) -> bool {
        return GetPrivateProfileIntW(L"Sharpen", key, def, g_ini.c_str()) != 0;
    };
    auto getFloat = [](const wchar_t* key, float def, float lo, float hi) -> float {
        wchar_t s[64]{}, d[64]{};
        swprintf_s(d, L"%.5f", double(def));
        GetPrivateProfileStringW(L"Sharpen", key, d, s, 64, g_ini.c_str());
        wchar_t* end = nullptr;
        float v = std::wcstof(s, &end);
        return end != s ? bound(v, lo, hi) : def;
    };
    g_enabled = getInt(L"Enabled", 0);
    g_big = getInt(L"Bigger", 1);
    g_edges = getInt(L"ProtectEdges", 1);
    g_split = getInt(L"SideBySide", 0);
    g_strength = getFloat(L"Strength", 0.4f, 0, 2);
    g_maxChange = getFloat(L"MaxChange", 0.10f, 0.01f, 0.5f);
    g_bias = getFloat(L"FXAABias", 0.02f, 0, 0.2f);
}
void setSetting(const char* name, float number) {
    if (!name) return;
    bool matched = true;
    wchar_t buffer[64]{};
    const wchar_t* iniKey = nullptr;
    if (_stricmp(name, "enabled") == 0) { g_enabled = number != 0; iniKey = L"Enabled"; swprintf_s(buffer, L"%u", unsigned(g_enabled.load())); }
    else if (_stricmp(name, "big") == 0) { g_big = number != 0; iniKey = L"Bigger"; swprintf_s(buffer, L"%u", unsigned(g_big.load())); }
    else if (_stricmp(name, "edges") == 0) { g_edges = number != 0; iniKey = L"ProtectEdges"; swprintf_s(buffer, L"%u", unsigned(g_edges.load())); }
    else if (_stricmp(name, "split") == 0) { g_split = number != 0; iniKey = L"SideBySide"; swprintf_s(buffer, L"%u", unsigned(g_split.load())); }
    else if (_stricmp(name, "strength") == 0) { number = bound(number, 0, 2); g_strength = number; iniKey = L"Strength"; swprintf_s(buffer, L"%.4f", double(number)); }
    else if (_stricmp(name, "limit") == 0) { number = bound(number, 0.01f, 0.5f); g_maxChange = number; iniKey = L"MaxChange"; swprintf_s(buffer, L"%.4f", double(number)); }
    else if (_stricmp(name, "bias") == 0) { number = bound(number, 0, 0.2f); g_bias = number; iniKey = L"FXAABias"; swprintf_s(buffer, L"%.4f", double(number)); }
    else matched = false;
    if (matched && !g_ini.empty()) WritePrivateProfileStringW(L"Sharpen", iniKey, buffer, g_ini.c_str());
}
void onCustomEvent(const char* event, const char* payload) {
    if (!event || std::strcmp(event, "glamayre_sharpen.set") != 0 || !payload) return;
    // Restrict accepted commands to key=scalar.
    const char* equal = std::strchr(payload, '=');
    if (!equal || equal - payload > 31) return;
    std::string name(payload, equal);
    char* end = nullptr;
    float value = std::strtof(equal + 1, &end);
    if (end == equal + 1) return;
    setSetting(name.c_str(), value);
}
void onPresent() {
    if (!g_api || !g_api->functions || !g_api->functions->dispatch_lua_event) return;
    unsigned long long now = GetTickCount64();
    if (now - g_lastReport < 400) return;
    g_lastReport = now;
    char data[256];
    snprintf(data, sizeof(data),
        "enabled=%d;big=%d;edges=%d;split=%d;strength=%.3f;limit=%.3f;bias=%.3f;gpuError=%d",
        int(g_enabled.load()), int(g_big.load()), int(g_edges.load()), int(g_split.load()),
        double(g_strength.load()), double(g_maxChange.load()), double(g_bias.load()), int(g_gpuError.load()));
    g_api->functions->dispatch_lua_event("glamayre_sharpen.status", data);
}
struct Pass {
    D3D12_RESOURCE_DESC desc{};
    DXGI_FORMAT viewFormat = DXGI_FORMAT_UNKNOWN;
    ComPtr<ID3D12Resource> scratch;
    ComPtr<ID3D12DescriptorHeap> srvHeap;
    ComPtr<ID3D12PipelineState> pso;
    struct TargetViews {
        ID3D12Resource* target = nullptr;
        ComPtr<ID3D12DescriptorHeap> heap;
    };
    std::vector<TargetViews> targets;
};
std::vector<Pass> g_passes;

DXGI_FORMAT typedFormat(DXGI_FORMAT f) {
    switch (f) {
    case DXGI_FORMAT_R8G8B8A8_TYPELESS: return DXGI_FORMAT_R8G8B8A8_UNORM;
    case DXGI_FORMAT_B8G8R8A8_TYPELESS: return DXGI_FORMAT_B8G8R8A8_UNORM;
    case DXGI_FORMAT_R16G16B16A16_TYPELESS: return DXGI_FORMAT_R16G16B16A16_FLOAT;
    case DXGI_FORMAT_R8G8B8A8_UNORM:
    case DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
    case DXGI_FORMAT_B8G8R8A8_UNORM:
    case DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:
    case DXGI_FORMAT_R10G10B10A2_UNORM:
    case DXGI_FORMAT_R16G16B16A16_FLOAT:
    case DXGI_FORMAT_R16G16B16A16_UNORM:
    case DXGI_FORMAT_R11G11B10_FLOAT:
    case DXGI_FORMAT_R32G32B32A32_FLOAT: return f;
    default: return DXGI_FORMAT_UNKNOWN;
    }
}
void resetGpu() {
    std::lock_guard lock(g_gpuMutex);
    g_passes.clear();
    g_vs.Reset(); g_ps.Reset(); g_root.Reset(); g_device = nullptr;
    g_gpuError = false;
}
void onDeviceReset() { resetGpu(); }

bool setupRootAndShaders(ID3D12Device* device) {
    if (g_root) return true;
    ComPtr<ID3DBlob> err;
    HRESULT hr = D3DCompile(kSharpenShader, std::strlen(kSharpenShader), "glamayre_uevr", nullptr, nullptr,
                            "VSMain", "vs_5_1", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &g_vs, &err);
    if (FAILED(hr)) {
        if (err && !g_gpuError.exchange(true) && g_api && g_api->functions->log_error)
            g_api->functions->log_error("Glamarye VS HLSL error: %s", static_cast<const char*>(err->GetBufferPointer()));
        return false;
    }
    err.Reset();
    hr = D3DCompile(kSharpenShader, std::strlen(kSharpenShader), "glamayre_uevr", nullptr, nullptr,
                    "PSMain", "ps_5_1", D3DCOMPILE_OPTIMIZATION_LEVEL3, 0, &g_ps, &err);
    if (FAILED(hr)) {
        if (err && !g_gpuError.exchange(true) && g_api && g_api->functions->log_error)
            g_api->functions->log_error("Glamarye PS HLSL error: %s", static_cast<const char*>(err->GetBufferPointer()));
        return false;
    }
    D3D12_DESCRIPTOR_RANGE range{};
    range.RangeType = D3D12_DESCRIPTOR_RANGE_TYPE_SRV; range.NumDescriptors = 1;
    range.BaseShaderRegister = 0; range.OffsetInDescriptorsFromTableStart = 0;
    D3D12_ROOT_PARAMETER params[2]{};
    params[0].ParameterType = D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;
    params[0].Constants.ShaderRegister = 0; params[0].Constants.Num32BitValues = 8;
    params[0].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    params[1].ParameterType = D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;
    params[1].DescriptorTable.NumDescriptorRanges = 1;
    params[1].DescriptorTable.pDescriptorRanges = &range;
    params[1].ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_STATIC_SAMPLER_DESC sampler{};
    sampler.Filter = D3D12_FILTER_MIN_MAG_MIP_LINEAR;
    sampler.AddressU = sampler.AddressV = sampler.AddressW = D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
    sampler.MaxLOD = D3D12_FLOAT32_MAX;
    sampler.ShaderRegister = 0; sampler.ShaderVisibility = D3D12_SHADER_VISIBILITY_PIXEL;
    D3D12_ROOT_SIGNATURE_DESC sig{};
    sig.NumParameters = 2; sig.pParameters = params;
    sig.NumStaticSamplers = 1; sig.pStaticSamplers = &sampler;
    sig.Flags = D3D12_ROOT_SIGNATURE_FLAG_ALLOW_INPUT_ASSEMBLER_INPUT_LAYOUT;
    ComPtr<ID3DBlob> sigBlob;
    if (!succeeded(D3D12SerializeRootSignature(&sig, D3D_ROOT_SIGNATURE_VERSION_1,
                    &sigBlob, &err), "Serialize root signature")) return false;
    return succeeded(device->CreateRootSignature(0, sigBlob->GetBufferPointer(),
        sigBlob->GetBufferSize(), IID_PPV_ARGS(&g_root)), "Create root signature");
}
bool makePass(ID3D12Device* device, const D3D12_RESOURCE_DESC& d, DXGI_FORMAT format, Pass& pass) {
    pass.desc = d; pass.viewFormat = format;
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC copyDesc = d;
    copyDesc.Flags = D3D12_RESOURCE_FLAG_NONE;
    if (!succeeded(device->CreateCommittedResource(&heap, D3D12_HEAP_FLAG_NONE,
        &copyDesc, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, nullptr,
        IID_PPV_ARGS(&pass.scratch)), "Create snapshot texture")) return false;
    D3D12_DESCRIPTOR_HEAP_DESC desc{};
    desc.NumDescriptors = 1; desc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;
    desc.Flags = D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    if (!succeeded(device->CreateDescriptorHeap(&desc, IID_PPV_ARGS(&pass.srvHeap)),
         "Create SRV heap")) return false;
    D3D12_SHADER_RESOURCE_VIEW_DESC srv{};
    srv.Format = format; srv.Shader4ComponentMapping = D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
    srv.ViewDimension = D3D12_SRV_DIMENSION_TEXTURE2DARRAY;
    srv.Texture2DArray.ArraySize = d.DepthOrArraySize;
    srv.Texture2DArray.MipLevels = 1;
    device->CreateShaderResourceView(pass.scratch.Get(), &srv, pass.srvHeap->GetCPUDescriptorHandleForHeapStart());
    D3D12_GRAPHICS_PIPELINE_STATE_DESC state{};
    state.pRootSignature = g_root.Get();
    state.VS = {g_vs->GetBufferPointer(), g_vs->GetBufferSize()};
    state.PS = {g_ps->GetBufferPointer(), g_ps->GetBufferSize()};
    state.BlendState.AlphaToCoverageEnable = FALSE;
    state.BlendState.IndependentBlendEnable = FALSE;
    for (auto& renderTarget : state.BlendState.RenderTarget) {
        renderTarget.BlendEnable = FALSE;
        renderTarget.RenderTargetWriteMask = D3D12_COLOR_WRITE_ENABLE_ALL;
    }
    state.SampleMask = UINT_MAX;
    state.RasterizerState.FillMode = D3D12_FILL_MODE_SOLID;
    state.RasterizerState.CullMode = D3D12_CULL_MODE_NONE;
    state.RasterizerState.DepthClipEnable = TRUE;
    state.DepthStencilState.DepthEnable = FALSE;
    state.DepthStencilState.StencilEnable = FALSE;
    state.PrimitiveTopologyType = D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
    state.NumRenderTargets = 1;
    state.RTVFormats[0] = format;
    state.SampleDesc.Count = 1;
    return succeeded(device->CreateGraphicsPipelineState(&state, IID_PPV_ARGS(&pass.pso)),
                     "Create pipeline state");
}
struct Constants {
    float width, height, strength, maxChange, fxaaBias, maximumColour;
    uint32_t flags, layer;
};
static_assert(sizeof(Constants) == 32);
void barrier(ID3D12GraphicsCommandList* cmd, ID3D12Resource* res,
             D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER b{};
    b.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = res; b.Transition.Subresource = D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = before; b.Transition.StateAfter = after;
    cmd->ResourceBarrier(1, &b);
}
void onPostDX12(void* list, void* resource, void* rtvHandle) {
    if (!g_enabled || g_strength.load() <= 0 || !list || !resource || g_gpuError) return;
    auto* cmd = static_cast<ID3D12GraphicsCommandList*>(list);
    auto* target = static_cast<ID3D12Resource*>(resource);
    D3D12_RESOURCE_DESC desc = target->GetDesc();
    // Unsupported paths are skipped rather than touching the game's GPU state.
    if (desc.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.SampleDesc.Count != 1 ||
        desc.MipLevels != 1 || !desc.Width || !desc.Height || desc.DepthOrArraySize > 2) return;
    DXGI_FORMAT format = typedFormat(desc.Format);
    if (format == DXGI_FORMAT_UNKNOWN) return;
    std::lock_guard lock(g_gpuMutex);
    ComPtr<ID3D12Device> device;
    if (!succeeded(cmd->GetDevice(IID_PPV_ARGS(&device)), "Get DX12 device")) return;
    if (g_device != device.Get()) {
        // Different devices should only arrive after UEVR on_device_reset.
        if (g_device != nullptr) return;
        g_device = device.Get();
    }
    if (!setupRootAndShaders(device.Get())) return;
    Pass* pass = nullptr;
    for (auto& cached : g_passes) {
        if (cached.desc.Width == desc.Width && cached.desc.Height == desc.Height &&
            cached.desc.Format == desc.Format && cached.desc.DepthOrArraySize == desc.DepthOrArraySize) {
            pass = &cached; break;
        }
    }
    if (!pass) {
        if (g_passes.size() >= 16) return;  // bound persistent allocations across resize events
        Pass p;
        if (!makePass(device.Get(), desc, format, p)) return;
        g_passes.push_back(std::move(p));
        pass = &g_passes.back();
    }

    // UEVR API.h documents callback target as RENDER_TARGET; preserve that contract.
    barrier(cmd, target, D3D12_RESOURCE_STATE_RENDER_TARGET, D3D12_RESOURCE_STATE_COPY_SOURCE);
    barrier(cmd, pass->scratch.Get(), D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE, D3D12_RESOURCE_STATE_COPY_DEST);
    cmd->CopyResource(pass->scratch.Get(), target);
    barrier(cmd, pass->scratch.Get(), D3D12_RESOURCE_STATE_COPY_DEST, D3D12_RESOURCE_STATE_PIXEL_SHADER_RESOURCE);
    barrier(cmd, target, D3D12_RESOURCE_STATE_COPY_SOURCE, D3D12_RESOURCE_STATE_RENDER_TARGET);

    cmd->SetGraphicsRootSignature(g_root.Get());
    cmd->SetPipelineState(pass->pso.Get());
    ID3D12DescriptorHeap* heaps[] = {pass->srvHeap.Get()};
    cmd->SetDescriptorHeaps(1, heaps);
    cmd->SetGraphicsRootDescriptorTable(1, pass->srvHeap->GetGPUDescriptorHandleForHeapStart());
    cmd->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
    D3D12_VIEWPORT vp{0, 0, float(desc.Width), float(desc.Height), 0, 1};
    D3D12_RECT scissor{0, 0, LONG(desc.Width), LONG(desc.Height)};
    cmd->RSSetViewports(1, &vp);
    cmd->RSSetScissorRects(1, &scissor);
    // The supplied UEVR RTV is correct for the current swapchain image.
    // For texture arrays, cache immutable per-resource RTV descriptors so rotating
    // headset images never point at the wrong target and GPU in-flight descriptors
    // are not rewritten.
    D3D12_CPU_DESCRIPTOR_HANDLE output{};
    unsigned step = device->GetDescriptorHandleIncrementSize(D3D12_DESCRIPTOR_HEAP_TYPE_RTV);
    if (desc.DepthOrArraySize == 1 && rtvHandle) {
        output = *static_cast<D3D12_CPU_DESCRIPTOR_HANDLE*>(rtvHandle);
    } else {
        Pass::TargetViews* views = nullptr;
        for (auto& v : pass->targets) if (v.target == target) { views = &v; break; }
        if (!views) {
            if (pass->targets.size() >= 16) return;
            D3D12_DESCRIPTOR_HEAP_DESC rdesc{};
            rdesc.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
            rdesc.NumDescriptors = desc.DepthOrArraySize;
            Pass::TargetViews v;
            v.target = target;
            if (!succeeded(device->CreateDescriptorHeap(&rdesc, IID_PPV_ARGS(&v.heap)),
                           "Create per-resource RTV heap")) return;
            auto base = v.heap->GetCPUDescriptorHandleForHeapStart();
            for (unsigned i=0; i < desc.DepthOrArraySize; ++i) {
                D3D12_RENDER_TARGET_VIEW_DESC dsv{};
                dsv.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2DARRAY;
                dsv.Format = format; dsv.Texture2DArray.ArraySize=1;
                dsv.Texture2DArray.FirstArraySlice = i;
                D3D12_CPU_DESCRIPTOR_HANDLE slot{base.ptr + SIZE_T(step) * i};
                device->CreateRenderTargetView(target, &dsv, slot);
            }
            pass->targets.push_back(std::move(v));
            views = &pass->targets.back();
        }
        output = views->heap->GetCPUDescriptorHandleForHeapStart();
    }
    Constants constants{float(desc.Width), float(desc.Height),
        g_strength.load(), g_maxChange.load(), g_bias.load(),
        (format == DXGI_FORMAT_R16G16B16A16_FLOAT || format == DXGI_FORMAT_R11G11B10_FLOAT
            || format == DXGI_FORMAT_R32G32B32A32_FLOAT) ? 16.0f : 1.0f,
        (g_edges ? 1u : 0u) | (g_big ? 2u : 0u) | (g_split && desc.DepthOrArraySize == 1 ? 4u : 0u), 0u};
    for (uint32_t eye = 0; eye < desc.DepthOrArraySize; ++eye) {
        constants.layer = eye;
        cmd->SetGraphicsRoot32BitConstants(0, 8, &constants, 0);
        D3D12_CPU_DESCRIPTOR_HANDLE out{output.ptr + SIZE_T(step) * eye};
        cmd->OMSetRenderTargets(1, &out, FALSE, nullptr);
        cmd->DrawInstanced(3, 1, 0, 0);
    }
}
} // namespace

extern "C" __declspec(dllexport) void uevr_plugin_required_version(UEVR_PluginVersion* v) {
    if (v) *v = {UEVR_PLUGIN_VERSION_MAJOR, UEVR_PLUGIN_VERSION_MINOR, UEVR_PLUGIN_VERSION_PATCH};
}
extern "C" __declspec(dllexport) bool uevr_plugin_initialize(const UEVR_PluginInitializeParam* api) {
    if (!api || !api->version || api->version->major != UEVR_PLUGIN_VERSION_MAJOR ||
        api->version->minor < UEVR_PLUGIN_VERSION_MINOR ||
        !api->callbacks || !api->functions || !api->renderer ||
        !api->callbacks->on_post_render_vr_framework_dx12 ||
        !api->callbacks->on_device_reset || !api->callbacks->on_present ||
        !api->callbacks->on_custom_event) return false;
    if (g_callbacksRegistered) return true;
    g_api = api;
    readConfig();
    bool a = api->callbacks->on_post_render_vr_framework_dx12(onPostDX12);
    bool b = api->callbacks->on_device_reset(onDeviceReset);
    bool c = api->callbacks->on_present(onPresent);
    bool d = api->callbacks->on_custom_event(onCustomEvent);
    if (!a || !b || !c || !d) {
        if (api->functions->remove_callback) {
            if (a) api->functions->remove_callback(reinterpret_cast<void*>(&onPostDX12));
            if (b) api->functions->remove_callback(reinterpret_cast<void*>(&onDeviceReset));
            if (c) api->functions->remove_callback(reinterpret_cast<void*>(&onPresent));
            if (d) api->functions->remove_callback(reinterpret_cast<void*>(&onCustomEvent));
        }
        return false;
    }
    g_callbacksRegistered = true;
    if (api->functions->log_info) api->functions->log_info("Glamarye UEVR v0.1 loaded (DX12)");
    return true;
}
BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, void*) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(module);
    return TRUE;
}
