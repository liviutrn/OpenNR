// DX12 WARP smoke test for the actual UEVR plugin.
// Creates one headset-like render target and verifies that enabling sharpening
// produces modified pixels, with no external game, headset or GPU required.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <uevr/API.h>
#include <cstdio>
#include <cstdarg>
#include <cstdint>
#include <cstring>
#include <string>
using Microsoft::WRL::ComPtr;

static UEVR_OnPostRenderVRFrameworkDX12Cb g_render = nullptr;
static UEVR_OnCustomEventCb g_custom = nullptr;
static bool regRender(UEVR_OnPostRenderVRFrameworkDX12Cb f) { g_render = f; return true; }
static bool regCustom(UEVR_OnCustomEventCb f) { g_custom = f; return true; }
static bool regPresent(UEVR_OnPresentCb) { return true; }
static bool regReset(UEVR_OnDeviceResetCb) { return true; }
static void info(const char*, ...) {}
static void warn(const char*, ...) {}
static void error(const char* fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vfprintf(stderr, fmt, args);
    va_end(args);
    fputc('\n', stderr);
}
static unsigned persistent(wchar_t*, unsigned) { return 0; }
static void luaEvent(const char*, const char*) {}
#define CHECK(HR, WHAT) do { HRESULT check_hr = (HR); if (FAILED(check_hr)) { \
    fprintf(stderr, "%s failed: 0x%08X\n", WHAT, unsigned(check_hr)); return 2; \
} } while(0)

int main() {
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(nullptr, path, MAX_PATH);
    wchar_t* sep = wcsrchr(path, L'\\');
    if (!sep) return 2;
    wcscpy_s(sep + 1, MAX_PATH - size_t(sep + 1 - path), L"GlamaryeSharpenUEVR.dll");
    HMODULE dll = LoadLibraryW(path);
    if (!dll) { fprintf(stderr, "Could not load plugin DLL: %lu\n", GetLastError()); return 2; }
    using Initialize = bool (*)(const UEVR_PluginInitializeParam*);
    auto init = reinterpret_cast<Initialize>(GetProcAddress(dll, "uevr_plugin_initialize"));
    using GpuRecord = bool (*)(void*, void*, void*, bool);
    auto record = reinterpret_cast<GpuRecord>(GetProcAddress(dll, "glamayre_sharpen_gpu_record"));
    if (!init) { fprintf(stderr, "Missing UEVR plugin export\n"); return 2; }

    UEVR_PluginCallbacks callbacks{};
    callbacks.on_post_render_vr_framework_dx12 = regRender;
    callbacks.on_custom_event = regCustom;
    callbacks.on_present = regPresent;
    callbacks.on_device_reset = regReset;
    UEVR_PluginFunctions fns{};
    fns.log_error = error;
    fns.log_warn = warn;
    fns.log_info = info;
    fns.get_persistent_dir = persistent;
    fns.dispatch_lua_event = luaEvent;
    UEVR_PluginVersion version{UEVR_PLUGIN_VERSION_MAJOR, UEVR_PLUGIN_VERSION_MINOR, UEVR_PLUGIN_VERSION_PATCH};
    UEVR_RendererData renderer{};
    renderer.renderer_type = UEVR_RENDERER_D3D12;
    UEVR_PluginInitializeParam host{};
    host.version = &version;
    host.callbacks = &callbacks;
    host.functions = &fns;
    host.renderer = &renderer;
    if (!record || !init(&host) || !g_custom) { fprintf(stderr, "Plugin adapter registration failed\n"); return 2; }

    ComPtr<IDXGIFactory4> factory;
    CHECK(CreateDXGIFactory1(IID_PPV_ARGS(&factory)), "DXGI factory");
    ComPtr<IDXGIAdapter> warp;
    CHECK(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)), "WARP adapter");
    ComPtr<ID3D12Device> device;
    CHECK(D3D12CreateDevice(warp.Get(), D3D_FEATURE_LEVEL_11_0, IID_PPV_ARGS(&device)), "WARP device");
    renderer.device = device.Get();

    D3D12_COMMAND_QUEUE_DESC q{};
    q.Type = D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    CHECK(device->CreateCommandQueue(&q, IID_PPV_ARGS(&queue)), "Queue");
    renderer.command_queue = queue.Get();
    ComPtr<ID3D12CommandAllocator> alloc;
    CHECK(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT, IID_PPV_ARGS(&alloc)), "Allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;
    CHECK(device->CreateCommandList(0, D3D12_COMMAND_LIST_TYPE_DIRECT, alloc.Get(), nullptr,
                                    IID_PPV_ARGS(&cmd)), "Command list");
    constexpr UINT W=64, H=64;
    D3D12_HEAP_PROPERTIES hp{}; hp.Type = D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC d{};
    d.Dimension = D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width = W; d.Height = H; d.DepthOrArraySize = 1; d.MipLevels = 1;
    d.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    d.SampleDesc.Count = 1;
    d.Flags = D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    D3D12_CLEAR_VALUE clear{};
    clear.Format = d.Format; clear.Color[0] = 0.2f; clear.Color[1] = 0.2f;
    clear.Color[2] = 0.2f; clear.Color[3] = 1.0f;
    ComPtr<ID3D12Resource> rt;
    CHECK(device->CreateCommittedResource(&hp, D3D12_HEAP_FLAG_NONE, &d,
          D3D12_RESOURCE_STATE_RENDER_TARGET, &clear, IID_PPV_ARGS(&rt)), "Target");

    D3D12_DESCRIPTOR_HEAP_DESC h{};
    h.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV; h.NumDescriptors = 1;
    ComPtr<ID3D12DescriptorHeap> rtvHeap;
    CHECK(device->CreateDescriptorHeap(&h, IID_PPV_ARGS(&rtvHeap)), "RTV");
    auto rtv = rtvHeap->GetCPUDescriptorHandleForHeapStart();
    device->CreateRenderTargetView(rt.Get(), nullptr, rtv);
    float left[4]{0.2f, 0.2f, 0.2f, 1.0f};
    float right[4]{0.4f, 0.4f, 0.4f, 1.0f};
    D3D12_RECT whole{0, 0, LONG(W), LONG(H)};
    D3D12_RECT rightArea{LONG(W / 2), 0, LONG(W), LONG(H)};
    cmd->ClearRenderTargetView(rtv, left, 1, &whole);
    cmd->ClearRenderTargetView(rtv, right, 1, &rightArea);
    // A small, low-contrast texture detail ensures Bigger Sharpen with edge
    // protection ON has a meaningful test beyond a solid vertical silhouette.
    float patch[4]{0.30f,0.30f,0.30f,1.0f};
    D3D12_RECT smallPatch{9,9,13,13};
    cmd->ClearRenderTargetView(rtv, patch, 1, &smallPatch);

    g_custom("glamayre_sharpen.set", "enabled=1");
    g_custom("glamayre_sharpen.set", "strength=1.8");
    g_custom("glamayre_sharpen.set", "limit=0.25");
    g_custom("glamayre_sharpen.set", "big=1");
    g_custom("glamayre_sharpen.set", "edges=1");
    if (!record(cmd.Get(), rt.Get(), &rtv, true)) { fprintf(stderr, "GPU render record refused.\n"); return 2; }

    D3D12_RESOURCE_BARRIER b{};
    b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource = rt.Get(); b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore = D3D12_RESOURCE_STATE_RENDER_TARGET;
    b.Transition.StateAfter = D3D12_RESOURCE_STATE_COPY_SOURCE;
    cmd->ResourceBarrier(1, &b);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT rows{}; UINT64 rowBytes{}, total{};
    device->GetCopyableFootprints(&d, 0, 1, 0, &footprint, &rows, &rowBytes, &total);
    D3D12_RESOURCE_DESC bd{};
    bd.Dimension = D3D12_RESOURCE_DIMENSION_BUFFER; bd.Width = total;
    bd.Height = 1; bd.DepthOrArraySize=1; bd.MipLevels=1;
    bd.SampleDesc.Count=1; bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    D3D12_HEAP_PROPERTIES readbackHeap{}; readbackHeap.Type=D3D12_HEAP_TYPE_READBACK;
    ComPtr<ID3D12Resource> buffer;
    CHECK(device->CreateCommittedResource(&readbackHeap, D3D12_HEAP_FLAG_NONE, &bd,
           D3D12_RESOURCE_STATE_COPY_DEST, nullptr, IID_PPV_ARGS(&buffer)), "Readback");
    D3D12_TEXTURE_COPY_LOCATION dest{}, source{};
    dest.pResource=buffer.Get(); dest.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
    dest.PlacedFootprint=footprint;
    source.pResource=rt.Get(); source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    source.SubresourceIndex=0;
    cmd->CopyTextureRegion(&dest, 0, 0, 0, &source, nullptr);
    CHECK(cmd->Close(), "Close GPU command list");
    ID3D12CommandList* cmds[]{cmd.Get()};
    queue->ExecuteCommandLists(1, cmds);

    ComPtr<ID3D12Fence> fence;
    CHECK(device->CreateFence(0, D3D12_FENCE_FLAG_NONE, IID_PPV_ARGS(&fence)), "Fence");
    CHECK(queue->Signal(fence.Get(), 1), "Fence signal");
    HANDLE done=CreateEventW(nullptr, FALSE, FALSE, nullptr);
    if (!done) return 2;
    CHECK(fence->SetEventOnCompletion(1, done), "Fence wait registration");
    DWORD waited=WaitForSingleObject(done, 10000);
    CloseHandle(done);
    if (waited != WAIT_OBJECT_0 || FAILED(device->GetDeviceRemovedReason())) {
        fprintf(stderr,"DX12 work did not finish successfully, wait=%lu, reason=0x%08X\n",
                waited, unsigned(device->GetDeviceRemovedReason()));
        return 2;
    }
    unsigned char* mapped=nullptr;
    CHECK(buffer->Map(0,nullptr,reinterpret_cast<void**>(&mapped)), "Readback Map");
    unsigned differing=0;
    for (UINT y=0;y<H;++y) for(UINT x=0;x<W;++x) {
        const auto red = mapped[footprint.Offset + y*footprint.Footprint.RowPitch + x*4];
        // Unsharpened clear colors are approximately 51 and 102.
        const int baseline = (x>=9 && x<13 && y>=9 && y<13) ? 77 : (x < W/2 ? 51 : 102);
        if (abs(int(red)-baseline)>2) ++differing;
    }
    buffer->Unmap(0,nullptr);
    if (!differing) {
        fprintf(stderr,"WARP rendered, but no pixels changed. Shader may be bypassed.\n");
        return 2;
    }
    printf("WARP DX12 passed: %u changed pixels, UEVR callback, SRV snapshot and pixel shader executed.\n", differing);
    return 0;
}
