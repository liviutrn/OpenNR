#pragma once
// Stage 5: Joey DuoView PSVR2 Toolkit CAPI reader. No driver or OpenXR layer replacement.
// ABI: BnuuySolutions/PSVR2Toolkit projects/common/hmd2_gaze.h (328 bytes).
#include "DuoViewGaze.hpp"
#include <windows.h>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>
#ifdef _MSC_VER
#pragma comment(lib, "Advapi32.lib")
#endif
namespace uevr::duoview::psvr2 {
enum class Bool : uint32_t { no, yes };
struct Vec2 { float x,y; };
struct Vec3 { float x,y,z; };
struct Lens { Vec3 left,right; };
enum class EnabledEye : uint8_t { left,right,both };
struct WearableEye {
    Bool origin_valid; Vec3 origin_mm;
    Bool direction_valid; Vec3 direction;
    Bool pupil_diameter_valid; float pupil_diameter_mm;
    Bool pupil_position_valid; Vec2 pupil_position;
    Bool guide_valid; Vec2 guide;
    Bool blink_valid; Bool blink;
};
struct Wearable {
    int64_t timestamp; uint32_t frame_counter;
    WearableEye left,right;
    Bool combined_origin_valid; Vec3 combined_origin;
    Bool combined_direction_valid; Vec3 combined_direction;
    Bool convergence_distance_valid;
};
struct Foveated {
    int64_t timestamp; uint32_t frame_counter; uint32_t tracking_state;
    Vec3 left,right,combined; float convergence_distance_mm;
};
struct Status {
    uint8_t magic[2]; uint16_t version; uint32_t size;
    float exposure_l,exposure_r;
    uint32_t led_status,exposure_counter_l,exposure_counter_r,led_counter;
    int32_t dsp_result; Lens lens; uint32_t calibration_id; Vec3 gaze_origin;
    EnabledEye eye; uint8_t motor_sequence,motor_strength;
    Wearable raw; Foveated tracked;
};
static_assert(sizeof(Status)==0x148,"PSVR2 Toolkit CAPI gaze ABI mismatch");
using InitFn = int(__cdecl*)();
using ReadFn = bool(__cdecl*)(Status*,uint32_t);

// Toolkit native basis X-left, Y-up, Z-forward -> common Mono X-right, Y-up, Z-forward.
inline std::optional<Ray> calibrated_ray(const Status& s) {
    if (s.size!=sizeof(Status) || s.magic[0]!='G' || s.magic[1]!='S' ||
        s.raw.combined_direction_valid!=Bool::yes ||
        (s.raw.left.blink_valid==Bool::yes && s.raw.left.blink==Bool::yes) ||
        (s.raw.right.blink_valid==Bool::yes && s.raw.right.blink==Bool::yes)) return {};
    const auto& d=s.raw.combined_direction;
    const float norm=std::sqrt(d.x*d.x+d.y*d.y+d.z*d.z);
    if (!std::isfinite(norm)||norm<.5f||norm>1.5f||d.z<.10f) return {};
    return Ray{-d.x/norm,d.y/norm,d.z/norm};
}

// Projection from Joey's actual shared Mono perspective, not a generic OpenXR matrix.
// Joey OpenXR::update_matrices creates a +Z-forward Unreal projection (p[11] == +1).
// A direction has no translation component; source gaze is already +forward.
inline std::optional<UV> projection_uv(const Ray& r,const std::array<float,16>& p) {
    if (!std::isfinite(r.right)||!std::isfinite(r.up)||
        !std::isfinite(r.forward)||r.forward<=.1f) return {};
    for(float x:p) if(!std::isfinite(x)) return {};
    const float x=p[0]*r.right+p[4]*r.up+p[8]*r.forward;
    const float y=p[1]*r.right+p[5]*r.up+p[9]*r.forward;
    const float w=p[3]*r.right+p[7]*r.up+p[11]*r.forward;
    if(!std::isfinite(w)||w<=.01f) return {};
    const float u=(x/w+1.f)*.5f, v=(1.f-y/w)*.5f;
    if(!std::isfinite(u)||!std::isfinite(v)) return {};
    return UV{std::clamp(u,0.f,1.f),std::clamp(v,0.f,1.f)};
}

struct Counters {
    uint64_t fresh{}, reused{}, invalid{}, expired{}, unavailable{};
    uint32_t age_ms{};
};
class Reader {
public:
    void set_recovery_controls(uint32_t hold_ms, uint32_t reacquire_samples) {
        std::scoped_lock lock{mutex_};
        recovery_.controls(hold_ms, reacquire_samples);
    }
    bool active() const { return active_.load(std::memory_order_acquire); }
    Counters counters() const {
        return {fresh_.load(std::memory_order_relaxed),reused_.load(std::memory_order_relaxed),
            invalid_.load(std::memory_order_relaxed),expired_.load(std::memory_order_relaxed),
            unavailable_.load(std::memory_order_relaxed),age_ms_.load(std::memory_order_relaxed)};
    }
    // Called ONLY for a new DuoView source-frame snapshot, not per eye or compositor.
    std::optional<UV> read_uv(const std::array<float,16>& projection,
                              const std::array<float,9>& optical_rotation) {
        std::scoped_lock lock{mutex_};
        const uint64_t now=GetTickCount64();
        if(!read_ && now>=next_attempt_) { initialize(); next_attempt_=now+1000; }
        if(!read_) {
            unavailable_.fetch_add(1,std::memory_order_relaxed);
            active_.store(false,std::memory_order_release); return {};
        }
        Status candidate{};
        const bool fresh=read_(&candidate,0);
        const auto sample = fresh ? calibrated_ray(candidate) : std::optional<Ray>{};
        const bool invalid = fresh && !sample.has_value();
        if (invalid) invalid_.fetch_add(1,std::memory_order_relaxed);
        const auto held = recovery_.update(now, sample, invalid);
        if (sample && !invalid)
            fresh_.fetch_add(1,std::memory_order_relaxed);
        if (!held) {
            age_ms_.store(UINT32_MAX,std::memory_order_relaxed);
            expired_.fetch_add(1,std::memory_order_relaxed);
            active_.store(false,std::memory_order_release);
            return {};
        }
        age_ms_.store(recovery_.age_ms(now),std::memory_order_relaxed);
        if (!fresh || invalid) reused_.fetch_add(1,std::memory_order_relaxed);
        const auto ray=optical_ray(*held,optical_rotation);
        const auto uv=ray ? projection_uv(*ray,projection) : std::optional<UV>{};
        active_.store(uv.has_value(),std::memory_order_release);
        return uv;
    }
private:
    void initialize() {
        if(!module_) {
            module_=GetModuleHandleW(L"psvr2_toolkit_capi.dll");
            wchar_t path[32768]{};
            const DWORD n=GetEnvironmentVariableW(L"PSVR2TK_CAPI_PATH",path,32768);
            if(!module_ && n && n<32768)
                module_=LoadLibraryExW(path,nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
            if(!module_) try {
                std::ifstream file(std::filesystem::temp_directory_path()/"psvr2tk_capi_path.txt");
                std::string dir;
                if(file && std::getline(file,dir) && !dir.empty()) {
                    const auto f=std::filesystem::path(dir)/"psvr2_toolkit_capi.dll";
                    module_=LoadLibraryExW(f.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            } catch(...) {}
            if(!module_) {
                wchar_t steam[32768]{};DWORD bytes=sizeof(steam);
                if(RegGetValueW(HKEY_CURRENT_USER,L"Software\\Valve\\Steam",L"SteamPath",
                    RRF_RT_REG_SZ,nullptr,steam,&bytes)==ERROR_SUCCESS) {
                    const std::wstring f=std::wstring(steam)+
                        L"\\steamapps\\common\\PlayStation VR2 App\\SteamVR_Plug-In\\bin\\win64\\psvr2_toolkit_capi.dll";
                    module_=LoadLibraryExW(f.c_str(),nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            }
            if(!module_) module_=LoadLibraryW(L"psvr2_toolkit_capi.dll");
        }
        if(!module_) return;
        auto init=reinterpret_cast<InitFn>(GetProcAddress(module_,"psvr2_toolkit_init"));
        auto read=reinterpret_cast<ReadFn>(GetProcAddress(module_,"psvr2_toolkit_gaze_status"));
        if(init && read && init()==0) read_=read;
    }
    mutable std::mutex mutex_{};
    std::atomic<bool> active_{false};
    std::atomic<uint64_t> fresh_{0},reused_{0},invalid_{0},expired_{0},unavailable_{0};
    std::atomic<uint32_t> age_ms_{UINT32_MAX};
    HMODULE module_{};
    ReadFn read_{};
    uint64_t next_attempt_{};
    RayRecovery recovery_{};
};
} // namespace uevr::duoview::psvr2
