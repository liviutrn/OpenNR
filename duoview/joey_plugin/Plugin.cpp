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
#include "DuoViewSubmission.hpp"
#include "DuoViewD3D12.hpp"
#include "PSVR2NativeGaze.hpp"
#include "MonoRenderingPolicy.hpp"

namespace dv = uevr::duoview;
using Microsoft::WRL::ComPtr;
namespace {
const UEVR_PluginInitializeParam* api{};
uintptr_t backend{};
std::atomic<int> mode{0};
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
dv::SubmissionMailbox<Packet> submissions;
std::atomic<uint64_t> last_report{}, last_success{}, last_status_write{}, last_status_check{}, last_wait_report{}, present_callbacks{};
std::atomic<uint64_t> engine_ticks{}, locate_calls{}, producer_pairs{}, render_callbacks{}, matched_packets{}, composite_queued{}, end_calls{}, submitted_layers{}, rejected_layers{}, xr_accepted{}, xr_failed{};
std::mutex status_mutex;
std::string status_reason{"Not initialized"};
std::filesystem::path status_path, status_request_path;
void set_reason(const char* reason) {
    std::scoped_lock lock(status_mutex);
    status_reason = reason;
}
void publish_status(bool force=false) {
    if (status_path.empty()) return;
    const auto now=GetTickCount64();
    if (!force) {
        // Poll infrequently, and do not do any file writes during gameplay
        // unless the UEVR ImGui panel has explicitly requested fresh status.
        auto checked = last_status_check.load();
        if (now - checked < 250 || !last_status_check.compare_exchange_strong(checked,now)) return;
        if (status_request_path.empty() || GetFileAttributesW(status_request_path.c_str()) == INVALID_FILE_ATTRIBUTES) return;
        DeleteFileW(status_request_path.c_str());
    }
    last_status_write.store(now);
    std::string reason;
    { std::scoped_lock lock(status_mutex); reason=status_reason; }
    auto temp=status_path; temp+=L".tmp";
    std::ofstream out(temp,std::ios::binary|std::ios::trunc);
    if (!out) return;
    out << "Mode=" << mode.load() << "\n"
        << "Hooks=" << (installed.load() ? "active" : "inactive") << "\n"
        << "Reason=" << reason << "\n"
        << "EngineTicks=" << engine_ticks.load() << "\n"
        << "PresentCallbacks=" << present_callbacks.load() << "\n"
        << "LocateViews=" << locate_calls.load() << "\n"
        << "ProducerPairs=" << producer_pairs.load() << "\n"
        << "RenderCallbacks=" << render_callbacks.load() << "\n"
        << "MatchedPackets=" << matched_packets.load() << "\n"
        << "CompositesQueued=" << composite_queued.load() << "\n"
        << "EndFrames=" << end_calls.load() << "\n"
        << "SubmittedLayers=" << submitted_layers.load() << "\n"
        << "RejectedLayers=" << rejected_layers.load() << "\n"
        << "XRSubmitAccepted=" << xr_accepted.load() << "\n"
        << "XRSubmitFailed=" << xr_failed.load() << "\n";
    out.close();
    if (out) MoveFileExW(temp.c_str(),status_path.c_str(),MOVEFILE_REPLACE_EXISTING);
}

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
    if (!installed.load() || mode.load() == 0 || !api->vr->is_openxr()) return false;
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
    value[0]=0; api->vr->get_mod_value("VR_FrameDelayCompensation",value,sizeof(value));
    if (std::string_view(value)!="0") return false;
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
    ++producer_pairs;
}
void pre_render_hook(void* extension,void* commands,void* family) {
    original_pre_render(extension,commands,family);
    ++render_callbacks;
    if (!native_mode() || !two_views(family)) return;
    const auto producer = family_frame(family);
    if (!producer) return;
    std::scoped_lock lock(packets_mutex);
    auto packet = packets.find(*producer);
    if (packet != packets.end() && packet->second.frame.config.key.generation == generation.load()) packet->second.render_seen = true;
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
    // Prefer any completed slot rather than skipping a frame because the next
    // round-robin slot is busy. Never reset an in-flight command allocator.
    const auto completed = gpu->fence->GetCompletedValue();
    Slot* ready = nullptr;
    for (size_t attempt = 0; attempt < gpu->slots.size(); ++attempt) {
        const auto index = (gpu->next + attempt) % gpu->slots.size();
        auto& candidate = gpu->slots[index];
        if (!candidate.fence || completed >= candidate.fence) {
            ready = &candidate;
            gpu->next = (index + 1) % gpu->slots.size();
            break;
        }
    }
    if (!ready) return false; // no CPU fence wait / forced hitch
    auto& slot = *ready;
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
    if (!dv::dx12::record_atlas_replacement(slot.compositor,device,slot.commands.Get(),source,slot.destination.Get(),packet.frame.config,frequency)) {
        slot.commands->Close(); return false;
    }
    if (FAILED(slot.commands->Close())) return false;
    ID3D12CommandList* lists[]{slot.commands.Get()}; queue->ExecuteCommandLists(1,lists);
    slot.fence=++gpu->signal;
    if (FAILED(queue->Signal(gpu->fence.Get(),slot.fence))) { report("DuoView queue fence signal failed"); return false; }
    ++composite_queued;
    set_reason("Composite queued on graphics queue; awaiting XR submission");
    const auto now=GetTickCount64(); auto previous=last_success.load();
    if (now-previous>=3000 && last_success.compare_exchange_strong(previous,now)) {
        const auto& l=packet.frame.config.layout;
        api->functions->log_info("[DuoViewJoey] Composite queued producer=%u fovea=%ux%u periphery=%ux%u output=%ux%u gaze=%s %.3f,%.3f previous-slot-GPU=%.3fms",
            packet.producer,l.fovea.width,l.fovea.height,l.periphery.width,l.periphery.height,l.atlas_width/2,l.atlas_height,
            packet.frame.gaze_valid ? "valid" : "fixed",packet.frame.config.gaze.u,packet.frame.config.gaze.v,slot.compositor.gpu_milliseconds());
    }
    return true;
}
int frame_hook(void* component,void* vr) {
    if (native_mode()) {
        const auto openxr = read<uintptr_t>(reinterpret_cast<uintptr_t>(vr)+0xa0);
        const auto handoff=openxr ? read<uint8_t>(*openxr+0x330) : std::nullopt;
        const auto consumer = openxr && handoff && *handoff ? read<uint32_t>(*openxr+0x32c) : std::nullopt;
        std::optional<Packet> packet;
        if (consumer) {
            std::scoped_lock lock(packets_mutex);
            const auto found=packets.find(*consumer);
            if (found!=packets.end() && found->second.render_seen && !found->second.used && found->second.frame.config.key.generation==generation.load()) {
                packet=found->second; found->second.used=true;
            }
        }
        if (packet) {
            ++matched_packets;
            auto* rhi=uevr::API::StereoHook::get_scene_render_target();
            auto* source=rhi ? static_cast<ID3D12Resource*>(rhi->get_native_resource()) : nullptr;
            if (mode==1 || compose(*packet,source)) {
                if (!submissions.publish(packet->optical.time, packet->frame.config.key.generation,
                        packet->frame.config.key.frame, *packet))
                    report("Duplicate or invalid predicted display time: frame not published");
            } else report("Scene format, queue, fence or compositor validation rejected this frame");
        } else report("Waiting for matching producer/render/consumer frame; no stale atlas will be submitted");
    }
    // xrEndFrame may run on another thread, or later than this callback.
    // Publication is bounded and can ONLY be consumed by its exact displayTime.
    return original_frame(component,vr);
}
XrResult XRAPI_CALL locate_hook(XrSession session,const XrViewLocateInfo* info,XrViewState* view_state,uint32_t capacity,uint32_t* count,XrView* views) {
    const auto result=original_locate(session,info,view_state,capacity,count,views);
    ++locate_calls;
    const auto valid=XR_VIEW_STATE_ORIENTATION_VALID_BIT|XR_VIEW_STATE_POSITION_VALID_BIT;
    if (XR_SUCCEEDED(result) && info && view_state && (view_state->viewStateFlags&valid)==valid && info->space==reinterpret_cast<XrSpace>(api->openxr->get_stage_space()) && count && *count==2 && capacity>=2 && views) {
        std::array<uevr::mono::Eye,2> eyes;
        for(size_t i=0;i<2;++i) {
            const auto& v=views[i]; eyes[i]={{v.pose.orientation.x,v.pose.orientation.y,v.pose.orientation.z,v.pose.orientation.w},{v.pose.position.x,v.pose.position.y,v.pose.position.z},
                {std::tan(v.fov.angleLeft),std::tan(v.fov.angleRight),std::tan(v.fov.angleUp),std::tan(v.fov.angleDown)}};
        }
        if (auto geometry=uevr::mono::geometry(eyes)) {
            // PSVR2 Toolkit gaze is already head-local. Sampling get_pose()
            // here is unsafe: Joey's view-space head update can follow LocateViews.
            // Estimate the head optical basis from the two *same-sample* eye
            // orientations so common head rotations cancel exactly.
            const glm::quat left{views[0].pose.orientation.w,views[0].pose.orientation.x,views[0].pose.orientation.y,views[0].pose.orientation.z};
            const glm::quat right{views[1].pose.orientation.w,views[1].pose.orientation.x,views[1].pose.orientation.y,views[1].pose.orientation.z};
            if (!std::isfinite(left.w) || !std::isfinite(right.w)) return result;
            const auto approximate_head=glm::normalize(glm::slerp(glm::normalize(left),glm::normalize(right),.5f));
            const auto optical_offset=glm::normalize(glm::inverse(approximate_head)*glm::normalize(left));
            std::scoped_lock lock(optics_mutex);
            optics=Optics{*geometry,info->displayTime,optical_offset};
        }
    }
    return result;
}
XrResult XRAPI_CALL end_hook(XrSession session,const XrFrameEndInfo* info) {
    ++end_calls;
    if (!native_mode() || !info || info->layerCount>64 || (info->layerCount && !info->layers))
        return original_end(session,info);
    // Consume exactly one producer whose LocateViews prediction matches
    // THIS OpenXR frame. No cross-thread TLS or last-frame fallback.
    const auto submitted=submissions.take(info->displayTime,generation.load());
    auto end=*info;
    std::vector<const XrCompositionLayerBaseHeader*> layers;
    bool prepared_scene_layer = false;
    std::vector<XrCompositionLayerProjection> projections; projections.reserve(info->layerCount);
    std::vector<std::array<XrCompositionLayerProjectionView,2>> pairs; pairs.reserve(info->layerCount);
    for(uint32_t i=0;i<info->layerCount;++i) {
        const auto* layer=info->layers[i];
        if (!layer || layer->type!=XR_TYPE_COMPOSITION_LAYER_PROJECTION) { layers.push_back(layer); continue; }
        const auto* projection=reinterpret_cast<const XrCompositionLayerProjection*>(layer);
        if (!submitted || projection->viewCount!=2) { ++rejected_layers; report("Withholding unpaired OpenXR scene layer"); continue; }
        auto pair=std::array{projection->views[0],projection->views[1]};
        std::array<uevr::mono::Eye,2> eyes;
        for (size_t eye=0;eye<2;++eye) {
            const auto& v=pair[eye]; eyes[eye]={{v.pose.orientation.x,v.pose.orientation.y,v.pose.orientation.z,v.pose.orientation.w},
                {v.pose.position.x,v.pose.position.y,v.pose.position.z},
                {std::tan(v.fov.angleLeft),std::tan(v.fov.angleRight),std::tan(v.fov.angleUp),std::tan(v.fov.angleDown)}};
        }
        const auto geometry=uevr::mono::geometry(eyes);
        if (!geometry || std::abs(geometry->horizontal-submitted->optical.geometry.horizontal)>0.0001f ||
            std::abs(geometry->vertical-submitted->optical.geometry.vertical)>0.0001f) { ++rejected_layers; report("Optical geometry changed between producer and submit"); continue; }
        const auto& g=*geometry;
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
        if (!valid_pair) { ++rejected_layers; continue; }
        ++submitted_layers;
        prepared_scene_layer = true;
        pairs.push_back(pair); projections.push_back(*projection); projections.back().views=pairs.back().data();
        layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projections.back()));
    }
    end.layerCount=static_cast<uint32_t>(layers.size()); end.layers=layers.data();
    const auto result = original_end(session,&end);
    if (prepared_scene_layer) {
        if (XR_SUCCEEDED(result)) {
            ++xr_accepted;
            set_reason("OpenXR accepted DuoView projection submission; headset visuals unverified");
        } else {
            ++xr_failed;
            set_reason("OpenXR rejected DuoView projection submission");
            report("OpenXR returned failure after DuoView projection submission");
        }
    }
    return result;
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
        // UEVR's Lua fs bindings are intentionally sandboxed in /data.
        // Keep native and Lua configuration/status in that same supported area.
        const auto data_path=std::filesystem::path(directory)/L"data";
        std::error_code directory_error;
        std::filesystem::create_directories(data_path,directory_error);
        config_=data_path/L"DuoViewJoey.ini";
        status_path=data_path/L"DuoViewJoey.status";
        status_request_path=data_path/L"DuoViewJoey.status.request";
        mode=static_cast<int>(GetPrivateProfileIntW(L"DuoView",L"Mode",0,config_.c_str()));
        api->functions->log_info("[DuoViewJoey] Config path=%ls Mode=%d",config_.c_str(),mode.load());
        if (mode<0 || mode>3) mode=0;
        if (!mode) { set_reason("Disabled in configuration; Joey is unchanged"); publish_status(true); api->functions->log_info("[DuoViewJoey] Disabled mode 0: released Joey rendering is unchanged"); return; }
        if (hash!="19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966") { mode=0; set_reason("Unsupported backend hash; hooks refused"); publish_status(true); api->functions->log_error("[DuoViewJoey] Unsupported backend: renderer hooks refused; use the pinned official Mono release"); return; }
        wchar_t game[32768]{}; GetModuleFileNameW(nullptr,game,32768);
        if (std::filesystem::path(game).filename()!=L"Stalker2-Win64-Shipping.exe") { mode=0; set_reason("Not STALKER 2 Shipping executable"); publish_status(true); api->functions->log_error("[DuoViewJoey] Renderer adapter is restricted to STALKER 2"); return; }
        for(const auto* module : {L"CheekyFoveatedDLSS.dll",L"CheekyFoveatedDLSSRuntime.dll",L"CheekyOpenXRLayer.dll",L"ReShade64.dll"}) {
            if (GetModuleHandleW(module)) { mode=0; set_reason("Incompatible Cheeky/ReShade module loaded; hooks refused"); publish_status(true); api->functions->log_error("[DuoViewJoey] Conflicting module loaded: %ls",module); return; }
        }
        dv::Settings settings;
        settings.crop_width=number(L"CropWidth",.5f); settings.crop_height=number(L"CropHeight",.5f);
        settings.peripheral_scale=number(L"PeripheralScale",.2f); settings.foveal_density=number(L"FovealDensity",1.f);
        settings.feather_fraction=number(L"Feather",.08f); settings.eye_tracked=mode==3;
        settings.debug_border=GetPrivateProfileIntW(L"DuoView",L"DebugBorder",1,config_.c_str())!=0;
        if (!state.configure(settings)) { mode=0; set_reason("Invalid crop/periphery/density settings"); publish_status(true); api->functions->log_error("[DuoViewJoey] Invalid layout settings; renderer hooks refused"); return; }
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
                mode=0; set_reason("Loaded hook signature mismatch; hooks refused"); publish_status(true); api->functions->log_error("[DuoViewJoey] Loaded hook prologue differs from the exact release; no renderer hooks installed"); return;
            }
        }
        pending_=true;
        set_reason("Validated binary; waiting for engine tick / OpenXR readiness");
        publish_status(true);
        api->functions->log_info("[DuoViewJoey] Backend validation passed; awaiting activation callback");
    }
    void on_pre_engine_tick(uevr::API::UGameEngine*, float) override {
        ++engine_ticks;
        activate_if_ready();
        publish_status();
    }
    void on_present() override {
        ++present_callbacks;
        activate_if_ready();
        publish_status();
    }
    void activate_if_ready() {
        if (!pending_ || installing_.test_and_set()) return;
        struct Unlock { std::atomic_flag& busy; ~Unlock(){ busy.clear(); } } unlock{installing_};
        if (!api->vr->is_openxr() || !api->vr->is_runtime_ready()) {
            auto last=last_wait_report.load();
            auto now=GetTickCount64();
            if (now-last >= 3000 && last_wait_report.compare_exchange_strong(last,now)) {
                set_reason("Waiting for OpenXR runtime readiness (UEVR native readiness gate)");
                api->functions->log_info("[DuoViewJoey] Waiting for OpenXR runtime ready; present=%llu tick=%llu", 
                    static_cast<unsigned long long>(present_callbacks.load()), static_cast<unsigned long long>(engine_ticks.load()));
            }
            return;
        }
        auto instance=reinterpret_cast<XrInstance>(api->openxr->get_xr_instance());
        if (!instance) {
            set_reason("OpenXR instance unavailable");
            return;
        }
        const auto loader=GetModuleHandleW(L"openxr_loader.dll");
        const auto get_proc=loader ? reinterpret_cast<PFN_xrGetInstanceProcAddr>(GetProcAddress(loader,"xrGetInstanceProcAddr")) : nullptr;
        PFN_xrVoidFunction locate{},end{};
        if (!get_proc || XR_FAILED(get_proc(instance,"xrLocateViews",&locate)) || XR_FAILED(get_proc(instance,"xrEndFrame",&end))) {
            set_reason("OpenXR loader functions unavailable; hooks pending");
            publish_status();
            return;
        }
        pending_=false;
        set_reason("Registering verified binary/OpenXR hooks");
        publish_status(true);
        const bool ok=hook(backend+0x2969b0,&rect_hook,original_rect) &&
            hook(backend+0x2bf2f0,&projection_hook,original_projection) &&
            hook(backend+0x2682c0,&projection_closure_hook,original_projection_closure) &&
            hook(backend+0x2ad080,&begin_hook,original_begin) &&
            hook(backend+0x3111f0,&pre_render_hook,original_pre_render) &&
            hook(backend+0x1f0f50,&frame_hook,original_frame) &&
            hook(reinterpret_cast<uintptr_t>(locate),&locate_hook,original_locate) &&
            hook(reinterpret_cast<uintptr_t>(end),&end_hook,original_end);
        if (!ok) { rollback_hooks(); mode=0; set_reason("Hook registration failed; rolled back, Joey untouched"); publish_status(true); api->functions->log_error("[DuoViewJoey] Hook transaction failed and was rolled back"); return; }
        installed=true;
        set_reason("Hooks active; waiting for paired UE scene frames");
        publish_status(true);
        api->functions->log_info("[DuoViewJoey] Mode=%d installed on unchanged official Joey Mono backend; select Native Stereo",mode.load());
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
        set_reason(installed ? "OpenXR/DX12 reset; awaiting fresh scene frames" : "Device reset; waiting for hooks");
        publish_status(true);
        state.retire();
        { std::scoped_lock lock(packets_mutex); packets.clear(); }
        submissions.retire();
        { std::scoped_lock lock(optics_mutex); optics.reset(); }
        { std::scoped_lock lock(gpu_mutex); if(gpu) retiring.push_back(std::move(gpu)); }
    }
private:
    float number(const wchar_t* key,float fallback) const {
        wchar_t buffer[64]{}; GetPrivateProfileStringW(L"DuoView",key,L"",buffer,64,config_.c_str());
        return buffer[0] ? std::wcstof(buffer,nullptr) : fallback;
    }
    std::filesystem::path config_;
    std::atomic<bool> pending_{false};
    std::atomic_flag installing_=ATOMIC_FLAG_INIT;
};
DuoViewPlugin plugin;
