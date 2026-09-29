#pragma once
#include <Windows.h>
#include <algorithm>
#include <cstddef>
#include <filesystem>
#include <format>
#include <iostream>
#include <optional>
#include <vector>

// Standalone adapters for the source Runtime.cpp's two host utility dependencies.
namespace Util {
struct DllVersion {
    unsigned a,b,c,d;
    unsigned major() const { return a; }
    unsigned minor() const { return b; }
};
inline std::optional<DllVersion> GetDllVersion(const std::wstring& path) {
    DWORD ignored=0,size=GetFileVersionInfoSizeW(path.c_str(),&ignored);
    if (!size) return {};
    std::vector<std::byte> data(size);
    if (!GetFileVersionInfoW(path.c_str(),0,size,data.data())) return {};
    VS_FIXEDFILEINFO* info=nullptr;UINT length=0;
    if (!VerQueryValueW(data.data(),L"\\",reinterpret_cast<void**>(&info),&length) || length<sizeof(*info)) return {};
    return DllVersion{HIWORD(info->dwFileVersionMS),LOWORD(info->dwFileVersionMS),HIWORD(info->dwFileVersionLS),LOWORD(info->dwFileVersionLS)};
}
inline std::string GetFormattedVersion(const DllVersion& v) { return std::format("{}.{}.{}.{}",v.a,v.b,v.c,v.d); }
namespace PathHelpers { inline std::filesystem::path GetDataPath() { return std::filesystem::current_path(); } }
}
namespace logger {
template<class... T> void warn(std::format_string<T...> message,T&&... args) { std::cerr<<std::format(message,std::forward<T>(args)...)<<'\n'; }
}
