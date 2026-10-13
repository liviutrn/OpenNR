#pragma once

#include <cstddef>
#include <cstdint>
#include <limits>
#include <type_traits>

namespace sdk::discovery {

/** Memory callbacks with the layout recorded in the official Joey PDB. */
struct Memory {
    void* context{};
    bool (*read)(void*, uintptr_t, void*, size_t){};
    bool (*executable)(void*, uintptr_t, size_t){};

    /** Read a complete trivial value through the supplied memory callback. */
    template<class T>
    bool load(uintptr_t address, T& value) const {
        static_assert(std::is_trivially_copyable_v<T>);
        return address != 0 && address <= (std::numeric_limits<uintptr_t>::max)() - sizeof(T) &&
            read != nullptr && read(context, address, &value, sizeof(T));
    }
};

static_assert(sizeof(Memory) == 24);
static_assert(offsetof(Memory, context) == 0 && offsetof(Memory, read) == 8 &&
              offsetof(Memory, executable) == 16);

/** Read current-process memory using the original complete-byte-count contract. */
bool read_process(void*, uintptr_t address, void* output, size_t size);

/** Require executable, readable image bytes inside one committed memory region. */
bool executable_image(void*, uintptr_t address, size_t size);

/** Construct the current-process callbacks without changing process state. */
inline Memory process_memory() {
    return {nullptr, read_process, executable_image};
}

}
