#define NOMINMAX
#include <Windows.h>
#include <sdk/DiscoveryMemory.hpp>
#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <span>
#include <stdexcept>
#include "OriginalMemoryReference.hpp"

namespace {
int failures{};
int checks{};

void expect(bool accepted, const char* description) {
    ++checks;
    if (!accepted) {
        ++failures;
        std::cerr << "FAILED: " << description << '\n';
    }
}

class OriginalFunction {
public:
    OriginalFunction(std::span<const uint8_t> code,
                     std::span<const original_sdk_memory::Patch> patches) {
        m_page = static_cast<uint8_t*>(VirtualAlloc(nullptr, 4096, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE));
        if (!m_page) { throw std::runtime_error("Reference allocation failed"); }
        try {
            if (code.size() > 1024 || patches.size() > 32) {
                throw std::runtime_error("Reference slice exceeds bounds");
            }
            std::memcpy(m_page, code.data(), code.size());
            const auto kernel = GetModuleHandleW(L"kernel32.dll");
            for (size_t index = 0; index < patches.size(); ++index) {
                const auto& patch = patches[index];
                if (patch.displacement < 2 || patch.displacement + 4 > code.size() ||
                    code[patch.displacement - 2] != 0xFF || code[patch.displacement - 1] != 0x15) {
                    throw std::runtime_error("Reference patch is not an indirect import call");
                }
                const auto function = GetProcAddress(kernel, patch.import);
                if (!function) { throw std::runtime_error("Reference import is unavailable"); }
                auto* slot = m_page + 2048 + index * sizeof(function);
                std::memcpy(slot, &function, sizeof(function));
                const auto distance = slot - (m_page + patch.displacement + 4);
                const auto relative = static_cast<int32_t>(distance);
                std::memcpy(m_page + patch.displacement, &relative, sizeof(relative));
            }
            DWORD prior{};
            if (!VirtualProtect(m_page, 4096, PAGE_EXECUTE_READ, &prior) ||
                !FlushInstructionCache(GetCurrentProcess(), m_page, code.size())) {
                throw std::runtime_error("Reference code publication failed");
            }
        } catch (...) {
            VirtualFree(m_page, 0, MEM_RELEASE);
            m_page = nullptr;
            throw;
        }
    }

    OriginalFunction(const OriginalFunction&) = delete;
    OriginalFunction& operator=(const OriginalFunction&) = delete;
    ~OriginalFunction() { if (m_page) { VirtualFree(m_page, 0, MEM_RELEASE); } }

    template<class Function>
    Function get() const {
        static_assert(sizeof(Function) == sizeof(m_page));
        Function function{};
        std::memcpy(&function, &m_page, sizeof(function));
        return function;
    }

private:
    uint8_t* m_page{};
};

class Pages {
public:
    Pages() {
        SYSTEM_INFO system{};
        GetSystemInfo(&system);
        page_size = system.dwPageSize;
        address = static_cast<uint8_t*>(VirtualAlloc(nullptr, page_size * 2,
            MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE));
        if (!address) { throw std::runtime_error("Test-page allocation failed"); }
        std::memset(address, 0x37, page_size * 2);
    }
    ~Pages() { if (address) { VirtualFree(address, 0, MEM_RELEASE); } }
    void protect(size_t page, DWORD protection) const {
        DWORD old{};
        if (!VirtualProtect(address + page * page_size, page_size, protection, &old)) {
            throw std::runtime_error("Test-page protection failed");
        }
    }
    uint8_t* address{};
    size_t page_size{};
};

void test_memory() {
    using Read = bool (*)(void*, uintptr_t, void*, size_t);
    using Executable = bool (*)(void*, uintptr_t, size_t);
    OriginalFunction original_read_code(original_sdk_memory::read_process_code,
                                        original_sdk_memory::read_process_patches);
    OriginalFunction original_executable_code(original_sdk_memory::executable_image_code,
                                              original_sdk_memory::executable_image_patches);
    const auto original_read = original_read_code.get<Read>();
    const auto original_executable = original_executable_code.get<Executable>();
    Pages pages;
    const auto base = reinterpret_cast<uintptr_t>(pages.address);

    const auto compare_read = [&](uintptr_t address, size_t count, bool null_output = false) {
        std::array<uint8_t, 64> original{}, reconstructed{};
        original.fill(0xA5);
        reconstructed = original;
        const auto first = original_read(nullptr, address, null_output ? nullptr : original.data(), count);
        const auto second = sdk::discovery::read_process(nullptr, address,
            null_output ? nullptr : reconstructed.data(), count);
        expect(first == second && original == reconstructed, "read result and bytes match the official SDK");
    };
    for (size_t count : {size_t{0}, size_t{1}, size_t{8}, size_t{64}}) {
        compare_read(base, count);
        compare_read(0, count);
        compare_read(0xFFFF, count);
    }
    compare_read(base, 8, true);
    compare_read((std::numeric_limits<uintptr_t>::max)() - 3, 8);
    pages.protect(1, PAGE_NOACCESS);
    compare_read(base + pages.page_size, 8);
    compare_read(base + pages.page_size - 8, 16);
    pages.protect(1, PAGE_READONLY);
    compare_read(base + pages.page_size - 8, 16);

    const auto compare_executable = [&](uintptr_t address, size_t count) {
        expect(original_executable(nullptr, address, count) ==
               sdk::discovery::executable_image(nullptr, address, count),
               "image-execution classification matches the official SDK");
    };
    const auto image_code = reinterpret_cast<uintptr_t>(&sdk::discovery::read_process);
    expect(original_executable(nullptr, image_code, 1), "reference recognizes real image code");
    for (const auto address : {uintptr_t{0}, uintptr_t{0xFFFF}, base, image_code,
                               (std::numeric_limits<uintptr_t>::max)() - 3}) {
        for (size_t count : {size_t{0}, size_t{1}, size_t{8}}) {
            compare_executable(address, count);
        }
    }
    for (const auto protection : {PAGE_EXECUTE, PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE,
                                  PAGE_READONLY, PAGE_READWRITE | PAGE_GUARD, PAGE_NOACCESS}) {
        pages.protect(1, static_cast<DWORD>(protection));
        compare_executable(base + pages.page_size, 8);
        compare_executable(base + pages.page_size - 8, 16);
    }
    MEMORY_BASIC_INFORMATION region{};
    if (VirtualQuery(reinterpret_cast<const void*>(image_code), &region, sizeof(region)) != sizeof(region)) {
        throw std::runtime_error("Image-region query failed");
    }
    const auto end = reinterpret_cast<uintptr_t>(region.BaseAddress) + region.RegionSize;
    compare_executable(end - 1, 1);
    compare_executable(end - 1, 2);
    compare_executable(image_code, (std::numeric_limits<size_t>::max)());

    int callback_count{};
    const sdk::discovery::Memory reader{&callback_count,
        [](void* context, uintptr_t, void* output, size_t count) {
            ++*static_cast<int*>(context);
            std::memset(output, 0x33, count);
            return true;
        }, nullptr};
    uint64_t value{};
    expect(reader.load(0x10000, value) && value == 0x3333333333333333ULL && callback_count == 1,
           "typed reader publishes the supplied callback bytes");
    expect(!reader.load(0, value) &&
           !reader.load((std::numeric_limits<uintptr_t>::max)() - 3, value) && callback_count == 1,
           "typed reader rejects null and overflowing ranges before callback execution");
    expect(!sdk::discovery::Memory{}.load(0x10000, value), "absent callback is rejected");
    const auto process = sdk::discovery::process_memory();
    expect(process.context == nullptr && process.read == sdk::discovery::read_process &&
           process.executable == sdk::discovery::executable_image,
           "process callbacks preserve the PDB-observed memory contract");
}
}

int main() {
    try { test_memory(); }
    catch (const std::exception& error) {
        ++failures;
        std::cerr << "Test error: " << error.what() << '\n';
    }
    std::cout << checks << " checks, " << failures << " failures\n";
    return failures == 0 ? 0 : 1;
}
