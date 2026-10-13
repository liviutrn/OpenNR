#define XR_USE_GRAPHICS_API_D3D12
#include <uevr/Plugin.hpp>
#include <d3d12.h>
#include <openxr/openxr.h>
#include <openxr/openxr_platform.h>
#include "JoeyCopyABI.hpp"
#include "CopyFlow.hpp"
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
#include "DuoViewActivation.hpp"
#include "OpticalCalibration.hpp"
#include "DuoViewD3D12.hpp"
#include "DuoViewOwnedCopy.hpp"
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
std::atomic<bool> armed{false}, faulted{false};
struct Slot;
struct Optics { uevr::mono::Geometry geometry; XrTime time{}; glm::quat eye_rotation{1,0,0,0}; };
std::optional<Optics> optics;
struct Packet { dv::ViewFrame frame{}; Optics optical{}; uint32_t producer{}; uint64_t epoch{}; bool modified{}, complete{}, render_seen{}, used{}; std::shared_ptr<Slot> slot; };
std::map<uint32_t, Packet> packets;
struct Draw { dv::FrameKey key; Optics optical; bool modified{}, published{}; std::shared_ptr<Slot> slot; };
thread_local std::optional<Draw> draw;
dv::SubmissionMailbox<Packet> submissions;
dv::ActivationGate activation_gate;
std::atomic<int> selected_mode{};
std::atomic<uint64_t> last_report{}, last_success{}, last_status_write{}, last_status_check{}, last_wait_report{}, present_callbacks{};
std::atomic<uint64_t> engine_ticks{}, locate_calls{}, producer_pairs{}, render_callbacks{}, matched_packets{}, composite_queued{}, end_calls{}, submitted_layers{}, rejected_layers{}, xr_accepted{}, xr_failed{};
std::atomic<uint32_t> output_width{}, output_height{};
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
        << "RequestedMode=" << selected_mode.load() << "\n"
        << "FrameCopyContract=" << (armed.load() ? "VERIFIED_COPY_CALLBACK" : "OBSERVING_OR_FALLBACK") << "\n"
        << "Reason=" << reason << "\n"
        << "OutputWidth=" << output_width.load() << "\n"
        << "OutputHeight=" << output_height.load() << "\n"
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
    if (!draw || !draw->modified || !native_mode()) return {};
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
duoview_joey::CopyFn original_copy{};
PFN_xrEnumerateSwapchainImages enumerate_images{};

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
struct Slot {
    ComPtr<ID3D12Resource> destination, source;
    ComPtr<ID3D12Fence> fence;
    uint64_t fence_value{};
    bool reserved{}, held{}, quarantined{};
    dv::dx12::Compositor compositor;
};
struct Gpu {
    ComPtr<ID3D12Device> device;
    ComPtr<ID3D12CommandQueue> queue;
    uint32_t width{}, height{};
    DXGI_FORMAT format{};
    std::array<std::shared_ptr<Slot>,4> slots;
};
std::shared_ptr<Gpu> gpu;
std::vector<std::shared_ptr<Gpu>> retiring;
struct Image {
    std::shared_ptr<Slot> slot;
    std::optional<Packet> mono;
    std::array<XrCompositionLayerProjectionView,2> native_views{};
    XrSwapchain swapchain{XR_NULL_HANDLE};
    uint64_t epoch{};
};
std::optional<Image> held_image;
XrSwapchain known_scene_handle{XR_NULL_HANDLE};
std::map<ID3D12Resource*,XrSwapchain> known_images;
struct Scope {
    std::optional<Packet> producer;
    std::optional<Image> image;
    ID3D12Resource* destination{};
    bool verified{}, failed{};
    std::shared_ptr<Slot> recording_slot;
};
thread_local Scope* copy_scope{};
void stop(const char* reason) {
    armed=false; faulted=true; set_reason(reason); report(reason);
}
bool retired(const std::shared_ptr<Slot>& slot) {
    return slot && !slot->quarantined && (!slot->fence ||
        slot->fence->GetCompletedValue()>=slot->fence_value);
}
std::shared_ptr<Slot> reserve_slot() {
    std::scoped_lock lock(gpu_mutex);
    if (!gpu || FAILED(gpu->device->GetDeviceRemovedReason())) return {};
    for (auto& slot:gpu->slots) {
        if (!slot->reserved && !slot->held && retired(slot)) {
            slot->reserved=true; return slot;
        }
    }
    return {};
}
void release_reservation(const std::shared_ptr<Slot>& slot) {
    if (!slot) return;
    std::scoped_lock lock(gpu_mutex); slot->reserved=false;
}
bool prepare_gpu(ID3D12Resource* source) {
    auto* device=static_cast<ID3D12Device*>(api->renderer->device);
    auto* queue=static_cast<ID3D12CommandQueue*>(api->renderer->command_queue);
    if (!device || !queue || !source || queue->GetDesc().Type!=D3D12_COMMAND_LIST_TYPE_DIRECT ||
        FAILED(device->GetDeviceRemovedReason())) return false;
    const auto desc=source->GetDesc();
    if (desc.Dimension!=D3D12_RESOURCE_DIMENSION_TEXTURE2D || desc.Width!=2ull*api->vr->get_hmd_width() ||
        desc.Height!=api->vr->get_hmd_height() || desc.Width>16384 || !desc.Width || !desc.Height ||
        desc.DepthOrArraySize!=1 || desc.MipLevels!=1 || desc.SampleDesc.Count!=1 ||
        desc.SampleDesc.Quality!=0 || !dv::dx12::bgra8(desc.Format) ||
        (desc.Flags&D3D12_RESOURCE_FLAG_DENY_SHADER_RESOURCE)) return false;
    ComPtr<ID3D12Device> sd,qd;
    if (FAILED(source->GetDevice(IID_PPV_ARGS(&sd))) || FAILED(queue->GetDevice(IID_PPV_ARGS(&qd))) ||
        sd.Get()!=device || qd.Get()!=device) return false;
    std::scoped_lock lock(gpu_mutex);
    if (gpu && gpu->device.Get()==device && gpu->queue.Get()==queue && gpu->width==desc.Width &&
        gpu->height==desc.Height && gpu->format==desc.Format) return true;
    // Resolution/device changes first return producer views to the original
    // renderer. All allocations happen during this unmodified observation phase.
    armed=false;
    if (gpu) { retiring.push_back(gpu); gpu.reset(); }
    if (held_image) { held_image->slot->held=false; held_image.reset(); }
    auto next=std::make_shared<Gpu>(); next->device=device; next->queue=queue;
    next->width=static_cast<uint32_t>(desc.Width); next->height=desc.Height; next->format=desc.Format;
    D3D12_HEAP_PROPERTIES heap{}; heap.Type=D3D12_HEAP_TYPE_DEFAULT;
    heap.CreationNodeMask=heap.VisibleNodeMask=1;

    for (auto& slot:next->slots) {
        slot=std::make_shared<Slot>();
        if (!slot->compositor.prewarm(device,next->width/2,next->height,
                desc.Format==DXGI_FORMAT_B8G8R8A8_UNORM_SRGB)) return false;

    }
    gpu=next;
    std::erase_if(retiring,[](const auto& old) {
        if (FAILED(old->device->GetDeviceRemovedReason())) return true;
        for (const auto& slot:old->slots) if (!retired(slot)) return false;
        return true;
    });
    return true;
}
// Copy only compatible owned/native images, using the state supplied by Joey's
// actual selected-scene boundary. Never replace an engine-owned scene resource.
void begin_hook(void* extension,void* family) {
    original_begin(extension,family);
    if (!draw || !installed || !two_views(family)) return;
    const auto producer=family_frame(family); if (!producer) return;
    Packet packet{}; packet.producer=*producer; packet.epoch=draw->key.generation;
    packet.optical=draw->optical; packet.modified=draw->modified; packet.slot=draw->slot;
    if (draw->modified) {
        state.family(draw->key,true,2);
        auto complete=state.consume(draw->key);
        if (complete) { packet.frame=*complete; packet.complete=true; }
        else stop("Incomplete paired views: holding the last coherent scene and restoring native producers");
    }
    std::scoped_lock lock(packets_mutex);
    if (packets.size()>=64) {
        for(auto& [key,p]:packets) release_reservation(p.slot);
        packets.clear(); stop("Producer backlog exceeded bound; restoring original rendering");
    }
    auto old=packets.find(*producer);
    if(old!=packets.end()) release_reservation(old->second.slot);
    packets.insert_or_assign(*producer,std::move(packet)); draw->published=true;
    if(draw->modified) ++producer_pairs;
}
void pre_render_hook(void* extension,void* commands,void* family) {
    original_pre_render(extension,commands,family); ++render_callbacks;
    if (!native_mode() || !two_views(family)) return;
    const auto producer=family_frame(family); if(!producer) return;
    std::scoped_lock lock(packets_mutex);
    auto p=packets.find(*producer);
    if(p!=packets.end() && p->second.epoch==generation.load()) p->second.render_seen=true;
}
int frame_hook(void* component,void* vr) {
    Scope scope{};
    if(installed && api->vr->is_openxr()) {
        const auto xr=read<uintptr_t>(reinterpret_cast<uintptr_t>(vr)+0xa0);
        const auto ready=xr ? read<uint8_t>(*xr+0x330):std::nullopt;
        const auto consumer=xr && ready && *ready ? read<uint32_t>(*xr+0x32c):std::nullopt;
        if(consumer) {
            std::scoped_lock lock(packets_mutex);
            auto p=packets.find(*consumer);
            if(p!=packets.end() && p->second.epoch==generation.load()) {
                scope.producer=p->second; packets.erase(p); ++matched_packets;
            }
        }
    }
    auto* previous=copy_scope; copy_scope=&scope;
    struct Restore { Scope*& target; Scope* previous; ~Restore(){target=previous;} } restore{copy_scope,previous};
    const int result=original_frame(component,vr);
    if(scope.producer) release_reservation(scope.producer->slot);
    release_reservation(scope.recording_slot);
    return result;
}
bool copy_hook(void* self,uint32_t index,ID3D12Resource* source,
    duoview_joey::CopyCallback pre,duoview_joey::ExtraCallback extra,
    D3D12_RESOURCE_STATES src_state,D3D12_BOX* box,duoview_joey::CopyCallback post,
    ID3D12Resource* retained,duoview_joey::RetainedPair pair) {
    using namespace duoview_joey;
    if(index!=0 || !copy_scope || (!native_mode() &&
        !(copy_scope->producer && copy_scope->producer->modified)))
        return original_copy(self,index,source,std::move(pre),std::move(extra),src_state,box,
            std::move(post),retained,std::move(pair));
    auto& scope=*copy_scope;
    const bool direct=source && !pre && !extra && !post && !box && !pair;
    std::optional<Image> hold;
    { std::scoped_lock lock(gpu_mutex); hold=held_image; }
    bool native=scope.producer && !scope.producer->modified;
    // At initial observation no producer may have passed our newly-installed
    // hooks yet. No cropped view can exist until a copied baseline is accepted.
    if(!scope.producer && !hold && !armed) native=true;
    if(!direct && native) {
        stop("Joey selected a callback/native-fix copy path; restore Native Stereo with Native Fix off");
        return original_copy(self,index,source,std::move(pre),std::move(extra),src_state,box,
            std::move(post),retained,std::move(pair));
    }
    const bool supported=direct && prepare_gpu(source);
    const auto action=choose_copy({native,scope.producer && scope.producer->modified,
        scope.producer && scope.producer->complete && scope.producer->render_seen,
        supported,scope.producer && bool(scope.producer->slot),bool(hold),
        !scope.producer || scope.producer->epoch==generation.load()});
    std::shared_ptr<Slot> slot;
    if(action==CopyAction::Compose) slot=scope.producer->slot;
    else if(action==CopyAction::Hold) { slot=hold->slot; stop("Frame copy mismatch: coherent held image; subsequent producers restored"); }
    else if(action==CopyAction::Native && supported && !armed && (!hold || !faulted)) {
        slot=reserve_slot();
        if(slot && !slot->destination) {
            ComPtr<ID3D12Device> device;source->GetDevice(IID_PPV_ARGS(&device));
            auto target=source->GetDesc();target.Format=DXGI_FORMAT_B8G8R8A8_TYPELESS;
            target.Flags=D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
            D3D12_HEAP_PROPERTIES heap{};heap.Type=D3D12_HEAP_TYPE_DEFAULT;
            heap.CreationNodeMask=heap.VisibleNodeMask=1;
            if(!device || FAILED(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&target,
                D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,IID_PPV_ARGS(&slot->destination)))) {
                release_reservation(slot);slot.reset();
            }
        }
    }
    if(action==CopyAction::Native && !slot) {
        // Passive original rendering: record the real acquired destination,
        // without altering scene pixels or optional callback ownership.
        CopyCallback observer=std::function<void(d3d12::CommandContext&,ID3D12Resource*)>(
            [&](d3d12::CommandContext&,ID3D12Resource* destination){scope.destination=destination;});
        return original_copy(self,index,source,std::move(pre),std::move(extra),src_state,box,
            std::move(observer),retained,std::move(pair));
    }
    if(!slot || action==CopyAction::Reject) {
        stop("No compatible scene/copy generation; original producer restored");
        scope.failed=true; return false;
    }
    ComPtr<ID3D12Device> device; auto* queue=static_cast<ID3D12CommandQueue*>(api->renderer->command_queue);
    if(!slot->compositor.mono_image() || FAILED(slot->compositor.mono_image()->GetDevice(IID_PPV_ARGS(&device))) || !queue) {scope.failed=true;return false;}
    scope.recording_slot=slot;
    d3d12::CommandContext* ctx{}; CopyProof proof{};
    CopyCallback commands=std::function<void(d3d12::CommandContext&,ID3D12Resource*)>(
        [&](d3d12::CommandContext& c,ID3D12Resource* destination) {
            ctx=&c; proof.fence_before=c.fence_value; scope.destination=destination;
            if(!c.ready()) return;
            const auto d=destination->GetDesc(),s=slot->compositor.mono_image()->GetDesc();
            ComPtr<ID3D12Device> dd;
            if(d.Width!=2*s.Width || d.Height!=s.Height || !dv::dx12::bgra8(d.Format) ||
               FAILED(destination->GetDevice(IID_PPV_ARGS(&dd))) || dd.Get()!=device.Get()) return;
            proof.destination_verified=true;
            if(action==CopyAction::Compose) {
                slot->source=source;
                if(!slot->compositor.record(device.Get(),c.cmd_list.Get(),source,
                    destination,src_state,scope.producer->frame.config)) return;
                proof.recorded=true;
            } else if(action==CopyAction::Native) {
                slot->source=source;
                if(!dv::dx12::copy_owned_image(c.cmd_list.Get(),device.Get(),source,slot->destination.Get(),src_state)) return;
            }
            if(action==CopyAction::Hold && hold->mono)
                proof.recorded=dv::dx12::copy_composite_to_stereo(c.cmd_list.Get(),device.Get(),slot->compositor.mono_image(),destination,
                    D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET);
            else if(action!=CopyAction::Compose)
                proof.recorded=dv::dx12::copy_owned_image(c.cmd_list.Get(),device.Get(),slot->destination.Get(),destination,
                    D3D12_RESOURCE_STATE_RENDER_TARGET);
            if(proof.recorded) c.has_commands=true;
        });
    // Original optional callbacks are absent on the validated direct path.
    // In a failed modified frame, never run a callback that copies a raw atlas.
    proof.original_returned=original_copy(self,index,nullptr,std::move(commands),std::nullopt,
        D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,std::nullopt,nullptr,nullptr);
    if(ctx) {
        std::scoped_lock lock(ctx->mtx);
        proof.fence_after=ctx->fence_value; proof.poisoned=ctx->poisoned;
        proof.waiting=ctx->waiting_for_fence;
        std::scoped_lock gpu_lock(gpu_mutex);
        if(proof.fence_after>proof.fence_before && ctx->fence) {
            slot->fence=ctx->fence; slot->fence_value=proof.fence_after;
        } else if(proof.recorded || slot->compositor.recorded_commands()) slot->quarantined=true;
    }
    if(!proof.queued()) {
        scope.failed=true; stop("Actual Joey copy/fence proof failed; restoring native producers");
        // Hardware/command-context failure cannot be cured by relabeling a
        // stale swapchain image. Do not publish this source as copied.
        if(hold && hold->epoch==generation.load() && hold->slot!=slot) {
            auto fallback=hold->slot; d3d12::CommandContext* fallback_ctx{}; CopyProof fallback_proof{};
            CopyCallback replay=std::function<void(d3d12::CommandContext&,ID3D12Resource*)>(
                [&](d3d12::CommandContext& c,ID3D12Resource* destination) {
                    fallback_ctx=&c;fallback_proof.fence_before=c.fence_value;scope.destination=destination;
                    if(!c.ready()) return;
                    fallback_proof.recorded=hold->mono ?
                        dv::dx12::copy_composite_to_stereo(c.cmd_list.Get(),device.Get(),fallback->compositor.mono_image(),destination,
                            D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_RENDER_TARGET) :
                        dv::dx12::copy_owned_image(c.cmd_list.Get(),device.Get(),fallback->destination.Get(),destination,D3D12_RESOURCE_STATE_RENDER_TARGET);
                    fallback_proof.destination_verified=fallback_proof.recorded;
                    if(fallback_proof.recorded) c.has_commands=true;
                });
            fallback_proof.original_returned=original_copy(self,index,nullptr,std::move(replay),std::nullopt,
                D3D12_RESOURCE_STATE_RENDER_TARGET,nullptr,std::nullopt,nullptr,nullptr);
            if(fallback_ctx) {
                std::scoped_lock lock(fallback_ctx->mtx);
                fallback_proof.fence_after=fallback_ctx->fence_value;
                fallback_proof.poisoned=fallback_ctx->poisoned;fallback_proof.waiting=fallback_ctx->waiting_for_fence;
                std::scoped_lock gpu_lock(gpu_mutex);
                if(fallback_proof.fence_after>fallback_proof.fence_before && fallback_ctx->fence) {
                    fallback->fence=fallback_ctx->fence;fallback->fence_value=fallback_proof.fence_after;
                } else if(fallback_proof.recorded) fallback->quarantined=true;
            }
            if(fallback_proof.queued()) {scope.verified=true;scope.failed=false;scope.image=*hold;return true;}
        }
        return false;
    }
    scope.verified=true; scope.failed=false;
    if(action==CopyAction::Hold) scope.image=*hold;
    else scope.image=Image{slot,action==CopyAction::Compose ? scope.producer : std::nullopt,{},XR_NULL_HANDLE,generation.load()};
    if(action==CopyAction::Compose) ++composite_queued;
    return true;
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
            const auto optical_offset=dv::synchronized_left_eye_offset(left,right);
            if (!optical_offset) return result;
            std::scoped_lock lock(optics_mutex);
            optics=Optics{*geometry,info->displayTime,*optical_offset};
        }
    }
    return result;
}
bool image_in_swapchain(XrSwapchain handle,ID3D12Resource* resource) {
    if(!enumerate_images || !handle || !resource) return false;
    {std::scoped_lock lock(gpu_mutex);auto found=known_images.find(resource);if(found!=known_images.end())return found->second==handle;}
    uint32_t count{};
    if(XR_FAILED(enumerate_images(handle,0,&count,nullptr)) || !count || count>64) return false;
    std::vector<XrSwapchainImageD3D12KHR> images(count,{XR_TYPE_SWAPCHAIN_IMAGE_D3D12_KHR});
    if(XR_FAILED(enumerate_images(handle,count,&count,
        reinterpret_cast<XrSwapchainImageBaseHeader*>(images.data())))) return false;
    bool found=false;
    { std::scoped_lock lock(gpu_mutex); for(const auto& image:images) {known_images[image.texture]=handle; if(image.texture==resource) found=true;} }
    return found;
    return false;
}
XrResult XRAPI_CALL end_hook(XrSession session,const XrFrameEndInfo* info) {
    ++end_calls;
    if(!copy_scope || (!native_mode() && !(copy_scope->producer && copy_scope->producer->modified)) || !info || info->layerCount>64 ||
        (info->layerCount && !info->layers)) return original_end(session,info);
    auto& scope=*copy_scope;
    auto end=*info;
    std::vector<const XrCompositionLayerBaseHeader*> layers;
    std::vector<XrCompositionLayerProjection> projections; projections.reserve(info->layerCount);
    std::vector<std::array<XrCompositionLayerProjectionView,2>> pairs; pairs.reserve(info->layerCount);
    bool scene=false;
    for(uint32_t i=0;i<info->layerCount;++i) {
        const auto* layer=info->layers[i];
        if(!layer || layer->type!=XR_TYPE_COMPOSITION_LAYER_PROJECTION) {layers.push_back(layer);continue;}
        const auto* p=reinterpret_cast<const XrCompositionLayerProjection*>(layer);
        if(p->viewCount!=2 || !p->views || p->space!=reinterpret_cast<XrSpace>(api->openxr->get_stage_space())) {layers.push_back(layer);continue;}
        const auto handle=p->views[0].subImage.swapchain;
        bool exact=scope.image && scope.image->swapchain==handle;
        {std::scoped_lock lock(gpu_mutex);if(scope.failed && known_scene_handle==handle) exact=true;}
        if(!exact && scope.destination && p->views[1].subImage.swapchain==handle &&
            p->views[0].subImage.imageArrayIndex==0 && p->views[1].subImage.imageArrayIndex==0)
            exact=image_in_swapchain(handle,scope.destination);
        if(!exact) {layers.push_back(layer);continue;}
        if(!scope.verified || !scope.image || scope.image->epoch!=generation.load()) {
            // Only an actual unrecoverable copy failure suppresses an image;
            // missing producer packets normally use the retained coherent hold.
            if(scope.failed) {++rejected_layers;continue;}
            layers.push_back(layer);continue;
        }
        auto pair=std::array{p->views[0],p->views[1]};
        if(scope.image->mono) {
            const auto& packet=*scope.image->mono; const auto& g=packet.optical.geometry;
            for(size_t eye=0;eye<2;++eye) {
                const auto crop=uevr::mono::projection_crop(g,eye,packet.frame.config.layout.atlas_width/2,
                    packet.frame.config.layout.atlas_height);
                if(!crop) return original_end(session,info);
                pair[eye].next=nullptr;
                pair[eye].pose={{g.orientation[0],g.orientation[1],g.orientation[2],g.orientation[3]},
                    {g.center[0],g.center[1],g.center[2]}};
                pair[eye].fov={std::atan(crop->fov[0]),std::atan(crop->fov[1]),std::atan(crop->fov[2]),std::atan(crop->fov[3])};
                pair[eye].subImage.imageRect={{static_cast<int32_t>(eye*(packet.frame.config.layout.atlas_width/2)+crop->x),
                    static_cast<int32_t>(crop->y)},{static_cast<int32_t>(crop->width),static_cast<int32_t>(crop->height)}};
            }
        } else if(scope.image->swapchain) {
            pair=scope.image->native_views;
        } else {
            // First full native snapshot carries the exact originally submitted
            // eye metadata. It is the fallback before the first DuoView success.
            for(auto& view:pair) view.next=nullptr;
            scope.image->native_views=pair;
        }
        scope.image->swapchain=handle;
        {std::scoped_lock lock(gpu_mutex);known_scene_handle=handle;}
        pairs.push_back(pair); projections.push_back(*p); projections.back().views=pairs.back().data();
        layers.push_back(reinterpret_cast<const XrCompositionLayerBaseHeader*>(&projections.back()));
        scene=true; ++submitted_layers;
    }
    end.layerCount=static_cast<uint32_t>(layers.size());end.layers=layers.data();
    // Presentation time remains Joey's current frame time. Pixel pose comes
    // from the exact copied producer (including an intentional coherent hold),
    // not from a comparison with xrLocateViews pose sample time.
    const auto result=original_end(session,&end);
    if(scene && XR_SUCCEEDED(result)) {
        ++xr_accepted;
        std::scoped_lock lock(gpu_mutex);
        if(held_image) held_image->slot->held=false;
        scope.image->slot->held=true; held_image=*scope.image;
        if(!faulted && scope.image->epoch==generation.load()) armed=true;
        set_reason(scope.image->mono ? "DuoView scene copied and XR accepted; headset validation pending" :
            faulted ? "Coherent native fallback; restart to retry DuoView" : "Native copy verified; DuoView activates at next complete producer frame");
    } else if(scene || scope.failed) {
        ++xr_failed; stop("OpenXR/copy rejected this frame; restoring original producers");
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
        selected_mode=mode.load();
        activation_gate.configure(mode!=0,generation.load());
        api->functions->log_info("[DuoViewJoey] Config path=%ls Mode=%d",config_.c_str(),mode.load());
        if (mode<0 || mode>3) mode=0;
        if(mode==1) { mode=0;set_reason("Shared-pose diagnostic retired; select fixed fovea or gaze mode");publish_status(true);return;}
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
        const std::array<uint8_t,20> copy_prologue{0x4c,0x89,0x4c,0x24,0x20,0x4c,0x89,0x44,0x24,0x18,0x89,0x54,0x24,0x10,0x55,0x53,0x56,0x57,0x41,0x54};
        if (!readable(backend+0x1c4280,copy_prologue.size()) || std::memcmp(reinterpret_cast<void*>(backend+0x1c4280),copy_prologue.data(),copy_prologue.size())) {mode=0;set_reason("Exact copy ABI entry mismatch");publish_status(true);return;}
        if (!dv::dx12::precompile_shader_cache()) {
            mode=0;
            set_reason("Compositor HLSL could not compile before renderer activation");
            publish_status(true);
            api->functions->log_error("[DuoViewJoey] Shader prewarm failed");
            return;
        }
        pending_=true;
        set_reason("Observing exact Joey copy boundary; producer views remain original until copied baseline is accepted");
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
        PFN_xrVoidFunction locate{},end{},enumerate{};
        if (!get_proc || XR_FAILED(get_proc(instance,"xrLocateViews",&locate)) || XR_FAILED(get_proc(instance,"xrEndFrame",&end)) ||
            XR_FAILED(get_proc(instance,"xrEnumerateSwapchainImages",&enumerate))) {
            set_reason("OpenXR loader functions unavailable; hooks pending");
            publish_status();
            return;
        }
        enumerate_images=reinterpret_cast<PFN_xrEnumerateSwapchainImages>(enumerate);
        pending_=false;
        set_reason("Registering verified binary/OpenXR hooks");
        publish_status(true);
        const bool ok=hook(backend+0x2969b0,&rect_hook,original_rect) &&
            hook(backend+0x2bf2f0,&projection_hook,original_projection) &&
            hook(backend+0x2682c0,&projection_closure_hook,original_projection_closure) &&
            hook(backend+0x2ad080,&begin_hook,original_begin) &&
            hook(backend+0x3111f0,&pre_render_hook,original_pre_render) &&
            hook(backend+0x1f0f50,&frame_hook,original_frame) &&
            hook(backend+0x1c4280,&copy_hook,original_copy) &&
            hook(reinterpret_cast<uintptr_t>(locate),&locate_hook,original_locate) &&
            hook(reinterpret_cast<uintptr_t>(end),&end_hook,original_end);
        if (!ok) { rollback_hooks(); mode=0; set_reason("Hook registration failed; rolled back, Joey untouched"); publish_status(true); api->functions->log_error("[DuoViewJoey] Hook transaction failed and was rolled back"); return; }
        installed=true;
        set_reason("Copy observer installed; original views until exact baseline snapshot is accepted");
        publish_status(true);
        api->functions->log_info("[DuoViewJoey] Mode=%d installed on unchanged official Joey Mono backend; select Native Stereo",mode.load());
    }
    void on_pre_viewport_client_draw(UEVR_UGameViewportClientHandle,UEVR_FViewportHandle,UEVR_FCanvasHandle) override {
        if(draw && !draw->published) release_reservation(draw->slot);
        draw.reset();
        output_width=api->vr->get_hmd_width(); output_height=api->vr->get_hmd_height();
        if(!native_mode()) {armed=false;return;}
        std::optional<Optics> optical;
        {std::scoped_lock lock(optics_mutex);optical=optics;}
        if(!optical) return;
        const auto serial=++draw_serial;
        auto slot=armed && !faulted ? reserve_slot() : std::shared_ptr<Slot>{};
        draw=Draw{{generation.load(),serial},*optical,bool(slot),false,slot};
        if(!slot) return; // Busy slots leave this producer fully unmodified.
        slot->destination.Reset(); // Retired native snapshot; active frames retain only the owned Mono image.
        std::array<float,16> projection{};
        projection[0]=1.f/optical->geometry.horizontal;projection[5]=1.f/optical->geometry.vertical;
        projection[11]=1.f;projection[14]=.1f;
        const auto frame=state.begin(draw->key,output_width,output_height,projection,[&]() -> std::optional<dv::UV> {
            XrQuaternionf orientation{};if(!cheeky_psvr2::read_orientation(orientation)) return {};
            const glm::quat gaze{orientation.w,orientation.x,orientation.y,orientation.z};
            const auto ray=glm::inverse(optical->eye_rotation)*(gaze*glm::vec3{0,0,-1});
            const auto& g=optical->geometry;
            return dv::ray_to_uv({ray.x,ray.y,-ray.z},{-g.horizontal,g.horizontal,g.vertical,-g.vertical});
        });
        if(!frame) {release_reservation(slot);draw->slot.reset();draw->modified=false;stop("Layout invalid for current output; original producer restored");}
    }
    void on_post_viewport_client_draw(UEVR_UGameViewportClientHandle,UEVR_FViewportHandle,UEVR_FCanvasHandle) override {
        if(draw && !draw->published) release_reservation(draw->slot);
        draw.reset();
    }
    void on_post_calculate_stereo_view_offset(UEVR_StereoRenderingDeviceHandle,int index,float meters,UEVR_Vector3f* position,UEVR_Rotatorf* rotation,bool is_double) override {
        if (!draw || !draw->modified || !native_mode() || !is_double || index<0 || index>1 || !position || !rotation) return;
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
        armed=false; faulted=false;
        ++generation;
        activation_gate.reset(generation.load());
        set_reason(installed ? "OpenXR/DX12 reset; retired active generation" : "Device reset; awaiting verified scene-copy contract");
        publish_status(true);
        state.retire();
        { std::scoped_lock lock(packets_mutex); packets.clear(); }
        submissions.retire();
        { std::scoped_lock lock(optics_mutex); optics.reset(); }
        { std::scoped_lock lock(gpu_mutex); known_images.clear();known_scene_handle=XR_NULL_HANDLE;if(held_image) {held_image->slot->held=false;held_image.reset();} if(gpu) {retiring.push_back(gpu);gpu.reset();} }
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
