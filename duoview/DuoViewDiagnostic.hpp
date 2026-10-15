#pragma once
// DuoView v49 diagnostic instrumentation. Experimental mode ID6 only.
// Three independent evidence channels: structured CPU frame trace, asynchronous
// GPU pixel patches, and a crash-tolerant rolling health report.
// No runtime memory-poking, no screenshot from the HMD, no third-party DLL.
#include "DuoViewState.hpp"
#include <windows.h>
#include <atomic>
#include <array>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <chrono>
#include <algorithm>

namespace uevr::duoview::diag {
enum class Phase : uint32_t { center=0, step=1, sweep=2, return_center=3, live=4 };
inline Phase phase_of(uint64_t n) {
    return n < 120 ? Phase::center : n < 240 ? Phase::step :
           n < 360 ? Phase::sweep : n < 480 ? Phase::return_center : Phase::live;
}
inline const char* phase_name(Phase p) {
    switch(p) {case Phase::center:return "CENTER";case Phase::step:return "STEP";
        case Phase::sweep:return "SWEEP";case Phase::return_center:return "RETURN";
        default:return "LIVE";}
}
struct CpuRecord {
    uint64_t qpc{}, frame{}, tick_ms{}, sensor_host_ms{};
    int64_t sensor_device_timestamp{};
    uint64_t scene_state{};
    uint32_t sensor_frame{}, stage{}, view{}, flags{}, phase{};
    float u{},v{}, crop_u0{},crop_v0{},crop_u1{},crop_v1{};
    double cam_x{},cam_y{},cam_z{}, expected_dx{},expected_dy{};
    double projection_0{},projection_5{},projection_8{},projection_9{};
};
struct ImageRecord {
    uint64_t frame{}, qpc{};
    uint32_t width{},height{},row_pitch{},format{},stage{},tile{};
    float u{},v{};
    std::vector<uint8_t> raw;
};
class Recorder {
public:
    static Recorder& get() { static Recorder* p=new Recorder(); return *p; }
    uint64_t sequence(uint64_t frame) {
        uint64_t expected=0;
        first_frame_.compare_exchange_strong(expected,frame,std::memory_order_acq_rel);
        const uint64_t base=first_frame_.load(std::memory_order_acquire);
        return frame>=base ? frame-base : 0;
    }
    GazeSample source_gaze(FrameKey key,GazeSample live) {
        const uint64_t seq=sequence(key.frame);
        const auto ph=phase_of(seq);
        if(ph==Phase::live) return live;
        const float u=ph==Phase::step ? 0.68f :
                      ph==Phase::sweep ? 0.35f + 0.30f * (float(seq-240)/119.f) : .5f;
        // Frame-domain synthetic gaze, independent of Toolkit/eye input. No
        // extra eye sampling; one packet is still frozen per producer frame.
        return GazeSample{UV{u,.5f},GetTickCount64(),true,false};
    }
    void cpu(uint32_t stage,uint32_t view,const ViewFrame& f,
             uint32_t flags=0,uint64_t scene_state=0,
             double proj0=0,double proj5=0,double proj8=0,double proj9=0,
             int64_t device_ts=0,uint32_t device_frame=0,uint64_t host_ms=0) {
        CpuRecord x{};
        LARGE_INTEGER q;QueryPerformanceCounter(&q);x.qpc=static_cast<uint64_t>(q.QuadPart);
        x.tick_ms=GetTickCount64();x.frame=f.config.key.frame;x.stage=stage;
        x.view=view;x.flags=flags;x.scene_state=scene_state;
        x.phase=static_cast<uint32_t>(phase_of(sequence(x.frame)));
        x.u=f.config.gaze.u;x.v=f.config.gaze.v;
        const auto& l=f.config.layout;
        x.crop_u0=l.u0;x.crop_v0=l.v0;x.crop_u1=l.u1;x.crop_v1=l.v1;
        x.cam_x=f.camera.position[0];x.cam_y=f.camera.position[1];x.cam_z=f.camera.position[2];
        x.projection_0=proj0;x.projection_5=proj5;x.projection_8=proj8;x.projection_9=proj9;
        x.sensor_device_timestamp=device_ts;x.sensor_frame=device_frame;x.sensor_host_ms=host_ms;
        if(!mu_.try_lock()){dropped_.fetch_add(1,std::memory_order_relaxed);return;}
        if(queue_.size()<20000)queue_.push_back(x);
        else dropped_.fetch_add(1,std::memory_order_relaxed);
        mu_.unlock();
        if(stage<stage_counts_.size())stage_counts_[stage].fetch_add(1,std::memory_order_relaxed);
        if(stage==7 && (flags & 1))faults_.fetch_add(1,std::memory_order_relaxed);
    }
    void gpu(ImageRecord&& image) {
        if(!mu_.try_lock()){dropped_images_.fetch_add(1,std::memory_order_relaxed);return;}
        if(images_.size()<20)images_.push_back(std::move(image));
        else dropped_images_.fetch_add(1,std::memory_order_relaxed);
        mu_.unlock();
        image_count_.fetch_add(1,std::memory_order_relaxed);
    }
    const std::filesystem::path& directory() const {return dir_;}
private:
    Recorder() {
        LARGE_INTEGER f{};QueryPerformanceFrequency(&f);frequency_=f.QuadPart;
        wchar_t path[MAX_PATH]{}; DWORD n=GetEnvironmentVariableW(L"LOCALAPPDATA",path,MAX_PATH);
        std::filesystem::path root=(n && n<MAX_PATH) ? std::filesystem::path(path)
            : std::filesystem::temp_directory_path();
        dir_=root / "DuoViewDiagnostics" /
            ("v49_pid"+std::to_string(GetCurrentProcessId())+"_tick"+std::to_string(GetTickCount64()));
        try {std::filesystem::create_directories(dir_);}
        catch(...){dir_=std::filesystem::temp_directory_path()/"DuoViewDiagnostics_fallback";
            try{std::filesystem::create_directories(dir_);}catch(...){}}
        std::thread([this] {writer();}).detach(); // process-lifetime diagnostics; no DllMain join
    }
    void writer() {
        std::ofstream csv(dir_/"frame_trace.csv",std::ios::out|std::ios::trunc);
        std::ofstream manifest(dir_/"image_manifest.csv",std::ios::out|std::ios::trunc);
        csv<<"qpc,qpc_frequency,tick_ms,frame,stage,view,flags,phase,u,v,crop_u0,crop_v0,crop_u1,crop_v1,cam_x,cam_y,cam_z,scene_state,proj0,proj5,proj8,proj9,sensor_device_timestamp,sensor_frame,sensor_host_ms\n";
        manifest<<"file,frame,qpc,tile,stage,width,height,row_pitch,dxgi_format,u,v\n";
        unsigned revision=0;
        for(;;) {
            std::this_thread::sleep_for(std::chrono::milliseconds(125));
            std::deque<CpuRecord> cp;
            std::deque<ImageRecord> imgs;
            {std::lock_guard<std::mutex> lock(mu_);cp.swap(queue_);imgs.swap(images_);}
            for(const auto& r:cp) {
                csv<<r.qpc<<','<<frequency_<<','<<r.tick_ms<<','<<r.frame<<','
                   <<r.stage<<','<<r.view<<','<<r.flags<<','<<r.phase<<','
                   <<std::setprecision(9)<<r.u<<','<<r.v<<','<<r.crop_u0<<','
                   <<r.crop_v0<<','<<r.crop_u1<<','<<r.crop_v1<<','
                   <<std::setprecision(17)<<r.cam_x<<','<<r.cam_y<<','<<r.cam_z<<','
                   <<r.scene_state<<','<<r.projection_0<<','<<r.projection_5<<','
                   <<r.projection_8<<','<<r.projection_9<<','
                   <<r.sensor_device_timestamp<<','<<r.sensor_frame<<','<<r.sensor_host_ms<<'\n';
            }
            for(auto& r:imgs) {
                std::string name="f"+std::to_string(r.frame)+"_t"+std::to_string(r.tile)+
                    "_q"+std::to_string(r.qpc)+".raw";
                std::ofstream out(dir_/name,std::ios::binary|std::ios::trunc);
                out.write(reinterpret_cast<const char*>(r.raw.data()),r.raw.size());
                out.close();
                manifest<<name<<','<<r.frame<<','<<r.qpc<<','<<r.tile<<','<<r.stage<<','
                    <<r.width<<','<<r.height<<','<<r.row_pitch<<','<<r.format<<','
                    <<r.u<<','<<r.v<<'\n';
            }
            csv.flush();manifest.flush();
            if(++revision%8==0){
                std::ofstream report(dir_/"health.txt",std::ios::trunc);
                report<<"DuoView v49 autonomous diagnostics\n"<<"Directory: "<<dir_.string()<<"\n"
                    <<"Synthetic phases by source frame: 0-119 CENTER, 120-239 STEP +0.18u, "
                    <<"240-359 SWEEP 0.35->0.65, 360-479 RETURN CENTER, 480+ LIVE TOOLKIT.\n"
                    <<"QPC frequency: "<<frequency_<<"\n"
                    <<"Stage 0=producer, 1=UE ctor input, 2=UE ctor result, "
                    <<"3=GPU composite submitted, 4=XR accepted, 7=fallback/fault.\n";
                for(size_t k=0;k<stage_counts_.size();++k)
                    report<<"stage_"<<k<<"="<<stage_counts_[k].load()<<"\n";
                report<<"raw_gpu_images_queued="<<image_count_.load()<<"\n"
                    <<"cpu_dropped="<<dropped_.load()<<"\n"
                    <<"images_dropped="<<dropped_images_.load()<<"\n"
                    <<"faults="<<faults_.load()<<"\n"
                    <<"Interpretation: CPU flags prove submitted values, not shader output. "
                    <<"GPU .raw patches are the separate image evidence. "
                    <<"Do not infer engine TSR history state only from a SceneViewState pointer.\n";
            }
        }
    }
    std::mutex mu_;
    std::deque<CpuRecord> queue_;
    std::deque<ImageRecord> images_;
    std::filesystem::path dir_;
    std::atomic<uint64_t> first_frame_{0},dropped_{0},dropped_images_{0},image_count_{0},faults_{0};
    std::array<std::atomic<uint64_t>,8> stage_counts_{};
    int64_t frequency_{};
};
} // namespace uevr::duoview::diag
