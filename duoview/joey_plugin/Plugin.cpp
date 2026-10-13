#include <uevr/Plugin.hpp>
#include <openxr/openxr.h>
#include <glm/gtx/euler_angles.hpp>
#include <glm/gtc/quaternion.hpp>
#include <bcrypt.h>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <map>
#include <vector>
#include "DuoViewState.hpp"
#include "DuoViewD3D12.hpp"
#include "PSVR2NativeGaze.hpp"
#include "MonoRenderingPolicy.hpp"

namespace dv = uevr::duoview;
using Microsoft::WRL::ComPtr;
namespace {
const UEVR_PluginInitializeParam* api{};
uintptr_t backend{};
int mode{};
std::atomic<bool> installed{};
std::atomic<uint64_t> generation{1}, draw_serial{};
dv::State state;
std::mutex packets_mutex, optics_mutex, gpu_mutex;
struct Optics { uevr::mono::Geometry geometry; XrTime time{}; glm::quat eye_rotation{1,0,0,0}; };
std::optional<Optics> optics;
struct Packet { dv::ViewFrame frame; Optics optical; uint32_t producer{}; bool render_seen{}, used{}; };
std::map<uint32_t, Packet> packets;
struct Draw { dv::FrameKey key; Optics optical; };
thread_local std::optional<Draw> draw;
thread_local std::optional<Packet> submitted;
std::atomic<uint64_t> last_report{};

bool readable(uintptr_t address, size_t size) {
    MEMORY_BASIC_INFORMATION info{};
    return address && size && VirtualQuery(reinterpret_cast<void*>(address), &info, sizeof(info)) &&
        info.State == MEM_COMMIT && !(info.Protect & (PAGE_NOACCESS | PAGE_GUARD)) &&
        address >= reinterpret_cast<uintptr_t>(info.BaseAddress) &&
        size <= info.RegionSize && address - reinterpret_cast<uintptr_t>(info.BaseAddress) <= info.RegionSize - size;
}
template<class T> std::optional<T> read(uintptr_t address) {
    if (!readable(address, sizeof(T))) return {};
    T result{}; std::memcpy(&result, reinterpret_cast<void*>(address), sizeof(T)); return result;
}
void report(const char* reason) {
    const auto now = GetTickCount64();
    auto previous=last_report.load();
    if (now - previous >= 3000 && last_report.compare_exchange_strong(previous,now)) api->functions->log_warn("[DuoViewJoey] %s", reason);
}
std::string file_hash(const std::filesystem::path& path) {
    std::ifstream stream(path, std::ios::binary);
    if (!stream) return {};
    BCRYPT_ALG_HANDLE algorithm{};
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0) return {};
    BCRYPT_HASH_HANDLE hash{};
    std::array<UCHAR,32> digest{};
    bool ok = BCryptCreateHash(algorithm, &hash, nullptr, 0, nullptr, 0, 0) >= 0;
    std::array<char,65536> buffer{};
    while (ok && stream) {
        stream.read(buffer.data(), buffer.size());
        if (stream.gcount()) ok = BCryptHashData(hash, reinterpret_cast<UCHAR*>(buffer.data()), static_cast<ULONG>(stream.gcount()), 0) >= 0;
    }
    ok = ok && stream.eof() && BCryptFinishHash(hash, digest.data(), static_cast<ULONG>(digest.size()), 0) >= 0;
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    if (!ok) return {};
    std::ostringstream result;
    for (auto byte : digest) result << std::hex << std::setw(2) << std::setfill('0') << unsigned(byte);
    return result.str();
}
std::optional<uint32_t> family_frame(void* family) {
    const auto offset = read<uint32_t>(backend + 0x13d6d70);
    if (!offset || *offset < 16 || *offset > 4096) return {};
    return read<uint32_t>(reinterpret_cast<uintptr_t>(family) + *offset);
}
bool two_views(void* family) {
    const auto descriptor = read<uintptr_t>(backend + 0xeba238);
    if (!descriptor) return false;
    const auto ready = read<uint8_t>(*descriptor + 0x18);
    const auto offset = read<uint32_t>(*descriptor + 0x14);
    if (!ready || !*ready || !offset || *offset > 4096) return false;
    const auto count = read<int32_t>(reinterpret_cast<uintptr_t>(family) + *offset + 8);
    return count && *count == 2;
}
bool native_mode() {
    if (!installed || !api->vr->is_openxr()) return false;
    const auto holder=read<uintptr_t>(backend+0xf10f10);
    const auto vr=holder ? read<uintptr_t>(*holder+8) : std::nullopt;
    const auto selection=vr ? read<uintptr_t>(*vr+0x56e60) : std::nullopt;
    const auto active=selection ? read<int32_t>(*selection+0x90) : std::nullopt;
    if (!active || *active!=0) return false;
    char value[64]{};
    api->vr->get_mod_value("VR_RenderingMethod", value, sizeof(value));
    if (std::string_view(value) != "0") return false;
    for (const char* key : {"VR_NativeStereoFix", "VR_ExtremeCompatibilityMode", "VR_StereoEmulation", "VR_2DScreenMode", "VR_Compatibility_SceneView"}) {
        value[0] = 0; api->vr->get_mod_value(key, value, sizeof(value));
        if (std::string_view(value) == "true" || std::string_view(value) == "1") return false;
    }
    return true;
}
std::optional<dv::ViewFrame> current_frame() {
    if (!draw || !native_mode()) return {};
    return state.snapshot(draw->key);
}
using RectFn = void(*)(void*,int32_t,int*,int*,uint32_t*,uint32_t*);
using ProjectionFn = void*(*)(void*,void*,int32_t);
using ProjectionClosureFn = void*(*)(void*,void*,void*,int32_t);
using BeginFn = void(*)(void*,void*);
using PreRenderFn = void(*)(void*,void*,void*);
using FrameFn = int(*)(void*,void*);
RectFn original_rect{};
ProjectionFn original_projection{};
ProjectionClosureFn original_projection_closure{};
BeginFn original_begin{};
PreRenderFn original_pre_render{};
FrameFn original_frame{};
PFN_xrLocateViews original_locate{};
PFN_xrEndFrame original_end{};

void rect_hook(void* stereo,int32_t index,int* x,int* y,uint32_t* w,uint32_t* h) {
    original_rect(stereo,index,x,y,w,h);
    const auto frame = current_frame();
    if (!frame || index < 0 || index > 1 || !x || !y || !w || !h) return;
    const auto& layout = frame->config.layout;
    const auto r = mode >= 2 ? (index == 0 ? layout.fovea : layout.periphery) : dv::Rect{uint32_t(index)*layout.atlas_width/2,0,layout.atlas_width/2,layout.atlas_height};
    *x = static_cast<int>(r.x); *y = static_cast<int>(r.y); *w = r.width; *h = r.height;
    state.rectangle(draw->key, static_cast<unsigned>(index));
}
void update_projection(void* output,int32_t index) {
    auto frame = current_frame();
    if (!frame || !output || index < 0 || index > 1) return;
    if (!readable(reinterpret_cast<uintptr_t>(output),sizeof(double)*16)) return;
    auto& matrix = *reinterpret_cast<std::array<std::array<double,4>,4>*>(output);
    const double near_z = matrix[3][2];
    if (!std::isfinite(near_z) || near_z <= 0 || near_z > 10000) return;
    matrix = {{{1.0/draw->optical.geometry.horizontal,0,0,0},{0,1.0/draw->optical.geometry.vertical,0,0},{0,0,0,1},{0,0,near_z,0}}};
    if (mode >= 2 && index == 0) dv::apply_foveal_crop(matrix, frame->config.layout);
    state.projection(draw->key, static_cast<unsigned>(index));
}
void* projection_hook(void* stereo,void* output,int32_t index) {
    auto result = original_projection(stereo,output,index); update_projection(output,index); return result;
}
void* projection_closure_hook(void* closure,void* stereo,void* output,int32_t index) {
    auto result = original_projection_closure(closure,stereo,output,index); update_projection(output,index); return result;
}
void begin_hook(void* extension,void* family) {
    original_begin(extension,family);
    if (!draw || !native_mode() || !two_views(family)) return;
    const auto producer = family_frame(family);
    if (!producer || !state.family(draw->key,true,2)) return;
    const auto complete = state.consume(draw->key);
    if (!complete) { report("Incomplete paired UE view callbacks; scene submission will be withheld"); return; }
    std::scoped_lock lock(packets_mutex);
    if (packets.size() >= 32) packets.erase(packets.begin());
    packets.insert_or_assign(*producer,Packet{*complete,draw->optical,*producer});
}
void pre_render_hook(void* extension,void* commands,void* family) {
    original_pre_render(extension,commands,family);
    if (!native_mode() || !two_views(family)) return;
    const auto producer = family_frame(family);
    if (!producer) return;
    std::scoped_lock lock(packets_mutex);
    auto packet = packets.find(*producer);
    if (packet != packets.end() && packet->second.frame.config.key.generation == generation.load()) packet->second.render_seen = true;
}
void transition(ID3D12GraphicsCommandList* commands,ID3D12Resource* resource,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER barrier{}; barrier.Type = D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    barrier.Transition = {resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,from,to}; commands->ResourceBarrier(1,&barrier);
}
struct Slot {
    ComPtr<ID3D12CommandAllocator> allocator;
    ComPtr<ID3D12GraphicsCommandList> commands;
    ComPtr<ID3D12Resource> destination,source;
    dv::dx12::Compositor compositor;
    uint64_t fence{};
};
struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    ComPtr<ID3D12Fence> fence;
    std::array<Slot,3> slots;
    uint64_t signal{};
    size_t next{};
};
std::unique_ptr<Gpu> gpu;
std::vector<std::unique_ptr<Gpu>> retiring;

bool compose(const Packet& packet,ID3D12Resource* source) {
    auto* device = static_cast<ID3D12Device*>(api->renderer->device);
    auto* queue = static_cast<ID3D12CommandQueue*>(api->renderer->command_queue);
    if (!device || !queue || !source || queue->GetDesc().Type != D3D12_COMMAND_LIST_TYPE_DIRECT || FAILED(device->GetDeviceRemovedReason())) return false;
    const auto desc = source->GetDesc();
    if (!dv::dx12::bgra8(desc.Format) || desc.Width != packet.frame.config.layout.atlas_width || desc.Height != packet.frame.config.layout.atlas_height ||
        desc.DepthOrArraySize != 1 || desc.MipLevels != 1 || desc.SampleDesc.Count != 1 || !(desc.Flags & D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET)) return false;
    ComPtr<ID3D12Device> source_device,queue_device;
    if (FAILED(source->GetDevice(IID_PPV_ARGS(&source_device))) || FAILED(queue->GetDevice(IID_PPV_ARGS(&queue_device))) || source_device.Get()!=device || queue_device.Get()!=device) return false;
    std::scoped_lock lock(gpu_mutex);
    std::erase_if(retiring,[](const auto& old) { return FAILED(old->device->GetDeviceRemovedReason()) || old->fence->GetCompletedValue() >= old->signal; });
    if (!gpu || gpu->device.Get()!=device || gpu->queue.Get()!=queue) {
        if (gpu) retiring.push_back(std::move(gpu));
        gpu = std::make_unique<Gpu>(); gpu->device=device; gpu->queue=queue;
        if (FAILED(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&gpu->fence)))) { gpu.reset(); return false; }
    }
    auto& slot = gpu->slots[gpu->next++ % gpu->slots.size()];
    if (slot.fence && gpu->fence->GetCompletedValue() < slot.fence) return false;
    slot.source=source;
    if (!slot.allocator) {
        if (FAILED(device->CreateCommandAllocator(D3D12_COMMAND_LIST_TYPE_DIRECT,IID_PPV_ARGS(&slot.allocator))) ||
            FAILED(device->CreateCommandList(0,D3D12_COMMAND_LIST_TYPE_DIRECT,slot.allocator.Get(),nullptr,IID_PPV_ARGS(&slot.commands)))) return false;
        if (FAILED(slot.commands->Close())) return false;
    }
    if (FAILED(slot.allocator->Reset()) || FAILED(slot.commands->Reset(slot.allocator.Get(),nullptr))) return false;
    if (!slot.destination || slot.destination->GetDesc().Width != desc.Width || slot.destination->GetDesc().Height != desc.Height) {
        slot.destination.Reset();
        auto target=desc; target.Format=DXGI_FORMAT_B8G8R8A8_TYPELESS;
        D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_DEFAULT; heap.CreationNodeMask=heap.VisibleNodeMask=1;
        if (FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&target,D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&slot.destination)))) { slot.commands->Close(); return false; }
        slot.destination->SetName(L"DuoViewJoey::DoubleWideComposite");
    }
    UINT64 frequency{}; queue->GetTimestampFrequency(&frequency);
    const auto recorded=slot.compositor.record(device,slot.commands.Get(),source,slot.destination.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,packet.frame.config,frequency);
    if (!recorded) { slot.commands->Close(); return false; }
    transition(slot.commands.Get(),source,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_DEST);
    transition(slot.commands.Get(),slot.destination.Get(),D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
    slot.commands->CopyResource(source,slot.destination.Get());
    transition(slot.commands.Get(),source,D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_RENDER_TARGET);
    transition(slot.commands.Get(),slot.destination.Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_RENDER_TARGET);
    if (FAILED(slot.commands->Close())) return false;
    ID3D12CommandList* lists[]{slot.commands.Get()}; queue->ExecuteCommandLists(1,lists);
    slot.fence=++gpu->signal;
    if (FAILED(queue->Signal(gpu->fence.Get(),slot.fence))) { report("DuoView queue fence signal failed"); return false; }
    return true;
}
int frame_hook(void* component,void* vr) {
    submitted.reset();
    if (native_mode()) {
        const auto openxr = read<uintptr_t>(reinterpret_cast<uintptr_t>(vr)+0xa0);
        const auto consumer = openxr ? read<uint32_t>(*openxr+0x32c) : std::nullopt;
        std::optional<Packet> packet;
        if (consumer) {
            std::scoped_lock lock(packets_mutex);
            const auto found=packets.find(*consumer);
            if (found!=packets.end() && found->second.render_seen && !found->second.used && found->second.frame.config.key.generation==generation.load()) {
                packet=found->second; found->second.used=true;
            }
        }
        if (packet) {
            auto* rhi=uevr::API::StereoHook::get_scene_render_target();
            auto* source=rhi ? static_cast<ID3D12Resource*>(rhi->get_native_resource()) : nullptr;
            if (mode==1 || compose(*packet,source)) submitted=packet;
            else report("Scene format, queue, fence or compositor validation rejected this frame");
        } else report("Waiting for matching producer/render/consumer frame; no stale atlas will be submitted");
    }
    const auto result=original_frame(component,vr);
    submitted.reset();
    return result;
}
XrResult XRAPI_CALL locate_hook(XrSession session,const XrViewLocateInfo* info,XrViewState* view_state,uint32_t capacity,uint32_t* count,XrView* views) {
    const auto result=original_locate(session,info,view_state,capacity,count,views);
    const auto valid=XR_VIEW_STATE_ORIENTATION_VALID_BIT|XR_VIEW_STATE_POSITION_VALID_BIT;
    if (XR_SUCCEEDED(result) && info && view_state && (view_state->viewStateFlags&valid)==valid && info->space==reinterpret_cast<XrSpace>(api->openxr->get_stage_space()) && count && *count==2 && capacity>=2 && views) {
        std::array<uevr::mono::Eye,2> eyes;
        for(size_t i=0;i<2;++i) {
            const auto& v=views[i]; eyes[i]={{v.pose.orientation.x,v.pose.orientation.y,v.pose.orientation.z,v.pose.orientation.w},{v.pose.position.x,v.pose.position.y,v.pose.position.z},
                {std::tan(v.fov.angleLeft),std::tan(v.fov.angleRight),std::tan(v.fov.angleUp),std::tan(v.fov.angleDown)}};
        }
        if (auto geometry=uevr::mono::geometry(eyes)) {
            UEVR_Vector3f position{}; UEVR_Quaternionf head{}; api->vr->get_pose(api->vr->get_hmd_index(),&position,&head);
            const glm::quat head_q{head.w,head.x,head.y,head.z};
            const glm::quat eye_q{views[0].pose.orientation.w,views[0].pose.orientation.x,views[0].pose.orientation.y,views[0].pose.orientation.z};
            std::scoped_lock lock(optics_mutex); optics=Optics{*geometry,info->displayTime,glm::normalize(glm::inverse(head_q)*eye_q)};
        }
    }
    return result;
}
XrResult XRAPI_CALL end_hook(XrSession session,const XrFrameEndInfo* info) {
    if (!native_mode() || !info || info->layerCount>64) return original_end(session,info);
    auto end=*info;
    std::vector<const XrCompositionLayerBaseHeader*> layers;
    std::vector<XrCompositionLayerProjection> projections; projections.reserve(info->layerCount);
    std::vector<std::array<XrCompositionLayerProjectionView,2>> pairs; pairs.reserve(info->layerCount);
    for(uint32_t i=0;i<info->layerCount;++i) {
        const auto* layer=info->layers[i];
        if (!layer || layer->type!=XR_TYPE_COMPOSITION_LAYER_PROJECTION) { layers.push_back(layer); continue; }
        const auto* projection=reinterpret_cast<const XrCompositionLayerProjection*>(layer);
        if (!submitted || submitted->optical.time!=info->displayTime || projection->viewCount!=2) { report("Withholding unpaired OpenXR scene layer"); continue; }
        const auto& g=submitted->optical.geometry;
        auto pair=std::array{projection->views[0],projection->views[1]};
        const auto width=submitted->frame.config.layout.atlas_width/2, height=submitted->frame.config.layout.atlas_height;
        bool valid_pair=true;
        for(size_t eye=0;eye<2;++eye) {
            const auto crop=uevr::mono::projection_crop(g,eye,width,height);
            if (!crop || pair[eye].subImage.imageArrayIndex!=0 || pair[eye].subImage.swapchain!=pair[0].subImage.swapchain) { valid_pair=false; break; }
            pair[eye].next=nullptr;
            pair[eye].pose={{g.orientation[0],g.orientation[1],g.orientation[2],g.orientation[3]},{g.center[0],g.center[1],g.center[2]}};
            pair[eye].fov={std::atan(crop->fov[0]),std::atan(crop->fov[1]),std::atan(crop->fov[2]),std::atan(crop->fov[3])};
            pair[eye].subImage.imageRect={{static_cast<int32_t>(eye*width+crop->x),static_cast<int32_t>(crop->y)},{static_cast<int32_t>(crop->width),static_cast<int32_t>(crop->height)}};
        }
        if (!valid_pair) continue;
        pairs.push_back(pair); projections.push_back(*projection); projections.back().views=pairs.back().data();
        layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projections.back()));
    }
    end.layerCount=static_cast<uint32_t>(layers.size()); end.layers=layers.data();
    return original_end(session,&end);
}
std::vector<int> hooks;
template<class Fn> bool hook(uintptr_t target,Fn replacement,Fn& original) {
    const auto id=api->functions->register_inline_hook(reinterpret_cast<void*>(target),reinterpret_cast<void*>(replacement),reinterpret_cast<void**>(&original));
    if (id<0) return false;
    hooks.push_back(id); return true;
}
void rollback_hooks() {
    for (auto it=hooks.rbegin();it!=hooks.rend();++it) api->functions->unregister_inline_hook(*it);
    hooks.clear();
}
}

class DuoViewPlugin : public uevr::Plugin {
public:
    void on_initialize() override {
        api=uevr::API::get()->param();
        backend=reinterpret_cast<uintptr_t>(api->uevr_module);
        wchar_t backend_path[32768]{}; GetModuleFileNameW(static_cast<HMODULE>(api->uevr_module),backend_path,32768);
        const auto hash=file_hash(backend_path);
        api->functions->log_info("[DuoViewJoey] Released-backend SHA256=%s commit=%s",hash.c_str(),api->functions->get_commit_hash());
        wchar_t directory[32768]{}; api->functions->get_persistent_dir(directory,32768);
        config_=std::filesystem::path(directory)/L"DuoViewJoey.ini";
        mode=static_cast<int>(GetPrivateProfileIntW(L"DuoView",L"Mode",0,config_.c_str()));
        if (mode<0 || mode>3) mode=0;
        if (!mode) { api->functions->log_info("[DuoViewJoey] Diagnostics mode: released Joey rendering is unchanged"); return; }
        if (hash!="19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966") { mode=0; api->functions->log_error("[DuoViewJoey] Unsupported backend: renderer hooks refused; use the pinned official Mono release"); return; }
        wchar_t game[32768]{}; GetModuleFileNameW(nullptr,game,32768);
        if (std::filesystem::path(game).filename()!=L"Stalker2-Win64-Shipping.exe") { mode=0; api->functions->log_error("[DuoViewJoey] Renderer adapter is restricted to STALKER 2"); return; }
        for(const auto* module : {L"CheekyFoveatedDLSS.dll",L"CheekyFoveatedDLSSRuntime.dll",L"CheekyOpenXRLayer.dll",L"ReShade64.dll"}) {
            if (GetModuleHandleW(module)) { mode=0; api->functions->log_error("[DuoViewJoey] Disable Cheeky/ReShade for the isolated recovery test; renderer hooks refused"); return; }
        }
        dv::Settings settings;
        settings.crop_width=number(L"CropWidth",.5f); settings.crop_height=number(L"CropHeight",.5f);
        settings.peripheral_scale=number(L"PeripheralScale",.2f); settings.foveal_density=number(L"FovealDensity",1.f);
        settings.feather_fraction=number(L"Feather",.08f); settings.eye_tracked=mode==3;
        settings.debug_border=GetPrivateProfileIntW(L"DuoView",L"DebugBorder",1,config_.c_str())!=0;
        if (!state.configure(settings)) { mode=0; api->functions->log_error("[DuoViewJoey] Invalid layout settings; renderer hooks refused"); return; }
        const std::array<std::pair<uintptr_t,std::array<uint8_t,16>>,6> contracts{{
            {0x2969b0,{0x4c,0x89,0x4c,0x24,0x20,0x89,0x54,0x24,0x10,0x55,0x53,0x57,0x41,0x54,0x41,0x55}},
            {0x2bf2f0,{0x48,0x8b,0xc4,0x44,0x89,0x40,0x18,0x48,0x89,0x50,0x10,0x48,0x89,0x48,0x08,0x55}},
            {0x2682c0,{0x48,0x8b,0xc4,0x48,0x89,0x58,0x08,0x44,0x89,0x48,0x20,0x4c,0x89,0x40,0x18,0x48}},
            {0x2ad080,{0x48,0x89,0x5c,0x24,0x08,0x55,0x56,0x57,0x41,0x54,0x41,0x55,0x41,0x56,0x41,0x57}},
            {0x3111f0,{0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x74,0x24,0x10,0x48,0x89,0x7c,0x24,0x18,0x55}},
            {0x1f0f50,{0x48,0x89,0x54,0x24,0x10,0x55,0x53,0x56,0x57,0x41,0x54,0x41,0x55,0x41,0x56,0x41}}
        }};
        for (const auto& [rva,bytes] : contracts) {
            if (!readable(backend+rva,bytes.size()) || std::memcmp(reinterpret_cast<void*>(backend+rva),bytes.data(),bytes.size())!=0) {
                mode=0; api->functions->log_error("[DuoViewJoey] Loaded hook prologue differs from the exact release; no renderer hooks installed"); return;
            }
        }
        pending_=true;
    }
    void on_present() override {
        if (!pending_ || !api->vr->is_openxr() || !api->vr->is_runtime_ready()) return;
        auto instance=reinterpret_cast<XrInstance>(api->openxr->get_xr_instance());
        if (!instance) return;
        const auto loader=GetModuleHandleW(L"openxr_loader.dll");
        const auto get_proc=loader ? reinterpret_cast<PFN_xrGetInstanceProcAddr>(GetProcAddress(loader,"xrGetInstanceProcAddr")) : nullptr;
        PFN_xrVoidFunction locate{},end{};
        if (!get_proc || XR_FAILED(get_proc(instance,"xrLocateViews",&locate)) || XR_FAILED(get_proc(instance,"xrEndFrame",&end))) return;
        pending_=false;
        const bool ok=hook(backend+0x2969b0,&rect_hook,original_rect) &&
            hook(backend+0x2bf2f0,&projection_hook,original_projection) &&
            hook(backend+0x2682c0,&projection_closure_hook,original_projection_closure) &&
            hook(backend+0x2ad080,&begin_hook,original_begin) &&
            hook(backend+0x3111f0,&pre_render_hook,original_pre_render) &&
            hook(backend+0x1f0f50,&frame_hook,original_frame) &&
            hook(reinterpret_cast<uintptr_t>(locate),&locate_hook,original_locate) &&
            hook(reinterpret_cast<uintptr_t>(end),&end_hook,original_end);
        if (!ok) { rollback_hooks(); mode=0; api->functions->log_error("[DuoViewJoey] Hook transaction failed and was rolled back"); return; }
        installed=true;
        api->functions->log_info("[DuoViewJoey] Mode=%d installed on unchanged official Joey Mono backend; select Native Stereo",mode);
    }
    void on_pre_viewport_client_draw(UEVR_UGameViewportClientHandle,UEVR_FViewportHandle,UEVR_FCanvasHandle) override {
        draw.reset();
        if (!native_mode()) return;
        std::optional<Optics> optical;
        { std::scoped_lock lock(optics_mutex); optical=optics; }
        if (!optical) return;
        const auto serial=++draw_serial;
        draw=Draw{{generation.load(),serial},*optical};
        std::array<float,16> projection{};
        projection[0]=1.f/optical->geometry.horizontal; projection[5]=1.f/optical->geometry.vertical; projection[11]=1.f; projection[14]=.1f;
        state.begin(draw->key,api->vr->get_hmd_width(),api->vr->get_hmd_height(),projection,[&]() -> std::optional<dv::UV> {
            XrQuaternionf orientation{};
            if (!cheeky_psvr2::read_orientation(orientation)) return {};
            const glm::quat gaze{orientation.w,orientation.x,orientation.y,orientation.z};
            const auto ray=glm::inverse(optical->eye_rotation)*(gaze*glm::vec3{0,0,-1});
            const auto& g=optical->geometry;
            return dv::ray_to_uv({ray.x,ray.y,-ray.z},{-g.horizontal,g.horizontal,g.vertical,-g.vertical});
        });
    }
    void on_post_viewport_client_draw(UEVR_UGameViewportClientHandle,UEVR_FViewportHandle,UEVR_FCanvasHandle) override { draw.reset(); }
    void on_post_calculate_stereo_view_offset(UEVR_StereoRenderingDeviceHandle,int index,float meters,UEVR_Vector3f* position,UEVR_Rotatorf* rotation,bool is_double) override {
        if (!draw || !native_mode() || !is_double || index<0 || index>1 || !position || !rotation) return;
        auto* p=reinterpret_cast<UEVR_Vector3d*>(position); auto* r=reinterpret_cast<UEVR_Rotatord*>(rotation);
        if (auto pose=state.camera(draw->key,static_cast<unsigned>(index))) {
            *p={pose->position[0],pose->position[1],pose->position[2]}; *r={pose->rotation[0],pose->rotation[1],pose->rotation[2]};
        } else {
            if (index != 0) return;
            UEVR_Vector3f left{},right{}; api->vr->get_eye_offset(UEVR_LEFT_EYE,&left); api->vr->get_eye_offset(UEVR_RIGHT_EYE,&right);
            char value[64]{}; api->vr->get_mod_value("VR_WorldScale",value,sizeof(value));
            const float scale=std::strtof(value,nullptr);
            if (!std::isfinite(scale) || scale<=0 || scale>10 || !std::isfinite(meters) || meters<=0) return;
            const auto q=glm::normalize(glm::quat{glm::yawPitchRoll(glm::radians(float(-r->yaw)),glm::radians(float(r->pitch)),glm::radians(float(-r->roll)))});
            const glm::vec3 offset{(left.x-right.x)*.5f,(left.y-right.y)*.5f,(left.z-right.z)*.5f};
            const auto delta=q*(offset*(meters*scale));
            const auto converter=glm::quat{glm::mat4{0,0,-1,0,1,0,0,0,0,1,0,0,0,0,0,1}};
            const auto correction=converter*delta;
            p->x+=correction.x; p->y+=correction.y; p->z+=correction.z;
        }
        state.camera(draw->key,static_cast<unsigned>(index),dv::CameraPose{{r->pitch,r->yaw,r->roll},{p->x,p->y,p->z}});
    }
    void on_device_reset() override {
        ++generation;
        state.retire();
        { std::scoped_lock lock(packets_mutex); packets.clear(); }
        { std::scoped_lock lock(optics_mutex); optics.reset(); }
        { std::scoped_lock lock(gpu_mutex); if(gpu) retiring.push_back(std::move(gpu)); }
    }
private:
    float number(const wchar_t* key,float fallback) const {
        wchar_t buffer[64]{}; GetPrivateProfileStringW(L"DuoView",key,L"",buffer,64,config_.c_str());
        return buffer[0] ? std::wcstof(buffer,nullptr) : fallback;
    }
    std::filesystem::path config_;
    bool pending_{};
};
DuoViewPlugin plugin;
