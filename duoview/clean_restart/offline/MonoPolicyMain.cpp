#include <cstdio>
#include <string_view>
#include "mods/vr/CompatibilityPolicy.hpp"

static unsigned failures{};
static unsigned checks{};
static void expect(bool condition, std::string_view message) {
    ++checks;
    if (!condition) {
        ++failures;
        std::fprintf(stderr, "FAIL: %.*s\n", static_cast<int>(message.size()), message.data());
    }
}

#include "MonoRenderingTests.hpp"

int main() {
    test_mono_rendering();
    std::printf("Original Joey Mono policy: %u checks, %u failures\n", checks, failures);
    return failures != 0;
}
