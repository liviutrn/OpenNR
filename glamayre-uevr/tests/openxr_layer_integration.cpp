// Fake OpenXR loader+runtime integrated with the production Glamarye DLL.
// Exercises Khronos negotiation, layer dispatch, real WARP D3D12 scene pass,
// projection-vs-UI selection and final pixel readback. No headset required.
#define WIN32_LEAN_AND_MEAN
#define XR_USE_PLATFORM_WIN32
#define XR_USE_GRAPHICS_API_D3D12
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include <loader_interfaces.h>
#include <uevr/API.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
using Microsoft::WRL::ComPtr;
namespace {
XrInstance instance=reinterpret_cast<XrInstance>(uintptr_t(101));
XrSession session=reinterpret_cast<XrSession>(uintptr_t(102));
XrSwapchain projection=reinterpret_cast<XrSwapchain>(uintptr_t(103));
XrSwapchain ui=reinterpret_cast<XrSwapchain>(uintptr_t(104));
ID3D12Resource* scene=nullptr;
ID3D12Resource* uiImage=nullptr;
uint32_t releaseCount=0;
UEVR_OnCustomEventCb custom=nullptr;
void logNoop(const char*, ...) {}
void luaNoop(const char*,const char*) {}
unsigned emptyPersistent(wchar_t*,unsigned){return 0;}
bool customRegister(UEVR_OnCustomEventCb x){custom=x;return true;}
bool presentRegister(UEVR_OnPresentCb){return true;}
bool resetRegister(UEVR_OnDeviceResetCb){return true;}
XrResult XRAPI_CALL createNext(const XrInstanceCreateInfo*,const XrApiLayerCreateInfo* chain,XrInstance* out) {
    if(!chain||chain->nextInfo||!out)return XR_ERROR_INITIALIZATION_FAILED;
    *out=instance;return XR_SUCCESS;
}
XrResult XRAPI_CALL instanceDestroy(XrInstance){return XR_SUCCESS;}
XrResult XRAPI_CALL sessionCreate(XrInstance,const XrSessionCreateInfo*,XrSession* out){*out=session;return XR_SUCCESS;}
XrResult XRAPI_CALL sessionDestroy(XrSession){return XR_SUCCESS;}
XrResult XRAPI_CALL swapCreate(XrSession,const XrSwapchainCreateInfo* info,XrSwapchain* out){
    if(!info||!out)return XR_ERROR_VALIDATION_FAILURE;
    *out=(info->height==64)?projection:ui;return XR_SUCCESS;
}
XrResult XRAPI_CALL swapDestroy(XrSwapchain){return XR_SUCCESS;}
XrResult XRAPI_CALL swapAcquire(XrSwapchain,const XrSwapchainImageAcquireInfo*,uint32_t* out){
    if(!out)return XR_ERROR_VALIDATION_FAILURE;
    *out=0;return XR_SUCCESS;
}
XrResult XRAPI_CALL swapRelease(XrSwapchain,const XrSwapchainImageReleaseInfo*){++releaseCount;return XR_SUCCESS;}
XrResult XRAPI_CALL frameEnd(XrSession,const XrFrameEndInfo*){return XR_SUCCESS;}
XrResult XRAPI_CALL enumerate(XrSwapchain sc,uint32_t cap,uint32_t* count,XrSwapchainImageBaseHeader* out){
    if(!count)return XR_ERROR_VALIDATION_FAILURE;
    *count=1;
    if(!cap)return XR_SUCCESS;
    if(!out||out->type!=XR_TYPE_SWAPCHAIN_IMAGE_D3D12_KHR)return XR_ERROR_VALIDATION_FAILURE;
    auto* image=reinterpret_cast<XrSwapchainImageD3D12KHR*>(out);
    image->texture=sc==projection?scene:uiImage;
    return XR_SUCCESS;
}
XrResult XRAPI_CALL nextGipa(XrInstance,const char* name,PFN_xrVoidFunction* out){
    if(!name||!out)return XR_ERROR_VALIDATION_FAILURE;
    struct Entry{const char* name;PFN_xrVoidFunction fn;};
    const Entry entries[]={
        {"xrDestroyInstance",(PFN_xrVoidFunction)&instanceDestroy},
        {"xrCreateSession",(PFN_xrVoidFunction)&sessionCreate},
        {"xrDestroySession",(PFN_xrVoidFunction)&sessionDestroy},
        {"xrCreateSwapchain",(PFN_xrVoidFunction)&swapCreate},
        {"xrDestroySwapchain",(PFN_xrVoidFunction)&swapDestroy},
        {"xrAcquireSwapchainImage",(PFN_xrVoidFunction)&swapAcquire},
        {"xrReleaseSwapchainImage",(PFN_xrVoidFunction)&swapRelease},
        {"xrEndFrame",(PFN_xrVoidFunction)&frameEnd},
        {"xrEnumerateSwapchainImages",(PFN_xrVoidFunction)&enumerate}
    };
    for(auto& e:entries){if(strcmp(name,e.name)==0){*out=e.fn;return XR_SUCCESS;}}
    *out=nullptr;return XR_ERROR_FUNCTION_UNSUPPORTED;
}
#define TEST(c,desc) do {if(!(c)){fprintf(stderr,"FAILED: %s at line %u\n",desc,__LINE__);return 1;}}while(0)
#define HR(c,desc) do {HRESULT r=(c);if(FAILED(r)){fprintf(stderr,"FAILED: %s HRESULT %08X\n",desc,(unsigned)r);return 2;}}while(0)
template<typename T>T symbol(HMODULE m,const char* n){return reinterpret_cast<T>(GetProcAddress(m,n));}
}
int main(){
    auto layer=LoadLibraryW(L"GlamaryeOpenXRLayer.dll");
    auto plugin=LoadLibraryW(L"GlamaryeSharpenUEVR.dll");
    TEST(layer&&plugin,"Both real DLLs load");
    auto negotiate=symbol<PFN_xrNegotiateLoaderApiLayerInterface>(layer,"xrNegotiateLoaderApiLayerInterface");
    TEST(negotiate,"Layer exports Khronos negotiation");
    XrNegotiateLoaderInfo loader{};
    loader.structType=XR_LOADER_INTERFACE_STRUCT_LOADER_INFO;
    loader.structVersion=XR_LOADER_INFO_STRUCT_VERSION;
    loader.structSize=sizeof(loader);
    loader.minInterfaceVersion=loader.maxInterfaceVersion=XR_CURRENT_LOADER_API_LAYER_VERSION;
    loader.minApiVersion=XR_MAKE_VERSION(1,0,0);
    loader.maxApiVersion=XR_CURRENT_API_VERSION;
    XrNegotiateApiLayerRequest req{};
    req.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_REQUEST;
    req.structVersion=XR_API_LAYER_INFO_STRUCT_VERSION;
    req.structSize=sizeof(req);
    TEST(negotiate(&loader,"XR_APILAYER_Glamarye_sharpen",&req)==XR_SUCCESS,"Khronos negotiation");
    TEST(req.getInstanceProcAddr&&req.createApiLayerInstance,"Negotiated function pointers");
    XrApiLayerNextInfo next{};
    next.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_NEXT_INFO;
    next.structVersion=XR_API_LAYER_NEXT_INFO_STRUCT_VERSION;
    next.structSize=sizeof(next);
    strcpy_s(next.layerName,"XR_APILAYER_Glamarye_sharpen");
    next.nextGetInstanceProcAddr=&nextGipa;
    next.nextCreateApiLayerInstance=&createNext;
    XrApiLayerCreateInfo chain{};
    chain.structType=XR_LOADER_INTERFACE_STRUCT_API_LAYER_CREATE_INFO;
    chain.structVersion=XR_API_LAYER_CREATE_INFO_STRUCT_VERSION;
    chain.structSize=sizeof(chain);chain.nextInfo=&next;
    XrInstance created=XR_NULL_HANDLE;
    XrInstanceCreateInfo ici{XR_TYPE_INSTANCE_CREATE_INFO};
    TEST(req.createApiLayerInstance(&ici,&chain,&created)==XR_SUCCESS&&created==instance,
         "API layer forwards instance creation to downstream runtime");
    auto get=[&](const char* name)->PFN_xrVoidFunction{
        PFN_xrVoidFunction f{};
        return req.getInstanceProcAddr(instance,name,&f)==XR_SUCCESS?f:nullptr;
    };
    auto createSession=(PFN_xrCreateSession)get("xrCreateSession");
    auto createSwap=(PFN_xrCreateSwapchain)get("xrCreateSwapchain");
    auto acquire=(PFN_xrAcquireSwapchainImage)get("xrAcquireSwapchainImage");
    auto release=(PFN_xrReleaseSwapchainImage)get("xrReleaseSwapchainImage");
    auto end=(PFN_xrEndFrame)get("xrEndFrame");
    auto destroySwap=(PFN_xrDestroySwapchain)get("xrDestroySwapchain");
    auto destroySession=(PFN_xrDestroySession)get("xrDestroySession");
    auto destroyInstance=(PFN_xrDestroyInstance)get("xrDestroyInstance");
    TEST(createSession&&createSwap&&acquire&&release&&end&&destroySwap&&destroySession&&destroyInstance,
         "All wrapped OpenXR entry points exposed");
    TEST(release!=&swapRelease,"Release function is genuinely intercepted");
    ComPtr<IDXGIFactory4> factory;
    HR(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"Factory");
    ComPtr<IDXGIAdapter> adapter;
    HR(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)),"WARP adapter");
    ComPtr<ID3D12Device> device;
    HR(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"WARP device");
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    HR(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"GPU queue");
    D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    desc.Width=128;desc.Height=64;desc.DepthOrArraySize=1;desc.MipLevels=1;
    desc.Format=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;desc.SampleDesc.Count=1;
    desc.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    ComPtr<ID3D12Resource> projectionTexture;
    HR(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&projectionTexture)),"Projection color");
    scene=projectionTexture.Get();
    desc.Height=32;
    ComPtr<ID3D12Resource> uiTexture;
    HR(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&uiTexture)),"UI color");
    uiImage=uiTexture.Get();

    UEVR_PluginCallbacks callbacks{};
    callbacks.on_custom_event=customRegister;
    callbacks.on_present=presentRegister;
    callbacks.on_device_reset=resetRegister;
    UEVR_PluginFunctions functions{};
    functions.get_persistent_dir=emptyPersistent;
    functions.log_info=logNoop;
    functions.log_warn=logNoop;
    functions.log_error=logNoop;
    functions.dispatch_lua_event=luaNoop;
    UEVR_PluginVersion pv{UEVR_PLUGIN_VERSION_MAJOR,UEVR_PLUGIN_VERSION_MINOR,UEVR_PLUGIN_VERSION_PATCH};
    UEVR_RendererData rdr{};
    rdr.renderer_type=UEVR_RENDERER_D3D12;
    rdr.device=device.Get();rdr.command_queue=queue.Get();
    UEVR_PluginInitializeParam param{};
    param.version=&pv;param.callbacks=&callbacks;param.functions=&functions;param.renderer=&rdr;
    auto init=symbol<UEVR_PluginInitializeFn>(plugin,"uevr_plugin_initialize");
    TEST(init&&init(&param)&&custom,"UEVR shader/controls plugin loaded");
    custom("glamayre_sharpen.set","enabled=1");
    custom("glamayre_sharpen.set","strength=2");
    custom("glamayre_sharpen.set","debug=1");

    XrGraphicsBindingD3D12KHR binding{XR_TYPE_GRAPHICS_BINDING_D3D12_KHR};
    binding.device=device.Get();binding.queue=queue.Get();
    XrSessionCreateInfo sci{XR_TYPE_SESSION_CREATE_INFO};sci.next=&binding;
    sci.systemId=1;
    XrSession ses=XR_NULL_HANDLE;
    TEST(createSession(instance,&sci,&ses)==XR_SUCCESS&&ses==session,"D3D12 session created");
    XrSwapchainCreateInfo ci{XR_TYPE_SWAPCHAIN_CREATE_INFO};
    ci.width=128;ci.height=64;ci.arraySize=1;ci.mipCount=1;ci.sampleCount=1;ci.faceCount=1;
    ci.format=DXGI_FORMAT_B8G8R8A8_UNORM_SRGB;
    XrSwapchain color=XR_NULL_HANDLE;
    TEST(createSwap(ses,&ci,&color)==XR_SUCCESS&&color==projection,"Projection swapchain created");
    ci.height=32;
    XrSwapchain uiSc=XR_NULL_HANDLE;
    TEST(createSwap(ses,&ci,&uiSc)==XR_SUCCESS&&uiSc==ui,"UI swapchain created");
    XrSwapchainImageAcquireInfo ai{XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO};
    XrSwapchainImageReleaseInfo ri{XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO};
    uint32_t index=99;
    // Before projection identity is known, no image may be modified.
    TEST(acquire(color,&ai,&index)==XR_SUCCESS&&index==0,"Acquire projection before discovery");
    TEST(release(color,&ri)==XR_SUCCESS,"Release before projection");
    XrCompositionLayerProjectionView views[2]{
        XrCompositionLayerProjectionView{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW},
        XrCompositionLayerProjectionView{XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW}};
    views[0].subImage.swapchain=color;
    views[0].subImage.imageRect.extent={64,64};
    views[1].subImage.swapchain=color;
    views[1].subImage.imageRect.offset={64,0};
    views[1].subImage.imageRect.extent={64,64};
    XrCompositionLayerProjection projectionLayer{XR_TYPE_COMPOSITION_LAYER_PROJECTION};
    projectionLayer.viewCount=2;projectionLayer.views=views;
    const XrCompositionLayerBaseHeader* layers[]={
        reinterpret_cast<XrCompositionLayerBaseHeader*>(&projectionLayer)};
    XrFrameEndInfo fi{XR_TYPE_FRAME_END_INFO};
    fi.layerCount=1;fi.layers=layers;
    TEST(end(ses,&fi)==XR_SUCCESS,"Projection layer observed in xrEndFrame");
    TEST(acquire(uiSc,&ai,&index)==XR_SUCCESS,"UI acquisition");
    TEST(release(uiSc,&ri)==XR_SUCCESS,"UI release left untouched");
    TEST(acquire(color,&ai,&index)==XR_SUCCESS,"Projection acquisition");
    TEST(release(color,&ri)==XR_SUCCESS,"Projection release");
    using Snapshot=void(*)(uint64_t*,uint32_t);
    auto status=symbol<Snapshot>(layer,"glamayre_layer_get_status");
    TEST(status,"Layer status export");
    uint64_t stats[8]{};
    status(stats,8);
    TEST(stats[0]==1&&stats[1]==3&&stats[2]==3&&stats[3]==1&&stats[4]==1&&stats[5]>=1,
         "Real OpenXR dispatch processed one projection color and excluded UI");

    // Only capture and map GPU timestamps when user opts in.
    using GpuSnapshot=void(__cdecl*)(uint64_t*,uint32_t);
    auto gpuStatus=symbol<GpuSnapshot>(layer,"glamayre_layer_get_gpu_timing");
    TEST(gpuStatus,"GPU timer export");
    uint64_t timing[2]{};
    gpuStatus(timing,2);
    TEST(timing[1]==0,"Timer initially disabled and has no samples");
    // First drain previously submitted diagnostic-red pass, otherwise the
    // real layer correctly skips an in-flight XR image instead of stalling.
    ComPtr<ID3D12Fence> timingFence;
    HR(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&timingFence)),"Timestamp fence");
    HANDLE timingEvent=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    TEST(timingEvent!=nullptr,"Timestamp event");
    HR(queue->Signal(timingFence.Get(),1),"Complete first projection pass");
    HR(timingFence->SetEventOnCompletion(1,timingEvent),"Initial timestamp wait");
    auto timingWait=WaitForSingleObject(timingEvent,10000);
    TEST(timingWait==WAIT_OBJECT_0,"Previous projection work has finished");
    custom("glamayre_sharpen.set","timing=1");
    TEST(acquire(color,&ai,&index)==XR_SUCCESS,"Timed image acquisition");
    TEST(release(color,&ri)==XR_SUCCESS,"Timed image release");
    uint64_t timedStats[8]{};
    status(timedStats,8);
    TEST(timedStats[5]>=2,"Timed pass must have been enqueued on same XR image");
    HR(queue->Signal(timingFence.Get(),2),"Timestamp wait signal");
    HR(timingFence->SetEventOnCompletion(2,timingEvent),"Timestamp wait");
    timingWait=WaitForSingleObject(timingEvent,10000);
    CloseHandle(timingEvent);
    TEST(timingWait==WAIT_OBJECT_0,"Asynchronous timestamp GPU work completed");
    TEST(acquire(color,&ai,&index)==XR_SUCCESS,"Reuse timestamped image");
    TEST(release(color,&ri)==XR_SUCCESS,"Harvest completed timestamp without blocking");
    gpuStatus(timing,2);
    TEST(timing[1]>0,"Timestamp counter increments when diagnostic on");
    printf("Opt-in GPU cost: %llu microseconds over %llu samples\n",
        (unsigned long long)timing[0],(unsigned long long)timing[1]);
    const uint64_t sampleCount=timing[1];
    custom("glamayre_sharpen.set","timing=0");
    TEST(acquire(color,&ai,&index)==XR_SUCCESS,"Acquire with disabled timing");
    TEST(release(color,&ri)==XR_SUCCESS,"Render with no timestamp queries");
    gpuStatus(timing,2);
    TEST(timing[1]==sampleCount,"No GPU timing samples while disabled");

    // Copy rendered headset pixel back after all prior queue work, checking debug red grid.
    ComPtr<ID3D12CommandAllocator> alloc;
    HR(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&alloc)),"Readback allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;
    HR(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,alloc.Get(),nullptr,
        IID_PPV_ARGS(&cmd)),"Readback command list");
    desc=scene->GetDesc();
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};
    UINT rows=0;UINT64 bytes=0,size=0;
    device->GetCopyableFootprints(&desc,0,1,0,&fp,&rows,&bytes,&size);
    D3D12_HEAP_PROPERTIES rh{};rh.Type=D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    bd.Width=size;bd.Height=1;bd.DepthOrArraySize=1;bd.MipLevels=1;
    bd.SampleDesc.Count=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    ComPtr<ID3D12Resource> rb;
    HR(device->CreateCommittedResource(&rh,D3D12_HEAP_FLAG_NONE,&bd,
        D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&rb)),"Readback resource");
    D3D12_RESOURCE_BARRIER barrier{};
    barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource=scene;
    barrier.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    barrier.Transition.StateBefore=D3D12_RESOURCE_STATE_RENDER_TARGET;
    barrier.Transition.StateAfter=D3D12_RESOURCE_STATE_COPY_SOURCE;
    cmd->ResourceBarrier(1,&barrier);
    D3D12_TEXTURE_COPY_LOCATION src{},dst{};
    src.pResource=scene;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.pResource=rb.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=fp;
    cmd->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
    HR(cmd->Close(),"Finish readback");
    ID3D12CommandList* batch[]={cmd.Get()};
    queue->ExecuteCommandLists(1,batch);
    ComPtr<ID3D12Fence> fence;
    HR(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"Fence");
    HR(queue->Signal(fence.Get(),1),"Signal fence");
    HANDLE signal=CreateEventW(nullptr,FALSE,FALSE,nullptr);
    TEST(signal!=nullptr,"Fence event");
    HR(fence->SetEventOnCompletion(1,signal),"Signal completion event");
    DWORD wait=WaitForSingleObject(signal,10000);CloseHandle(signal);
    TEST(wait==WAIT_OBJECT_0&&SUCCEEDED(device->GetDeviceRemovedReason()),"GPU completed without removal");
    unsigned char* p=nullptr;
    HR(rb->Map(0,nullptr,reinterpret_cast<void**>(&p)),"Read pixel");
    bool red=p[2]>235&&p[1]<90&&p[0]<90;
    rb->Unmap(0,nullptr);
    TEST(red,"Pixel from genuine API-layer projection image contains red diagnostic grid");
    TEST(destroySwap(uiSc)==XR_SUCCESS&&destroySwap(color)==XR_SUCCESS,"Swapchain shutdown");
    TEST(destroySession(ses)==XR_SUCCESS&&destroyInstance(instance)==XR_SUCCESS,"OpenXR shutdown");
    printf("PASS: real layer negotiation + image dispatch + projection-only classification + WARP red pixels\n");
    return 0;
}
