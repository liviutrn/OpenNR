#define NOMINMAX
#include <Windows.h>
#include <sdk/DiscoveryMemory.hpp>

namespace sdk::discovery {

bool read_process(void*, uintptr_t address, void* output, size_t size) {
    SIZE_T copied{};
    return address >= 0x10000 &&
        ReadProcessMemory(GetCurrentProcess(), reinterpret_cast<const void*>(address),
                          output, size, &copied) != 0 && copied == size;
}

bool executable_image(void*, uintptr_t address, size_t size) {
    MEMORY_BASIC_INFORMATION region{};
    if (address < 0x10000 || size == 0 || address > (std::numeric_limits<uintptr_t>::max)() - size ||
        VirtualQuery(reinterpret_cast<const void*>(address), &region, sizeof(region)) != sizeof(region) ||
        region.State != MEM_COMMIT || region.Type != MEM_IMAGE ||
        (region.Protect & (PAGE_GUARD | PAGE_NOACCESS)) != 0) {
        return false;
    }
    const auto protection = region.Protect & 0xFF;
    const auto base = reinterpret_cast<uintptr_t>(region.BaseAddress);
    return (protection == PAGE_EXECUTE_READ || protection == PAGE_EXECUTE_READWRITE ||
            protection == PAGE_EXECUTE_WRITECOPY) && address >= base &&
        address - base <= region.RegionSize && size <= region.RegionSize - (address - base);
}

}
