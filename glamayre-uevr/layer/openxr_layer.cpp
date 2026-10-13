// Glamarye OpenXR implicit API layer. Copyright 2026 contributors.
// Uses Khronos OpenXR loader negotiation rather than detouring an arbitrary
// openxr_loader.dll. UEVR/Joey may statically link their loader; this layer is
// loaded by THAT loader through the standard API-layer mechanism.
// OpenXR-layer code is separate from the sharpening/UEVR settings DLL.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define XR_USE_PLATFORM_WIN32
#define XR_USE_GRAPHICS_API_D3D12
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <loader_interfaces.h>
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstring>
#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>
#include <vector>

using Microsoft::WRL::ComPtr;
namespace {
constexpr char kName[] = "XR_APILAYER_Glamarye_sharpen";
struct Dispatch {
    PFN_xrGetInstanceProcAddr gipa{};
    PFN_xrDestroyInstance destroyInstance{};
    PFN_xrCreateSession createSession{};
    PFN_xrDestroySession destroySession{};
    PFN_xrCreateSwapchain createSwapchain{};
    PFN_xrDestroySwapchain destroySwapchain{};
    PFN_xrAcquireSwapchainImage acquire{};
    PFN_xrReleaseSwapchainImage release{};
    PFN_xrEndFrame endFrame{};
    PFN_xrEnumerateSwapchainImages enumerate{};
};
struct SessionData {
    XrInstance instance{XR_NULL_HANDLE};
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
};
struct Image {
    ComPtr<ID3D12Resource> resource;
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> list;
    ComPtr<ID3D12DescriptorHeap> rtvs;
    ComPtr<ID3D12Fence> fence;
    UINT64 lastSignal{};
};
struct Swap {
    XrSession session{XR_NULL_HANDLE};
    bool projection{};
    bool doubleWide{};
    bool rejected{};
    std::deque<uint32_t> acquisitions;
    std::vector<std::unique_ptr<Image>> images;
};
std::mutex mutex;
std::unordered_map<XrInstance,Dispatch> instances;
std::unordered_map<XrSession,SessionData> sessions;
std::unordered_map<XrSwapchain,Swap> swaps;
std::atomic<uint64_t> acquires{}, releases{}, endframes{}, projections{}, processed{}, rejects{}, errors{};
std::atomic<bool> layerReady{false};

using Record = bool (__cdecl*)(void*,void*,void*,bool);
using Enabled = bool (__cdecl*)();
bool process(Swap& swap,uint32_t index) {
    if (!swap.projection || swap.rejected) return false;
    auto sit=sessions.find(swap.session);
    if(sit==sessions.end()||!sit->second.device||!sit->second.queue) return false;
    HMODULE plugin=GetModuleHandleW(L"GlamaryeSharpenUEVR.dll");
    if(!plugin) return false; // No native UEVR controls DLL yet: do not alter output.
    auto enabled=reinterpret_cast<Enabled>(GetProcAddress(plugin,"glamayre_sharpen_processing_enabled"));
    auto record=reinterpret_cast<Record>(GetProcAddress(plugin,"glamayre_sharpen_gpu_record"));
    if(!enabled||!record||!enabled()) return false;

    auto& ses=sit->second;
    if(swap.images.empty()) return false;
    if(index>=swap.images.size()) return false;
    Image& im=*swap.images[index];
    if(im.fence->GetCompletedValue()<im.lastSignal) return false;
    if(FAILED(im.allocator->Reset())||
       FAILED(im.list->Reset(im.allocator.Get(),nullptr))) {++errors;return false;}
    auto rtv=im.rtvs->GetCPUDescriptorHandleForHeapStart();
    if(!record(im.list.Get(),im.resource.Get(),&rtv,swap.doubleWide)) {
        im.list->Close();return false;
    }
    if(FAILED(im.list->Close())) {++errors;return false;}
    ID3D12CommandList* commands[]={im.list.Get()};
    ses.queue->ExecuteCommandLists(1,commands);
    UINT64 next=im.lastSignal+1;
    if(FAILED(ses.queue->Signal(im.fence.Get(),next))) {++errors;return false;}
    im.lastSignal=next; ++processed;
    return true;
}
bool ensureImages(XrSwapchain sc,Swap& s) {
    if(s.rejected) return false;
    if(!s.images.empty()) return true;
    if(!s.projection) return false;
    auto ses=sessions.find(s.session);
    if(ses==sessions.end()||!ses->second.device) return false;
    auto di=instances.find(ses->second.instance);
    if(di==instances.end()||!di->second.enumerate) return false;
    uint32_t count=0;
    auto e=di->second.enumerate(sc,0,&count,nullptr);
    if(XR_FAILED(e)||count==0) return false;
    if(count>16) {s.rejected=true;return false;}
    std::vector<XrSwapchainImageD3D12KHR> xrImages(count);
    for(auto& x:xrImages) {x.type=XR_TYPE_SWAPCHAIN_IMAGE_D3D12_KHR;x.next=nullptr;x.texture=nullptr;}
    e=di->second.enumerate(sc,count,&count,reinterpret_cast<XrSwapchainImageBaseHeader*>(xrImages.data()));
    if(XR_FAILED(e)) return false;
    auto* dev=ses->second.device.Get();
    std::vector<std::unique_ptr<Image>> fresh;
    for(auto& x:xrImages) {
        if(!x.texture) {s.rejected=true;return false;}
        auto d=x.texture->GetDesc();
        if(d.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D||d.SampleDesc.Count!=1||
           d.DepthOrArraySize!=1||d.MipLevels!=1||
           !(d.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)||
           (d.Format!=DXGI_FORMAT_R8G8B8A8_UNORM_SRGB &&
            d.Format!=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB &&
            d.Format!=DXGI_FORMAT_R8G8B8A8_UNORM &&
            d.Format!=DXGI_FORMAT_B8G8R8A8_UNORM &&
            d.Format!=DXGI_FORMAT_R8G8B8A8_TYPELESS &&
            d.Format!=DXGI_FORMAT_B8G8R8A8_TYPELESS &&
            d.Format!=DXGI_FORMAT_R16G16B16A16_FLOAT)) {
            s.rejected=true;++rejects;return false;
        }
        auto im=std::make_unique<Image>();im->resource=x.texture;
        D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.NumDescriptors=1;
        if(FAILED(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&im->allocator)))||
           FAILED(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,im->allocator.Get(),
                                        nullptr,IID_PPV_ARGS(&im->list)))||
           FAILED(im->list->Close())||
           FAILED(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&im->rtvs)))||
           FAILED(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&im->fence)))) {
            ++errors;return false;
        }
        D3D12_RENDER_TARGET_VIEW_DESC rtv{};
        rtv.ViewDimension=D3D12_RTV_DIMENSION_TEXTURE2D;
        rtv.Format=d.Format==DXGI_FORMAT_R8G8B8A8_TYPELESS?DXGI_FORMAT_R8G8B8A8_UNORM_SRGB:
                   d.Format==DXGI_FORMAT_B8G8R8A8_TYPELESS?DXGI_FORMAT_B8G8R8A8_UNORM_SRGB:d.Format;
        dev->CreateRenderTargetView(x.texture,&rtv,im->rtvs->GetCPUDescriptorHandleForHeapStart());
        fresh.push_back(std::move(im));
    }
    s.images=std::move(fresh);
    return true;
}
void drain(Swap& s) {
    // Only on teardown; no fence waits on ordinary frames.
    for(auto& i:s.images) {
        if(!i||!i->lastSignal||i->fence->GetCompletedValue()>=i->lastSignal) continue;
        HANDLE event=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if(event) {
            if(SUCCEEDED(i->fence->SetEventOnCompletion(i->lastSignal,event)))
                WaitForSingleObject(event,5000);
            CloseHandle(event);
        }
    }
    s.images.clear();s.acquisitions.clear();
}
Dispatch* find(XrInstance i){auto it=instances.find(i);return it==instances.end()?nullptr:&it->second;}
Dispatch* fromSession(XrSession s) {
    auto it=sessions.find(s);
    return it==sessions.end()?nullptr:find(it->second.instance);
}
XrResult XRAPI_CALL onCreateSession(XrInstance inst,const XrSessionCreateInfo* info,XrSession* out) {
    PFN_xrCreateSession next{};
    {std::lock_guard lock(mutex);auto d=find(inst);if(!d)return XR_ERROR_HANDLE_INVALID;next=d->createSession;}
    if(!next)return XR_ERROR_FUNCTION_UNSUPPORTED;
    auto result=next(inst,info,out);
    if(XR_FAILED(result)||!out||*out==XR_NULL_HANDLE)return result;
    SessionData sd{};sd.instance=inst;
    if(info) {
        for(auto* p=reinterpret_cast<const XrBaseInStructure*>(info->next);p;p=p->next) {
            if(p->type==XR_TYPE_GRAPHICS_BINDING_D3D12_KHR) {
                auto* b=reinterpret_cast<const XrGraphicsBindingD3D12KHR*>(p);
                sd.device=b->device;sd.queue=b->queue;break;
            }
        }
    }
    {std::lock_guard lock(mutex);sessions[*out]=std::move(sd);}
    return result;
}
XrResult XRAPI_CALL onDestroySession(XrSession session) {
    PFN_xrDestroySession next{};
    {std::lock_guard lock(mutex);auto d=fromSession(session);if(!d)return XR_ERROR_HANDLE_INVALID;next=d->destroySession;}
    auto r=next?next(session):XR_ERROR_FUNCTION_UNSUPPORTED;
    if(XR_SUCCEEDED(r)) {
        std::lock_guard lock(mutex);
        for(auto it=swaps.begin();it!=swaps.end();) {
            if(it->second.session==session) {drain(it->second);it=swaps.erase(it);}
            else ++it;
        }
        sessions.erase(session);
    }
    return r;
}
XrResult XRAPI_CALL onCreateSwapchain(XrSession session,const XrSwapchainCreateInfo* info,XrSwapchain* out) {
    PFN_xrCreateSwapchain next{};
    {std::lock_guard lock(mutex);auto d=fromSession(session);if(!d)return XR_ERROR_HANDLE_INVALID;next=d->createSwapchain;}
    if(!next)return XR_ERROR_FUNCTION_UNSUPPORTED;
    auto r=next(session,info,out);
    if(XR_SUCCEEDED(r)&&out&&*out!=XR_NULL_HANDLE) {
        std::lock_guard lock(mutex);auto& s=swaps[*out];s.session=session;
    }
    return r;
}
XrResult XRAPI_CALL onDestroySwapchain(XrSwapchain sc) {
    PFN_xrDestroySwapchain next{};
    {std::lock_guard lock(mutex);
       auto it=swaps.find(sc);if(it==swaps.end())return XR_ERROR_HANDLE_INVALID;
       auto d=fromSession(it->second.session);if(!d)return XR_ERROR_HANDLE_INVALID;
       next=d->destroySwapchain;drain(it->second);
    }
    auto r=next?next(sc):XR_ERROR_FUNCTION_UNSUPPORTED;
    if(XR_SUCCEEDED(r)) {std::lock_guard lock(mutex);swaps.erase(sc);}
    return r;
}
XrResult XRAPI_CALL onAcquire(XrSwapchain sc,const XrSwapchainImageAcquireInfo* info,uint32_t* index) {
    PFN_xrAcquireSwapchainImage next{};
    {std::lock_guard lock(mutex);auto it=swaps.find(sc);
     if(it==swaps.end())return XR_ERROR_HANDLE_INVALID;
     auto d=fromSession(it->second.session);if(!d)return XR_ERROR_HANDLE_INVALID;
     next=d->acquire;
    }
    auto r=next?next(sc,info,index):XR_ERROR_FUNCTION_UNSUPPORTED;
    if(XR_SUCCEEDED(r)&&index) {
        ++acquires;std::lock_guard lock(mutex);
        auto it=swaps.find(sc);
        if(it!=swaps.end()) {
            if(it->second.acquisitions.size()<16)it->second.acquisitions.push_back(*index);
            else {it->second.acquisitions.clear();++errors;}
        }
    }
    return r;
}
XrResult XRAPI_CALL onRelease(XrSwapchain sc,const XrSwapchainImageReleaseInfo* info) {
    PFN_xrReleaseSwapchainImage next{};
    {std::lock_guard lock(mutex);
        auto it=swaps.find(sc);
        if(it==swaps.end())return XR_ERROR_HANDLE_INVALID;
        auto d=fromSession(it->second.session);if(!d)return XR_ERROR_HANDLE_INVALID;
        next=d->release;
        if(!it->second.acquisitions.empty()) {
            const uint32_t idx=it->second.acquisitions.front();
            it->second.acquisitions.pop_front();
            if(ensureImages(sc,it->second))process(it->second,idx);
        }
    }
    ++releases;
    return next?next(sc,info):XR_ERROR_FUNCTION_UNSUPPORTED;
}
XrResult XRAPI_CALL onEndFrame(XrSession session,const XrFrameEndInfo* info) {
    PFN_xrEndFrame next{};
    {std::lock_guard lock(mutex);
        auto d=fromSession(session);if(!d)return XR_ERROR_HANDLE_INVALID;
        next=d->endFrame;
        if(info && info->layers && info->layerCount<=16) {
            for(uint32_t i=0;i<info->layerCount;++i) {
                auto layer=info->layers[i];
                if(!layer ||layer->type!=XR_TYPE_COMPOSITION_LAYER_PROJECTION)continue;
                auto* p=reinterpret_cast<const XrCompositionLayerProjection*>(layer);
                if(!p->views||p->viewCount<1||p->viewCount>4)continue;
                for(uint32_t j=0;j<p->viewCount;++j) {
                    auto sc=p->views[j].subImage.swapchain;
                    auto it=swaps.find(sc);
                    if(it==swaps.end()||it->second.session!=session)continue;
                    if(!it->second.projection)++projections;
                    it->second.projection=true;
                    if(p->viewCount==2 &&
                       p->views[0].subImage.swapchain==p->views[1].subImage.swapchain) {
                        auto a=p->views[0].subImage.imageRect;
                        auto b=p->views[1].subImage.imageRect;
                        if(a.offset.x==0 && b.offset.x==a.extent.width &&
                           a.extent.width==b.extent.width &&
                           a.offset.y==b.offset.y)it->second.doubleWide=true;
                    }
                }
            }
        }
    }
    ++endframes;
    return next?next(session,info):XR_ERROR_FUNCTION_UNSUPPORTED;
}
XrResult XRAPI_CALL onDestroyInstance(XrInstance inst) {
    PFN_xrDestroyInstance next{};
    {std::lock_guard lock(mutex);auto d=find(inst);if(!d)return XR_ERROR_HANDLE_INVALID;next=d->destroyInstance;}
    auto r=next?next(inst):XR_ERROR_FUNCTION_UNSUPPORTED;
    if(XR_SUCCEEDED(r)) {
        std::lock_guard lock(mutex);
        for(auto it=sessions.begin();it!=sessions.end();) {
            if(it->second.instance==inst)it=sessions.erase(it);else ++it;
        }
        instances.erase(inst);
    }
    return r;
}
template<class T> void lookup(PFN_xrGetInstanceProcAddr gipa,XrInstance inst,
                             const char* name,T& output) {
    PFN_xrVoidFunction ptr=nullptr;
    if(XR_SUCCEEDED(gipa(inst,name,&ptr)))output=reinterpret_cast<T>(ptr);
}
} // namespace

extern "C" __declspec(dllexport) void __cdecl glamayre_layer_get_status(uint64_t* out,uint32_t count) {
    if(!out||count<8)return;
    out[0]=layerReady?1:0;out[1]=acquires;out[2]=releases;out[3]=endframes;
    out[4]=projections;out[5]=processed;out[6]=rejects;out[7]=errors;
}
extern "C" __declspec(dllexport) XrResult XRAPI_CALL LayerGetInstanceProcAddr(
    XrInstance instance,const char* name,PFN_xrVoidFunction* fn) {
    if(!name||!fn)return XR_ERROR_VALIDATION_FAILURE;
    *fn=nullptr;
    if(std::strcmp(name,"xrGetInstanceProcAddr")==0) {
        *fn=reinterpret_cast<PFN_xrVoidFunction>(&LayerGetInstanceProcAddr);return XR_SUCCESS;
    }
    if(instance==XR_NULL_HANDLE)return XR_ERROR_FUNCTION_UNSUPPORTED;
    PFN_xrGetInstanceProcAddr next{};
    {std::lock_guard lock(mutex);
     auto d=find(instance);if(!d)return XR_ERROR_HANDLE_INVALID;next=d->gipa;}
    if(!next)return XR_ERROR_FUNCTION_UNSUPPORTED;
    // Do not expose unsupported downstream extension/core calls.
    auto result=next(instance,name,fn);
    if(XR_FAILED(result)||!*fn)return result;
    // Only install wrappers for functions confirmed by the downstream layer.
    if(std::strcmp(name,"xrCreateSession")==0)*fn=(PFN_xrVoidFunction)&onCreateSession;
    else if(std::strcmp(name,"xrDestroySession")==0)*fn=(PFN_xrVoidFunction)&onDestroySession;
    else if(std::strcmp(name,"xrCreateSwapchain")==0)*fn=(PFN_xrVoidFunction)&onCreateSwapchain;
    else if(std::strcmp(name,"xrDestroySwapchain")==0)*fn=(PFN_xrVoidFunction)&onDestroySwapchain;
    else if(std::strcmp(name,"xrAcquireSwapchainImage")==0)*fn=(PFN_xrVoidFunction)&onAcquire;
    else if(std::strcmp(name,"xrReleaseSwapchainImage")==0)*fn=(PFN_xrVoidFunction)&onRelease;
    else if(std::strcmp(name,"xrEndFrame")==0)*fn=(PFN_xrVoidFunction)&onEndFrame;
    else if(std::strcmp(name,"xrDestroyInstance")==0)*fn=(PFN_xrVoidFunction)&onDestroyInstance;
    return result;
}
extern "C" __declspec(dllexport) XrResult XRAPI_CALL LayerCreateInstance(
    const XrInstanceCreateInfo* create,const XrApiLayerCreateInfo* chain,XrInstance* instance) {
    if(!create||!chain||!chain->nextInfo||!instance||
        chain->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO||
        chain->nextInfo->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO||
        std::strcmp(chain->nextInfo->layerName,kName)!=0||
        !chain->nextInfo->nextCreateApiLayerInstance||!chain->nextInfo->nextGetInstanceProcAddr)
        return XR_ERROR_INITIALIZATION_FAILED;
    auto next=chain->nextInfo->nextCreateApiLayerInstance;
    auto gipa=chain->nextInfo->nextGetInstanceProcAddr;
    XrApiLayerCreateInfo forwarded=*chain;
    forwarded.nextInfo=chain->nextInfo->next;
    auto result=next(create,&forwarded,instance);
    if(XR_FAILED(result)||*instance==XR_NULL_HANDLE)return result;
    Dispatch d{};d.gipa=gipa;
    lookup(gipa,*instance,"xrDestroyInstance",d.destroyInstance);
    lookup(gipa,*instance,"xrCreateSession",d.createSession);
    lookup(gipa,*instance,"xrDestroySession",d.destroySession);
    lookup(gipa,*instance,"xrCreateSwapchain",d.createSwapchain);
    lookup(gipa,*instance,"xrDestroySwapchain",d.destroySwapchain);
    lookup(gipa,*instance,"xrAcquireSwapchainImage",d.acquire);
    lookup(gipa,*instance,"xrReleaseSwapchainImage",d.release);
    lookup(gipa,*instance,"xrEndFrame",d.endFrame);
    lookup(gipa,*instance,"xrEnumerateSwapchainImages",d.enumerate);
    {
        std::lock_guard lock(mutex);
        instances[*instance]=d;
        layerReady=true;
    }
    return result;
}
extern "C" __declspec(dllexport) XrResult XRAPI_CALL xrNegotiateLoaderApiLayerInterface(
    const XrNegotiateLoaderInfo* li,const char* name,XrNegotiateApiLayerRequest* req) {
    if(!li||!req||!name||std::strcmp(name,kName)!=0||
       li->structType!=XR_LOADER_INTERFACE_STRUCT_LOADER_INFO||
       li->structSize<sizeof(XrNegotiateLoaderInfo)||
       req->structSize<sizeof(XrNegotiateApiLayerRequest)||
       req->structType!=XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST||
       li->minInterfaceVersion>XR_CURRENT_LOADER_API_LAYER_VERSION||
       li->maxInterfaceVersion<XR_CURRENT_LOADER_API_LAYER_VERSION)
        return XR_ERROR_INITIALIZATION_FAILED;
    req->layerInterfaceVersion=XR_CURRENT_LOADER_API_LAYER_VERSION;
    req->layerApiVersion=XR_CURRENT_API_VERSION;
    req->createApiLayerInstance=&LayerCreateInstance;
    req->getInstanceProcAddr=&LayerGetInstanceProcAddr;
    return XR_SUCCESS;
}
BOOL WINAPI DllMain(HINSTANCE h,DWORD reason,void*) {
    if(reason==DLL_PROCESS_ATTACH)DisableThreadLibraryCalls(h);
    return TRUE;
}
