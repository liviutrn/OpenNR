#pragma once
#include <cstdint>
namespace uevr::duoview::ngx {
struct Counters { uint64_t calls{},matched{},resets{},missing_frame{};bool installed{}; };
void service();
Counters counters();
}
