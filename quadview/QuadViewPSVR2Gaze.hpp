#pragma once

// ID7 adapter for the exact v186.1 PSVR2 Toolkit ABI and validation rules.
// It deliberately returns the recovered calibrated HEAD-space ray so the
// caller can project it once per true stereo eye. ID6's reader stays intact.
#include "DuoViewPSVR2Gaze.hpp"
#include <atomic>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string>

#ifdef _MSC_VER
#pragma comment(lib, "Advapi32.lib")
#endif

namespace uevr::quadview::psvr2 {

using Ray = duoview::Ray;
using Status = duoview::psvr2::Status;
using ReadFn = duoview::psvr2::ReadFn;
using InitFn = duoview::psvr2::InitFn;

struct Counters {
    uint64_t fresh{}, reused{}, invalid{}, expired{}, unavailable{};
    uint32_t age_ms{};
    bool available{}, active{};
};

class Reader {
public:
    void set_recovery_controls(uint32_t hold_ms, uint32_t reacquire_samples) {
        std::scoped_lock lock{mutex_};
        recovery_.controls(hold_ms, reacquire_samples);
    }

    bool active() const { return active_.load(std::memory_order_acquire); }
    bool available() const { return available_.load(std::memory_order_acquire); }

    Counters counters() const {
        return {fresh_.load(std::memory_order_relaxed), reused_.load(std::memory_order_relaxed),
            invalid_.load(std::memory_order_relaxed), expired_.load(std::memory_order_relaxed),
            unavailable_.load(std::memory_order_relaxed), age_ms_.load(std::memory_order_relaxed),
            available_.load(std::memory_order_relaxed), active_.load(std::memory_order_relaxed)};
    }

    // Call once per ID7 draw transaction. Eye projection must not call this.
    std::optional<Ray> read_ray() {
        std::scoped_lock lock{mutex_};
        const uint64_t now = GetTickCount64();
        if (!read_ && now >= next_attempt_) { initialize(); next_attempt_ = now + 1000; }
        if (!read_) {
            unavailable_.fetch_add(1, std::memory_order_relaxed);
            active_.store(false, std::memory_order_release);
            return {};
        }
        Status candidate{};
        const bool fresh = read_(&candidate, 0);
        const auto sample = fresh ? duoview::psvr2::calibrated_ray(candidate) : std::optional<Ray>{};
        const bool invalid = fresh && !sample.has_value();
        if (invalid) invalid_.fetch_add(1, std::memory_order_relaxed);
        const auto held = recovery_.update(now, sample, invalid);
        if (sample && !invalid) fresh_.fetch_add(1, std::memory_order_relaxed);
        if (!held) {
            age_ms_.store(UINT32_MAX, std::memory_order_relaxed);
            expired_.fetch_add(1, std::memory_order_relaxed);
            active_.store(false, std::memory_order_release);
            return {};
        }
        age_ms_.store(recovery_.age_ms(now), std::memory_order_relaxed);
        if (!fresh || invalid) reused_.fetch_add(1, std::memory_order_relaxed);
        active_.store(true, std::memory_order_release);
        return held;
    }

private:
    void initialize() {
        if (!module_) {
            module_ = GetModuleHandleW(L"psvr2_toolkit_capi.dll");
            wchar_t path[32768]{};
            const DWORD n = GetEnvironmentVariableW(L"PSVR2TK_CAPI_PATH", path, 32768);
            if (!module_ && n && n < 32768)
                module_ = LoadLibraryExW(path, nullptr,
                    LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
            if (!module_) try {
                std::ifstream file(std::filesystem::temp_directory_path() / "psvr2tk_capi_path.txt");
                std::string dir;
                if (file && std::getline(file, dir) && !dir.empty()) {
                    const auto candidate = std::filesystem::path(dir) / "psvr2_toolkit_capi.dll";
                    module_ = LoadLibraryExW(candidate.c_str(), nullptr,
                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            } catch (...) {}
            if (!module_) {
                wchar_t steam[32768]{};
                DWORD bytes = sizeof(steam);
                if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", L"SteamPath",
                    RRF_RT_REG_SZ, nullptr, steam, &bytes) == ERROR_SUCCESS) {
                    const std::wstring candidate = std::wstring(steam) +
                        L"\\steamapps\\common\\PlayStation VR2 App\\SteamVR_Plug-In\\bin\\win64\\psvr2_toolkit_capi.dll";
                    module_ = LoadLibraryExW(candidate.c_str(), nullptr,
                        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
                }
            }
            if (!module_) module_ = LoadLibraryW(L"psvr2_toolkit_capi.dll");
        }
        if (!module_) return;
        auto init = reinterpret_cast<InitFn>(GetProcAddress(module_, "psvr2_toolkit_init"));
        auto read = reinterpret_cast<ReadFn>(GetProcAddress(module_, "psvr2_toolkit_gaze_status"));
        if (init && read && init() == 0) {
            read_ = read;
            available_.store(true,std::memory_order_release);
        }
    }

    mutable std::mutex mutex_{};
    std::atomic<bool> active_{false};
    std::atomic<bool> available_{false};
    std::atomic<uint64_t> fresh_{0}, reused_{0}, invalid_{0}, expired_{0}, unavailable_{0};
    std::atomic<uint32_t> age_ms_{UINT32_MAX};
    HMODULE module_{};
    ReadFn read_{};
    uint64_t next_attempt_{};
    duoview::RayRecovery recovery_{};
};

} // namespace uevr::quadview::psvr2
