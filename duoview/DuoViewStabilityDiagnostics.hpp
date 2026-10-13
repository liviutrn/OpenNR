#pragma once
#include <atomic>
#include <chrono>
#include <cstdint>

namespace uevr::duoview::stability {
inline std::int64_t microseconds() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline void maximum(std::atomic<std::int64_t>& destination, std::int64_t sample) {
    auto old = destination.load(std::memory_order_relaxed);
    while (old < sample && !destination.compare_exchange_weak(old, sample, std::memory_order_relaxed)) {}
}
struct Counters {
    std::atomic<std::uint64_t> present_entries{0}, present_gaps_17ms{0}, present_gaps_33ms{0};
    std::atomic<std::uint64_t> frame_calls{0}, rejected_mono_frames{0};
    std::atomic<std::uint64_t> post_presents{0}, clears_blocked{0}, graphics_commits{0};
    std::atomic<std::uint64_t> main_families_1{0}, main_families_2{0}, main_families_other{0};
    std::atomic<std::uint32_t> raw_view_bits{0};
    std::atomic<std::int64_t> last_present_us{0}, max_present_gap_us{0};
    std::atomic<std::int64_t> max_frame_us{0}, max_commit_us{0}, max_clear_us{0};
};
inline Counters& counters() { static Counters c; return c; }
inline void present_entry() {
    auto& c = counters();
    c.present_entries.fetch_add(1, std::memory_order_relaxed);
    const auto now = microseconds();
    const auto prior = c.last_present_us.exchange(now, std::memory_order_relaxed);
    if (prior > 0 && now >= prior) {
        const auto gap = now - prior;
        maximum(c.max_present_gap_us, gap);
        if (gap > 16667) c.present_gaps_17ms.fetch_add(1, std::memory_order_relaxed);
        if (gap > 33333) c.present_gaps_33ms.fetch_add(1, std::memory_order_relaxed);
    }
}
inline void raw_view(int index) {
    const unsigned bit = index < 0 ? 0u : index < 4 ? static_cast<unsigned>(index + 1) : 5u;
    counters().raw_view_bits.fetch_or(1u << bit, std::memory_order_relaxed);
}
inline void main_family(unsigned views) {
    auto& c = counters();
    if (views == 1) c.main_families_1.fetch_add(1, std::memory_order_relaxed);
    else if (views == 2) c.main_families_2.fetch_add(1, std::memory_order_relaxed);
    else c.main_families_other.fetch_add(1, std::memory_order_relaxed);
}
struct Duration {
    std::atomic<std::int64_t>& target;
    std::int64_t start{microseconds()};
    ~Duration() { maximum(target, microseconds() - start); }
};
} // namespace uevr::duoview::stability
