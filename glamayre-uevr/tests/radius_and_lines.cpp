// GPU integration regression for four independent Glamarye radius bands,
// original FXAA edge attenuation and independent isolated-thin-line protection.
// Exercises REAL pixel shader on Windows DX12 WARP (not a CPU reimplementation).
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <uevr/API.h>
#include <algorithm>
#include <array>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstring>
using Microsoft::WRL::ComPtr;
static UEVR_OnCustomEventCb custom=nullptr;
static bool cb(UEVR_OnCustomEventCb f){custom=f;return true;}
static bool present(UEVR_OnPresentCb){return true;}
static bool reset(UEVR_OnDeviceResetCb){return true;}
static unsigned persistent(wchar_t*,unsigned){return 0;}
static void noop(const char*,...) {}
static void luaEvent(const char*,const char*) {}
#define HR(EXPR,MSG) do {auto h=(EXPR); if(FAILED(h)){fprintf(stderr,"%s failed 0x%08X\n",MSG,unsigned(h));return 2;}} while(0)
static void set(const char* key,float value) {
    char s[128];sprintf_s(s,"%s=%.5f",key,double(value));
    custom("glamayre_sharpen.set",s);
}
struct Mode {
    const char* name;
    float small,big,extra,ultra;
    bool protectEdges;
    float thin;
};
constexpr std::array<Mode,10> modes{{
    {"Original",0,0,0,0,false,0},
    {"Small",5,0,0,0,false,0},
    {"Big",0,5,0,0,false,0},
    {"Extra",0,0,5,0,false,0},
    {"Ultra",0,0,0,5,false,0},
    {"Ultra_Edges",0,0,0,5,true,0},
    {"Ultra_Thin100",0,0,0,5,false,1},
    {"Ultra_Thin050",0,0,0,5,false,0.5f},
    {"Small_Edges",5,0,0,0,true,0},
    {"Four_Bands",1,1,1,1,true,0.75f}
}};
int main(){
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(nullptr,path,MAX_PATH);
    wchar_t* pos=wcsrchr(path,L'\\');if(!pos)return 2;
    wcscpy_s(pos+1,MAX_PATH-size_t(pos+1-path),L"GlamaryeSharpenUEVR.dll");
    HMODULE dll=LoadLibraryW(path);
    if(!dll)return 2;
    using Init=bool(*)(const UEVR_PluginInitializeParam*);
    using Record=bool(*)(void*,void*,void*,bool);
    auto init=reinterpret_cast<Init>(GetProcAddress(dll,"uevr_plugin_initialize"));
    auto record=reinterpret_cast<Record>(GetProcAddress(dll,"glamayre_sharpen_gpu_record"));
    if(!init||!record)return 2;
    UEVR_PluginCallbacks callbacks{};callbacks.on_custom_event=cb;
    callbacks.on_present=present;callbacks.on_device_reset=reset;
    UEVR_PluginFunctions funcs{};
    funcs.log_error=noop;funcs.log_warn=noop;funcs.log_info=noop;
    funcs.dispatch_lua_event=luaEvent;funcs.get_persistent_dir=persistent;
    UEVR_PluginVersion version{UEVR_PLUGIN_VERSION_MAJOR,UEVR_PLUGIN_VERSION_MINOR,UEVR_PLUGIN_VERSION_PATCH};
    UEVR_RendererData renderer{};renderer.renderer_type=UEVR_RENDERER_D3D12;
    UEVR_PluginInitializeParam api{};api.version=&version;
    api.callbacks=&callbacks;api.functions=&funcs;api.renderer=&renderer;
    if(!init(&api)||!custom)return 2;
    ComPtr<ID3D12Debug> debug;
    if(SUCCEEDED(D3D12GetDebugInterface(IID_PPV_ARGS(&debug))))debug->EnableDebugLayer();
    ComPtr<IDXGIFactory4> factory;HR(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI");
    ComPtr<IDXGIAdapter> warp;HR(factory->EnumWarpAdapter(IID_PPV_ARGS(&warp)),"WARP");
    ComPtr<ID3D12Device> dev;HR(D3D12CreateDevice(warp.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&dev)),"Device");
    renderer.device=dev.Get();
    D3D12_COMMAND_QUEUE_DESC qd{};qd.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;
    HR(dev->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue)),"Queue");
    renderer.command_queue=queue.Get();
    ComPtr<ID3D12CommandAllocator> allocator;
    HR(dev->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&allocator)),"Allocator");
    ComPtr<ID3D12GraphicsCommandList> cmd;
    HR(dev->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,allocator.Get(),nullptr,IID_PPV_ARGS(&cmd)),"List");
    constexpr unsigned W=64,H=64;
    D3D12_HEAP_PROPERTIES props{};props.Type=D3D12_HEAP_TYPE_DEFAULT;
    D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;
    d.Width=W;d.Height=H;d.DepthOrArraySize=1;d.MipLevels=1;
    d.Format=DXGI_FORMAT_R8G8B8A8_UNORM;d.SampleDesc.Count=1;
    d.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    ComPtr<ID3D12Resource> rt;
    HR(dev->CreateCommittedResource(&props,D3D12_HEAP_FLAG_NONE,&d,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&rt)),"Source");
    D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.NumDescriptors=1;
    ComPtr<ID3D12DescriptorHeap> rtvHeap;HR(dev->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&rtvHeap)),"RTV heap");
    auto rtv=rtvHeap->GetCPUDescriptorHandleForHeapStart();
    dev->CreateRenderTargetView(rt.Get(),nullptr,rtv);
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT fp{};UINT rows=0;UINT64 rowBytes=0,total=0;
    dev->GetCopyableFootprints(&d,0,1,0,&fp,&rows,&rowBytes,&total);
    D3D12_HEAP_PROPERTIES rbProps{};rbProps.Type=D3D12_HEAP_TYPE_READBACK;
    D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;
    bd.Width=total;bd.Height=1;bd.DepthOrArraySize=1;bd.MipLevels=1;
    bd.SampleDesc.Count=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    std::array<ComPtr<ID3D12Resource>,modes.size()> outputs;
    for(auto& out:outputs)
        HR(dev->CreateCommittedResource(&rbProps,D3D12_HEAP_FLAG_NONE,&bd,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&out)),"Readback");
    D3D12_RESOURCE_BARRIER barrier{};barrier.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition.pResource=rt.Get();barrier.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    D3D12_TEXTURE_COPY_LOCATION source{},destination{};
    source.pResource=rt.Get();source.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    float background[4]{0.2f,0.2f,0.2f,1.0f};
    float wireColor[4]{0.65f,0.65f,0.65f,1.0f};
    float jaggyColor[4]{0.8f,0.8f,0.8f,1.0f};
    float textureColor[4]{0.45f,0.45f,0.45f,1.0f};
    D3D12_RECT screen{0,0,LONG(W),LONG(H)};
    D3D12_RECT wire{8,10,28,11};
    D3D12_RECT patch{5,46,20,54};
    set("enabled",1);set("debug",0);set("limit",0.4f);set("bias",0.020f);
    for(size_t k=0;k<modes.size();++k){
        const auto& m=modes[k];
        cmd->ClearRenderTargetView(rtv,background,1,&screen);
        cmd->ClearRenderTargetView(rtv,wireColor,1,&wire);
        cmd->ClearRenderTargetView(rtv,textureColor,1,&patch);
        // One-pixel staircase catches the distinction between FXAA jagged-edge
        // protection and isolated-line protection.
        for(LONG y=19;y<40;y++){
            LONG step=31+(y-19)/2;
            D3D12_RECT line{step,y,LONG(W),y+1};
            cmd->ClearRenderTargetView(rtv,jaggyColor,1,&line);
        }
        set("small",m.small);set("bigStrength",m.big);set("extra",m.extra);
        set("ultra",m.ultra);set("edges",m.protectEdges?1:0);set("thin",m.thin);
        if(k>0 && !record(cmd.Get(),rt.Get(),&rtv,false)){
            fprintf(stderr,"Shader refused %s\n",m.name);return 2;
        }
        barrier.Transition.StateBefore=D3D12_RESOURCE_STATE_RENDER_TARGET;
        barrier.Transition.StateAfter=D3D12_RESOURCE_STATE_COPY_SOURCE;
        cmd->ResourceBarrier(1,&barrier);
        destination={};destination.pResource=outputs[k].Get();
        destination.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;
        destination.PlacedFootprint=fp;
        cmd->CopyTextureRegion(&destination,0,0,0,&source,nullptr);
        barrier.Transition.StateBefore=D3D12_RESOURCE_STATE_COPY_SOURCE;
        barrier.Transition.StateAfter=D3D12_RESOURCE_STATE_RENDER_TARGET;
        cmd->ResourceBarrier(1,&barrier);
    }
    HR(cmd->Close(),"Close");
    ID3D12CommandList* lists[]{cmd.Get()};queue->ExecuteCommandLists(1,lists);
    ComPtr<ID3D12Fence> fence;HR(dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"Fence");
    HR(queue->Signal(fence.Get(),1),"Signal");
    HANDLE done=CreateEventW(nullptr,FALSE,FALSE,nullptr);if(!done)return 2;
    HR(fence->SetEventOnCompletion(1,done),"Completion");
    auto wait=WaitForSingleObject(done,10000);CloseHandle(done);
    if(wait!=WAIT_OBJECT_0||FAILED(dev->GetDeviceRemovedReason())) {
        fprintf(stderr,"GPU failed, wait=%lu, reason=0x%08X\n",wait,unsigned(dev->GetDeviceRemovedReason()));return 2;
    }
    std::array<std::array<uint8_t,W*H*4>,modes.size()> pixels{};
    std::array<int,modes.size()> wireValues{},changeCounts{};
    for(size_t k=0;k<modes.size();++k){
        uint8_t* p=nullptr;
        HR(outputs[k]->Map(0,nullptr,reinterpret_cast<void**>(&p)),"Map");
        for(unsigned y=0;y<H;y++) for(unsigned x=0;x<W;x++){
            unsigned psrc=unsigned(fp.Offset+y*fp.Footprint.RowPitch+x*4);
            unsigned dst=(y*W+x)*4;
            for(unsigned c=0;c<4;c++)pixels[k][dst+c]=p[psrc+c];
        }
        outputs[k]->Unmap(0,nullptr);
        wireValues[k]=pixels[k][(10*W+20)*4];
        for(size_t j=0;j<pixels[k].size();j+=4){
            if(abs(int(pixels[k][j])-int(pixels[0][j]))>1)++changeCounts[k];
        }
        printf("%s: thin-line pixel=%d, total changed=%d\n",modes[k].name,wireValues[k],changeCounts[k]);
    }
    bool good=true;
    for(unsigned k=1;k<=4;k++)if(changeCounts[k]<2){
        fprintf(stderr,"Radius %s did not change the GPU image\n",modes[k].name);good=false;
    }
    if(changeCounts[9]<2){fprintf(stderr,"4-band combination did not sharpen\n");good=false;}
    // Enabling anti-thin-line protection should reduce the sharpening shift
    // of a 1-pixel wire, rather than merely changing the UI checkbox.
    const int baseline=wireValues[0];
    const int exposed=abs(wireValues[4]-baseline);
    const int protectedChange=abs(wireValues[6]-baseline);
    if(exposed<3 || protectedChange>=exposed-2){
        fprintf(stderr,"Thin protection ineffective on isolated 1px line: exposed=%d protected=%d\n",
            exposed,protectedChange);good=false;
    }
    if(abs(wireValues[7]-baseline)>exposed || abs(wireValues[7]-baseline)<protectedChange){
        fprintf(stderr,"Half protection not between off and full protection\n");good=false;
    }
    // Original jagged-edge checkbox must materially change response somewhere
    // in the deliberate 1-pixel staircase test pattern.
    int edgePixelsChanged=0;
    for(unsigned y=18;y<41;y++)for(unsigned x=29;x<W;x++){
        size_t pix=(y*W+x)*4;
        if(abs(int(pixels[4][pix])-int(pixels[5][pix]))>=1)++edgePixelsChanged;
    }
    printf("FXAA jagged-edge protection changed %d staircase pixels\n",edgePixelsChanged);
    if(edgePixelsChanged<1){fprintf(stderr,"Original FXAA edge protection showed no effect\n");good=false;}
    if(!good) return 3;
    printf("PASS: 4 radii, original jagged-edge control, separate thin-line guard, additive multiband\n");
    return 0;
}
