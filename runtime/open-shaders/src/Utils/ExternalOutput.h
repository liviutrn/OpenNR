#pragma once
#include <Windows.h>
#include <filesystem>
#include <stdexcept>
#include <string>

namespace OpenNRStorage
{
    /** Resolve an existing ancestor through Windows before allowing generated output. */
    inline std::filesystem::path ResolveExternalOutput(const std::filesystem::path& path)
    {
        auto ancestor = std::filesystem::absolute(path).lexically_normal();
        std::filesystem::path suffix;
        while (!std::filesystem::exists(ancestor)) {
            if (ancestor == ancestor.root_path())
                throw std::runtime_error("OpenNR output volume is unavailable");
            suffix = ancestor.filename() / suffix;
            ancestor = ancestor.parent_path();
        }
        const HANDLE handle = CreateFileW(ancestor.c_str(), FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
            OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr);
        if (handle == INVALID_HANDLE_VALUE)
            throw std::runtime_error("Cannot resolve OpenNR output storage");
        const DWORD required = GetFinalPathNameByHandleW(handle, nullptr, 0, FILE_NAME_NORMALIZED);
        std::wstring physical(required ? required : 1, L'\0');
        const DWORD length = GetFinalPathNameByHandleW(handle, physical.data(),
            static_cast<DWORD>(physical.size()), FILE_NAME_NORMALIZED);
        CloseHandle(handle);
        if (!required || !length || length >= physical.size())
            throw std::runtime_error("Cannot identify physical OpenNR output volume");
        physical.resize(length);
        if (physical.starts_with(L"\\\\?\\UNC\\"))
            physical = L"\\\\" + physical.substr(8);
        else if (physical.starts_with(L"\\\\?\\"))
            physical.erase(0, 4);
        const auto resolved = std::filesystem::path(physical) / suffix;
        if (_wcsicmp(resolved.root_name().c_str(), L"D:") == 0)
            throw std::invalid_argument("OpenNR generated output must be outside D:");
        return resolved;
    }
}
