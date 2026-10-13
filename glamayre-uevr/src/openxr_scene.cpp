// OpenXR Direct3D12 scene path for Glamarye Sharpen UEVR.
// Hooks loader-level xrAcquireSwapchainImage, xrReleaseSwapchainImage, xrEndFrame,
// xrDestroySwapchain using UEVR's public inline-hook facility.
// Validates projection-layer swapchain identity from a PREVIOUS xrEndFrame:
// UI, depth, spectator and unclassified textures are NEVER sharpened.
//
// Design: UEVR's D3D12Component::OpenXR::copy() records a copy to the OpenXR
// color image, executes it on the UEVR DirectX 12 queue, THEN calls
// xrReleaseSwapchainImage. On the same queue this code enqueues its sharpening
// draw before passing xrReleaseSwapchainImage to the real loader/runtime.
// No per-frame CPU waits or GPU readbacks. If we can't prove context, skip.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <uevr/API.h>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <mutex>
#include <memory>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <algorithm>

using Microsoft::WRL::ComPtr;
extern "C" bool glamayre_sharpen_gpu_record(void* list, void* resource, void* rtv, bool autoSplit);
extern "C" bool glamayre_sharpen_processing_enabled();

namespace {
// OpenXR 1.x ABI types/field layouts used below, based on Khronos OpenXR headers.
// https://github.com/KhronosGroup/OpenXR-SDK/tree/main/include/openxr
using Swapchain = void*;
using Session = void*;
using Result = int32_t;
constexpr int32_t XR_SUCCESS = 0, XR_TYPE_IMAGE_D3D12 = 1000028001;
constexpr int32_t XR_TYPE_PROJECTION_LAYER = 35;
struct BaseHeader { int32_t type; const void* next; };
struct Rect { struct { int32_t x,y; } offset; struct { int32_t width,height; } extent; };
struct SubImage { Swapchain swapchain; Rect rect; uint32_t arrayIndex; };
struct Pose { float orientation[4]; float position[3]; };
struct Fov { float angle[4]; };
struct ProjectionView { int32_t type; const void* next; Pose pose; Fov fov; SubImage subImage; };
struct ProjectionLayer { int32_t type; const void* next; uint64_t flags; void* space; uint32_t count; const ProjectionView* views; };
struct FrameEndInfo {
    int32_t type; const void* next; int64_t displayTime;
    int32_t environmentBlendMode; uint32_t layerCount; const BaseHeader* const* layers;
};
struct ImageD3D12 { int32_t type; void* next; ID3D12Resource* texture; };
using AcquireFn = Result(WINAPI*)(Swapchain, const void*, uint32_t*);
using ReleaseFn = Result(WINAPI*)(Swapchain, const void*);
using EndFrameFn = Result(WINAPI*)(Session, const FrameEndInfo*);
using DestroyFn = Result(WINAPI*)(Swapchain);
using EnumerateFn = Result(WINAPI*)(Swapchain,uint32_t,uint32_t*,BaseHeader*);

static_assert(sizeof(ImageD3D12) == 24 && sizeof(SubImage) == 32);
static_assert(sizeof(ProjectionView) == 96 && sizeof(FrameEndInfo) == 40);

std::mutex g_lock;
const UEVR_PluginInitializeParam* g_api = nullptr;
AcquireFn g_acquire = nullptr;
ReleaseFn g_release = nullptr;
EndFrameFn g_endframe = nullptr;
DestroyFn g_destroy = nullptr;
EnumerateFn g_enumerate = nullptr;
int g_hookAcquire = -1, g_hookRelease = -1, g_hookEnd = -1, g_hookDestroy = -1;
std::atomic<bool> g_hooked{false};
std::atomic<unsigned long long> g_frames{0};

struct ImageContext {
    ComPtr<ID3D12Resource> texture;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commandList;
    ComPtr<ID3D12DescriptorHeap> rtvHeap;
    ComPtr<ID3D12Fence> fence;
    uint64_t lastSignalled = 0;
};
struct SwapchainState {
    std::deque<uint32_t> acquired;
    bool projection = false;
    bool splitStereo = false;
    bool initialized = false;
    std::vector<std::unique_ptr<ImageContext>> images;
};
std::unordered_map<Swapchain,SwapchainState> g_swapchains;

void log(const char* message) {
    if (g_api && g_api->functions && g_api->functions->log_info)
        g_api->functions->log_info("Glamarye OpenXR: %s", message);
}
bool makeContext(ImageContext& ctx, ID3D12Resource* tex, ID3D12Device* device) {
    if (!tex) return false;
    const auto d = tex->GetDesc();
    // UEVR's D3D12 OpenXR color images are BGRA8 sRGB, arraySize==1.
    if (d.Dimension != D3D12_RESOURCE_DIMENSION_TEXTURE2D ||
        d.SampleDesc.Count != 1 || d.DepthOrArraySize != 1 ||
        (d.Format != DXGI_FORMAT_B8G8R8A8_UNORM_SRGB &&
         d.Format != DXGI_FORMAT_R8G8B8A8_UNORM_SRGB &&
         d.Format != DXGI_FORMAT_B8G8R8A8_UNORM &&
         d.Format != DXGI_FORMAT_R8G8B8A8_UNORM &&
         d.Format != DXGI_FORMAT_R16G16B16A16_FLOAT)) return false;
    if (!(d.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)) return false;
    ctx.texture = tex;
    if (FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,
            IID_PPV_ARGS(&ctx.allocator)))) return false;
    if (FAILED(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,
            ctx.allocator.Get(),nullptr,IID_PPV_ARGS(&ctx.commandList)))) return false;
    if (FAILED(ctx.commandList->Close())) return false;
    D3D12_DESCRIPTOR_HEAP_DESC heap{};
    heap.Type = D3D12_DESCRIPTOR_HEAP_TYPE_RTV;
    heap.NumDescriptors = 1;
    if (FAILED(device->CreateDescriptorHeap(&heap,IID_PPV_ARGS(&ctx.rtvHeap)))) return false;
    D3D12_RENDER_TARGET_VIEW_DESC rtv{};
    rtv.Format = d.Format;
    rtv.ViewDimension = D3D12_RTV_DIMENSION_TEXTURE2D;
    rtv.Texture2D.MipSlice = 0;
    device->CreateRenderTargetView(tex, &rtv, ctx.rtvHeap->GetCPUDescriptorHandleForHeapStart());
    if (FAILED(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&ctx.fence))))
        return false;
    return true;
}

bool ensureImages(Swapchain swapchain, SwapchainState& state) {
    if (state.initialized) return !state.images.empty();
    // Fail closed; an incomplete mapping must not be retried every frame.
    state.initialized = true;
    if (!g_enumerate || !g_api || !g_api->renderer ||
        g_api->renderer->renderer_type != UEVR_RENDERER_D3D12) return false;
    auto* dev = static_cast<ID3D12Device*>(g_api->renderer->device);
    if (!dev) return false;
    uint32_t count = 0;
    if (g_enumerate(swapchain,0,&count,nullptr) != XR_SUCCESS || count<1 || count>8) return false;
    std::vector<ImageD3D12> images(count);
    for(auto& image : images) image.type = XR_TYPE_IMAGE_D3D12;
    if (g_enumerate(swapchain,count,&count,
        reinterpret_cast<BaseHeader*>(images.data())) != XR_SUCCESS) return false;
    for (auto& image : images) {
        auto ctx = std::make_unique<ImageContext>();
        if (!makeContext(*ctx,image.texture,dev)) {
            state.images.clear();
            return false;
        }
        state.images.push_back(std::move(ctx));
    }
    return true;
}

Result WINAPI onAcquire(Swapchain sc, const void* info, uint32_t* index) {
    if (!g_acquire) return -2;
    auto result = g_acquire(sc,info,index);
    if (result == XR_SUCCESS && index) {
        std::lock_guard guard(g_lock);
        auto& q = g_swapchains[sc].acquired;
        if (q.size() < 16) q.push_back(*index);
        else q.clear(); // never consume an uncertain queue
    }
    return result;
}
Result WINAPI onEndFrame(Session session, const FrameEndInfo* info) {
    // Only projection layers carry scene color. In UEVR, UI overlays are quads.
    // A swapchain becomes eligible from the NEXT frame, once identity is known.
    if (info && info->layers && info->layerCount < 32) {
        std::lock_guard guard(g_lock);
        for (uint32_t i=0;i<info->layerCount;++i) {
            auto* base = info->layers[i];
            if (!base || base->type != XR_TYPE_PROJECTION_LAYER) continue;
            auto* p = reinterpret_cast<const ProjectionLayer*>(base);
            if (!p->views || p->count != 2) continue;
            const auto left = p->views[0].subImage;
            const auto right = p->views[1].subImage;
            if (!left.swapchain || !right.swapchain) continue;
            auto& l = g_swapchains[left.swapchain];
            auto& r = g_swapchains[right.swapchain];
            l.projection = true; r.projection = true;
            // Eye boundaries are derived from OpenXR projection sub-image
            // rectangles, not simply guessed from screen dimensions.
            bool doubled = left.swapchain == right.swapchain
                && left.rect.offset.x == 0 && right.rect.offset.x == left.rect.extent.width
                && left.rect.extent.width == right.rect.extent.width
                && left.rect.offset.y == right.rect.offset.y;
            if (doubled) l.splitStereo = true;
        }
    }
    return g_endframe ? g_endframe(session,info) : -2;
}

void waitAndClear(SwapchainState& state) {
    // During swapchain destruction only; never blocks a normal frame.
    for (auto& p : state.images) {
        if (!p || !p->fence || !p->lastSignalled) continue;
        if (p->fence->GetCompletedValue() >= p->lastSignalled) continue;
        HANDLE ev = CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if (ev) {
            if (SUCCEEDED(p->fence->SetEventOnCompletion(p->lastSignalled,ev)))
                WaitForSingleObject(ev,5000);
            CloseHandle(ev);
        }
    }
    state.images.clear();
    state.acquired.clear();
}

Result WINAPI onDestroy(Swapchain sc) {
    {
        std::lock_guard guard(g_lock);
        auto it = g_swapchains.find(sc);
        if (it != g_swapchains.end()) {
            waitAndClear(it->second);
            g_swapchains.erase(it);
        }
    }
    return g_destroy ? g_destroy(sc) : -2;
}

Result WINAPI onRelease(Swapchain sc, const void* info) {
    // Do not ever change OpenXR's return codes or skip its real release.
    // The lock also serializes setup, release and swapchain reset on the CPU.
    {
        std::lock_guard guard(g_lock);
        auto it = g_swapchains.find(sc);
        if (it != g_swapchains.end()) {
            auto& state = it->second;
            if (!state.acquired.empty()) {
                const uint32_t index = state.acquired.front();
                state.acquired.pop_front();
                if (state.projection && glamayre_sharpen_processing_enabled() &&
                    g_api && g_api->renderer && g_api->renderer->command_queue &&
                    ensureImages(sc,state) && index < state.images.size()) {
                    auto& ctx = *state.images[index];
                    auto* queue = static_cast<ID3D12CommandQueue*>(g_api->renderer->command_queue);
                    // Avoid blocking the render thread if the same swapchain image
                    // somehow arrives before the GPU finished the previous use.
                    if (ctx.fence && ctx.lastSignalled <= ctx.fence->GetCompletedValue() &&
                        SUCCEEDED(ctx.allocator->Reset()) &&
                        SUCCEEDED(ctx.commandList->Reset(ctx.allocator.Get(),nullptr))) {
                        auto handle = ctx.rtvHeap->GetCPUDescriptorHandleForHeapStart();
                        if (glamayre_sharpen_gpu_record(ctx.commandList.Get(),
                            ctx.texture.Get(),&handle,state.splitStereo)) {
                            if (SUCCEEDED(ctx.commandList->Close())) {
                                ID3D12CommandList* lists[] = {ctx.commandList.Get()};
                                queue->ExecuteCommandLists(1,lists);
                                uint64_t next = ctx.lastSignalled+1;
                                if (SUCCEEDED(queue->Signal(ctx.fence.Get(),next))) {
                                    ctx.lastSignalled = next;
                                    g_frames.fetch_add(1,std::memory_order_relaxed);
                                }
                            }
                        } else {
                            // On error the command list won't be submitted.
                            ctx.commandList->Close();
                        }
                    }
                }
            }
        }
    }
    return g_release ? g_release(sc,info) : -2;
}
} // namespace

extern "C" unsigned long long glamayre_xr_processed_count() {
    return g_frames.load(std::memory_order_relaxed);
}
extern "C" bool glamayre_xr_hooks_ready() {
    return g_hooked.load(std::memory_order_acquire);
}
extern "C" void glamayre_xr_reset_buffers() {
    std::lock_guard guard(g_lock);
    for (auto& [_,sc] : g_swapchains) {
        waitAndClear(sc);
        sc.initialized=false;
        sc.projection=false;
        sc.splitStereo=false;
    }
    g_swapchains.clear();
}
extern "C" void glamayre_xr_tick(const UEVR_PluginInitializeParam* api) {
    if (g_hooked.load(std::memory_order_acquire) || !api ||
        !api->renderer || api->renderer->renderer_type != UEVR_RENDERER_D3D12 ||
        !api->vr || !api->vr->is_openxr || !api->vr->is_openxr() ||
        !api->functions || !api->functions->register_inline_hook) return;
    std::lock_guard guard(g_lock);
    if (g_hooked.load()) return;
    g_api = api;
    // UEVR calls the OpenXR loader exports directly in its D3D12Component.
    // Hook exactly those exported functions, avoiding runtime private offsets.
    HMODULE loader = GetModuleHandleW(L"openxr_loader.dll");
    if (!loader) return;
    auto acq = GetProcAddress(loader,"xrAcquireSwapchainImage");
    auto rel = GetProcAddress(loader,"xrReleaseSwapchainImage");
    auto end = GetProcAddress(loader,"xrEndFrame");
    auto dst = GetProcAddress(loader,"xrDestroySwapchain");
    auto en = GetProcAddress(loader,"xrEnumerateSwapchainImages");
    if (!acq || !rel || !end || !dst || !en) return;
    g_enumerate = reinterpret_cast<EnumerateFn>(en);
    // Roll back the complete transaction on any failed hook. A partial hook
    // installation could otherwise duplicate callbacks or leave broken state.
    const auto rollback = [&]() {
        auto unreg = api->functions->unregister_inline_hook;
        if (unreg) {
            if (g_hookDestroy >= 0) unreg(g_hookDestroy);
            if (g_hookEnd >= 0) unreg(g_hookEnd);
            if (g_hookRelease >= 0) unreg(g_hookRelease);
            if (g_hookAcquire >= 0) unreg(g_hookAcquire);
        }
        g_hookAcquire = g_hookRelease = g_hookEnd = g_hookDestroy = -1;
        g_acquire = nullptr; g_release = nullptr;
        g_endframe = nullptr; g_destroy = nullptr;
    };
    if (!api->functions->unregister_inline_hook) return;
    g_hookAcquire = api->functions->register_inline_hook(
        reinterpret_cast<void*>(acq),reinterpret_cast<void*>(&onAcquire),
        reinterpret_cast<void**>(&g_acquire));
    if (g_hookAcquire < 0 || !g_acquire) { rollback(); return; }
    g_hookRelease = api->functions->register_inline_hook(
        reinterpret_cast<void*>(rel),reinterpret_cast<void*>(&onRelease),
        reinterpret_cast<void**>(&g_release));
    if (g_hookRelease < 0 || !g_release) { rollback(); return; }
    g_hookEnd = api->functions->register_inline_hook(
        reinterpret_cast<void*>(end),reinterpret_cast<void*>(&onEndFrame),
        reinterpret_cast<void**>(&g_endframe));
    if (g_hookEnd < 0 || !g_endframe) { rollback(); return; }
    g_hookDestroy = api->functions->register_inline_hook(
        reinterpret_cast<void*>(dst),reinterpret_cast<void*>(&onDestroy),
        reinterpret_cast<void**>(&g_destroy));
    if (g_hookDestroy < 0 || !g_destroy) { rollback(); return; }
    g_hooked.store(true,std::memory_order_release);
    log("OpenXR projection hooks active. Awaiting the first xrEndFrame to identify scene.");
}
