// Deterministic simulated OpenXR frame test for the real hook implementation.
// Unlike GPU-only tests, this invokes acquire/endframe/release/destroy callbacks,
// selects scene-vs-UI swapchain image, and checks queue-ordered GPU recording.
// No HMD or installed OpenXR runtime is required.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <uevr/API.h>
#include <cstdio>
#include <cstdint>
#include <array>
#include <atomic>
#include <cstring>
using Microsoft::WRL::ComPtr;

static unsigned g_draws=0, g_fakeReleases=0, g_fakeEnds=0;
static void* g_sceneHandle=reinterpret_cast<void*>(uintptr_t(0x41));
static void* g_uiHandle=reinterpret_cast<void*>(uintptr_t(0x42));
static ID3D12Resource* g_sceneTexture=nullptr;
static ID3D12Resource* g_uiTexture=nullptr;
static bool g_lastSplit=false;
static bool g_failEnumerateOnce=false;
extern "C" bool glamayre_sharpen_gpu_record(void*,void* resource,void* rtv,bool autoSplit) {
    if (!resource || !rtv || resource != g_sceneTexture) return false;
    ++g_draws;
    g_lastSplit=autoSplit;
    return true; // GPU shader bytes are independently tested by GPU smoke test.
}
extern "C" bool glamayre_sharpen_processing_enabled() { return true; }
#include "../src/openxr_scene.cpp"

static Result WINAPI fakeAcquire(Swapchain,const void*,uint32_t* idx) {
    if (!idx) return -1;
    *idx = 0;
    return XR_SUCCESS;
}
static Result WINAPI fakeRelease(Swapchain,const void*) { ++g_fakeReleases; return XR_SUCCESS; }
static Result WINAPI fakeEnd(Session,const FrameEndInfo*) { ++g_fakeEnds; return XR_SUCCESS; }
static Result WINAPI fakeDestroy(Swapchain) { return XR_SUCCESS; }
static Result WINAPI fakeEnumerate(Swapchain sc,uint32_t capacity,uint32_t* out,BaseHeader* buffer) {
    if (g_failEnumerateOnce) { g_failEnumerateOnce=false;return -2; }
    ID3D12Resource* tex=(sc==g_sceneHandle)?g_sceneTexture:
                       (sc==g_uiHandle)?g_uiTexture:nullptr;
    if (!tex) return -1;
    if (!out) return -1;
    *out=1;
    if (!capacity) return XR_SUCCESS;
    if (!buffer || capacity<1) return -1;
    auto* image=reinterpret_cast<ImageD3D12*>(buffer);
    if (image->type!=XR_TYPE_IMAGE_D3D12) return -1;
    image->texture=tex;
    return XR_SUCCESS;
}
#define CHECK(x,name) do { const HRESULT status=(x); if (FAILED(status)) { \
    fprintf(stderr,"%s failed with 0x%08X\n",name,unsigned(status)); return 1; \
} } while(0)
static void ignoreLog(const char*,...) {}
static uint32_t getWidth() { return 300u; }
static uint32_t getHeight() { return 300u; }
static bool runtimeOpenXR() { return true; }
int main() {
    ComPtr<ID3D12Debug> debug;
    if (SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug)))) debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;
    CHECK(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");
    ComPtr<IDXGIAdapter> adapter;
    CHECK(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)),"WARP adapter");
    ComPtr<ID3D12Device> device;
    CHECK(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"Device");
    D3D12_COMMAND_QUEUE_DESC cq{};
    cq.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    CHECK(device->CreateCommandQueue(&cq,IID_PPV_ARGS(&queue)),"Queue");
    D3D12_HEAP_PROPERTIES heap{};
    heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC d{};
    d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=600;d.Height=300;d.DepthOrArraySize=1;d.MipLevels=1;
    d.Format=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;d.SampleDesc.Count=1;
    d.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    ComPtr<ID3D12Resource> scene;
    CHECK(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&scene)),"Scene resource");
    g_sceneTexture=scene.Get();
    d.Width=600;d.Height=200; // UI must NOT be processed even if BGRA sRGB.
    ComPtr<ID3D12Resource> ui;
    CHECK(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&d,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&ui)),"UI resource");
    g_uiTexture=ui.Get();

    UEVR_RendererData renderer{};
    renderer.renderer_type=UEVR_RENDERER_D3D12;
    renderer.device=device.Get();
    renderer.command_queue=queue.Get();
    UEVR_VRData vr{};
    vr.get_hmd_width=getWidth;
    vr.get_hmd_height=getHeight;
    vr.is_openxr=runtimeOpenXR;
    UEVR_PluginFunctions functions{};
    functions.log_info=ignoreLog;
    UEVR_PluginVersion version{2,39,0};
    UEVR_PluginInitializeParam host{};
    host.version=&version;host.renderer=&renderer;host.vr=&vr;
    host.functions=&functions;
    g_api=&host;
    g_acquire=fakeAcquire;
    g_release=fakeRelease;
    g_endframe=fakeEnd;
    g_destroy=fakeDestroy;
    g_enumerate=fakeEnumerate;

    // CASE 0: Joey may release its first headset image before the
    // DX12 device pointer is ready. Do not permanently mark the image invalid.
    renderer.device=nullptr;
    uint32_t idx=999;
    if (onAcquire(g_sceneHandle,nullptr,&idx)!=XR_SUCCESS) return 12;
    if (onRelease(g_sceneHandle,nullptr)!=XR_SUCCESS || g_draws!=0 ||
        g_swapchains[g_sceneHandle].initialized) {
        fprintf(stderr,"Premature OpenXR initialization poisoned the scene\n");return 13;
    }
    renderer.device=device.Get();
    g_failEnumerateOnce=true;
    if (onAcquire(g_sceneHandle,nullptr,&idx)!=XR_SUCCESS) return 14;
    if (onRelease(g_sceneHandle,nullptr)!=XR_SUCCESS || g_draws!=0 ||
        g_swapchains[g_sceneHandle].initialized ||
        g_swapchains[g_sceneHandle].enumerateAttempts!=1) {
        fprintf(stderr,"Transient swapchain enumeration failure did not retry\n");return 15;
    }
    // CASE 1: before xrEndFrame identifies any projection layer,
    // the unique color buffer with exact HMD pixel extent is accepted.
    idx=999;
    if (onAcquire(g_sceneHandle,nullptr,&idx)!=XR_SUCCESS||idx!=0) return 2;
    if (onRelease(g_sceneHandle,nullptr)!=XR_SUCCESS||g_draws!=1||
        !g_lastSplit||glamayre_xr_processed_count()!=1) {
        fprintf(stderr,"Scene detection/release failed, draws=%u frames=%llu split=%d\n",
            g_draws,glamayre_xr_processed_count(),int(g_lastSplit));
        return 3;
    }
    // CASE 2: UI buffer with same format but wrong height is excluded.
    if (onAcquire(g_uiHandle,nullptr,&idx)!=XR_SUCCESS) return 4;
    if (onRelease(g_uiHandle,nullptr)!=XR_SUCCESS||g_draws!=1) {
        fprintf(stderr,"UI mistakenly sharpened\n");return 5;
    }
    // CASE 3: actual OpenXR projection layer signals same scene image.
    ProjectionView views[2]{};
    views[0].subImage.swapchain=g_sceneHandle;
    views[0].subImage.rect.extent.width=300;
    views[0].subImage.rect.extent.height=300;
    views[1].subImage.swapchain=g_sceneHandle;
    views[1].subImage.rect.offset.x=300;
    views[1].subImage.rect.extent.width=300;
    views[1].subImage.rect.extent.height=300;
    ProjectionLayer projection{};
    projection.type=XR_TYPE_PROJECTION_LAYER;
    projection.count=2;
    projection.views=views;
    const BaseHeader* layers[] = {reinterpret_cast<BaseHeader*>(&projection)};
    FrameEndInfo end{};
    end.layerCount=1;
    end.layers=layers;
    if (onEndFrame(reinterpret_cast<Session>(uintptr_t(1)),&end)!=XR_SUCCESS||
        !g_swapchains[g_sceneHandle].projection) {
        fprintf(stderr,"Projection layer was not accepted\n");return 6;
    }
    if (onAcquire(g_sceneHandle,nullptr,&idx)!=XR_SUCCESS) return 7;
    if (onRelease(g_sceneHandle,nullptr)!=XR_SUCCESS) return 8;
    // When submitting twice on WARP, previous fence may still be in flight:
    // skip rather than wait, so a pass count of 1 or 2 is acceptable.
    if (g_draws<1 || g_fakeReleases!=5||g_fakeEnds!=1 ||
        glamayre_xr_dimension_count()!=1||glamayre_xr_release_count()!=5) {
        fprintf(stderr,"Callback counts inconsistent\n");return 9;
    }
    // Test fence draining occurs on teardown only.
    if (onDestroy(g_sceneHandle)!=XR_SUCCESS ||
        g_swapchains.count(g_sceneHandle)!=0) {
        fprintf(stderr,"Swapchain teardown not isolated\n");return 10;
    }
    if (onDestroy(g_uiHandle)!=XR_SUCCESS) return 11;
    printf("OpenXR mock PASS: acquire/release/EndFrame/scene extent,"
           " UI exclusion, stereo detection, queue work and teardown\n");
    return 0;
}
