#pragma once
// Cheeky PSVR2 experimental OpenXR fallback.
// ABI mirrors BnuuySolutions/PSVR2Toolkit projects/common/hmd2_gaze.h,
// without bundling, modifying, or replacing the driver's DLL.
// This file is intentionally self-contained for the Cheeky OpenXR layer.
#include <Windows.h>
#include <openxr/openxr.h>
#include <cmath>
#include <cstdint>
#include <string>
#include <fstream>
#include <filesystem>
#include <mutex>
#ifdef _MSC_VER
#pragma comment(lib, "Advapi32.lib")
#endif

namespace cheeky_psvr2 {
enum class gaze_bool : std::uint32_t { no, yes };
struct vec2 { float x, y; };
struct vec3 { float x, y, z; };
struct lens_config { vec3 left, right; };
enum class enabled_eye : std::uint8_t { left, right, both };
struct wearable_eye {
    gaze_bool origin_valid; vec3 origin_mm;
    gaze_bool direction_valid; vec3 direction;
    gaze_bool pupil_diameter_valid; float pupil_diameter_mm;
    gaze_bool pupil_position_valid; vec2 pupil_position;
    gaze_bool guide_valid; vec2 guide;
    gaze_bool blink_valid; gaze_bool blink;
};
struct wearable {
    std::int64_t timestamp;
    std::uint32_t frame_counter;
    wearable_eye left, right;
    gaze_bool combined_origin_valid; vec3 combined_origin;
    gaze_bool combined_direction_valid; vec3 combined_direction;
    gaze_bool convergence_distance_valid;
};
struct foveated {
    std::int64_t timestamp;
    std::uint32_t frame_counter;
    std::uint32_t tracking_state;
    vec3 left, right, combined;
    float convergence_distance_mm;
};
struct status {
    std::uint8_t magic[2]; std::uint16_t version; std::uint32_t size;
    float exposure_l, exposure_r;
    std::uint32_t led_status, exposure_counter_l, exposure_counter_r, led_counter;
    int dsp_result;
    lens_config lens;
    std::uint32_t calibration_id;
    vec3 gaze_origin;
    enabled_eye eye;
    std::uint8_t motor_sequence, motor_strength;
    wearable raw;
    foveated tracked;
};
static_assert(sizeof(status) == 0x148, "PSVR2Toolkit CAPI gaze layout drift");
using initialize_fn = int(__cdecl*)();
using gaze_fn = bool(__cdecl*)(status*, std::uint32_t);

inline HMODULE find_library() {
    if (auto mod = GetModuleHandleW(L"psvr2_toolkit_capi.dll")) return mod;
    wchar_t path[32768]{};
    auto count = GetEnvironmentVariableW(L"PSVR2TK_CAPI_PATH", path, 32768);
    if (count && count < 32768) {
        if (auto mod = LoadLibraryExW(path, nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)) return mod;
    }
    // Use exactly the path discovered by PSVR2 Toolkit's own CAPI loader.
    // Its driver publishes this directory in the system temp folder.
    try {
        std::ifstream path_file(std::filesystem::temp_directory_path() / "psvr2tk_capi_path.txt");
        std::string directory;
        if (path_file && std::getline(path_file, directory) && !directory.empty()) {
            const auto candidate = std::filesystem::path(directory) / "psvr2_toolkit_capi.dll";
            if (auto mod = LoadLibraryExW(candidate.c_str(), nullptr,
                LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)) return mod;
        }
    } catch (...) {}
    wchar_t steam[32768]{};
    DWORD size = sizeof(steam);
    if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", L"SteamPath",
        RRF_RT_REG_SZ, nullptr, steam, &size) == ERROR_SUCCESS) {
        const std::wstring candidate = std::wstring(steam) +
            L"\\steamapps\\common\\PlayStation VR2 App\\SteamVR_Plug-In\\bin\\win64\\psvr2_toolkit_capi.dll";
        if (auto mod = LoadLibraryExW(candidate.c_str(), nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)) return mod;
    }
    return LoadLibraryW(L"psvr2_toolkit_capi.dll");
}

struct bridge {
    HMODULE module{};
    gaze_fn read{};
    bool initialized{};
    bridge() { try_initialize(); }
    void try_initialize() {
        if (initialized) return;
        if (!module) module = find_library();
        if (!module) return;
        auto init = reinterpret_cast<initialize_fn>(GetProcAddress(module, "psvr2_toolkit_init"));
        auto read_function = reinterpret_cast<gaze_fn>(GetProcAddress(module, "psvr2_toolkit_gaze_status"));
        if (!init || !read_function || init() != 0) return;
        read = read_function;
        initialized = true;
    }
    ~bridge() {
        // Deliberately leave the CAPI slot intact at process teardown:
        // API-layer shutdown order can precede outstanding projection calls.
    }
};
inline bool read_orientation(XrQuaternionf& orientation) {
    static bridge api;
    // Non-blocking CAPI reads return false between new gaze frames and
    // do not copy a sample at all. Cache the last complete sample for at
    // most 50ms, in line with Cheeky's existing gaze-staleness policy.
    static std::mutex sample_mutex;
    static status cached_sample{};
    static bool have_cached_sample = false;
    static ULONGLONG last_fresh_tick = 0;
    std::lock_guard lock(sample_mutex);
    // UEVR can create its OpenXR instance before Toolkit finishes starting.
    // A failed first discovery must not permanently disable eye tracking.
    static ULONGLONG retry_at{};
    const ULONGLONG tick = GetTickCount64();
    if (!api.initialized && tick >= retry_at) {
        api.try_initialize();
        retry_at = tick + 1000ULL;
    }
    if (!api.initialized || !api.read) return false;
    status incoming{};
    // Toolkit getGazeStatus() does NOT write to the output argument when
    // there is no new frame. Its false return means "unchanged", not invalid.
    const bool new_frame = api.read(&incoming, 0);
    const ULONGLONG now = GetTickCount64();
    if (new_frame &&
        incoming.size == sizeof(incoming) &&
        incoming.magic[0] == 'G' && incoming.magic[1] == 'S') {
        cached_sample = incoming;
        have_cached_sample = true;
        last_fresh_tick = now;
    }
    // Keep the last complete valid sample across asynchronous gaze/frame
    // cadence differences; never accept a sample older than 50 milliseconds.
    if (!have_cached_sample || now - last_fresh_tick > 50) return false;
    const auto& sample = cached_sample;
    const auto& source = sample.raw;
    // Combined calibrated direction is in PSVR2 device coordinates.
    // Monado's known PSVR2->OpenXR mapping negates X and Z.
    if (source.combined_direction_valid != gaze_bool::yes) return false;
    if ((source.left.blink_valid == gaze_bool::yes && source.left.blink == gaze_bool::yes) ||
        (source.right.blink_valid == gaze_bool::yes && source.right.blink == gaze_bool::yes)) return false;
    const float x = -source.combined_direction.x;
    const float y = source.combined_direction.y;
    const float z = -source.combined_direction.z;
    const float length = std::sqrt(x*x + y*y + z*z);
    if (!std::isfinite(length) || length < 0.5f || length > 1.5f) return false;
    const float nx = x/length, ny = y/length, nz = z/length;
    // OpenXR straight ahead is -Z. Reject impossible backward samples.
    if (nz > -0.1f) return false;
    // Quaternion rotating (0,0,-1) into the calibrated gaze direction.
    const float qw = 1.0f - nz, qx = ny, qy = -nx;
    const float norm = std::sqrt(qw*qw + qx*qx + qy*qy);
    if (!std::isfinite(norm) || norm < 0.001f) return false;
    orientation = {qx/norm, qy/norm, 0.0f, qw/norm};
    return true;
}
} // namespace cheeky_psvr2

