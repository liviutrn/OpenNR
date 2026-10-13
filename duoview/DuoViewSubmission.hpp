#pragma once
// Cross-thread OpenXR submission mailbox.
// Producer: Joey D3D12 frame hook after compositing was queued.
// Consumer: xrEndFrame, keyed by the exact predicted display time from xrLocateViews.
// No implicit same-thread requirement; no stale "last submitted" packet fallback.
#include <cstddef>
#include <cstdint>
#include <map>
#include <mutex>
#include <optional>
#include <utility>

namespace uevr::duoview {
template<class T, std::size_t Capacity = 8>
class SubmissionMailbox {
    static_assert(Capacity > 0);
public:
    bool publish(std::int64_t display_time, std::uint64_t generation,
                 std::uint64_t frame, T packet) {
        if (display_time <= 0 || generation == 0 || frame == 0) return false;
        std::scoped_lock lock(mutex_);
        const auto [it, inserted] =
            entries_.try_emplace(display_time, Entry{generation, frame, std::move(packet)});
        if (!inserted) return false; // never silently replace a different producer
        while (entries_.size() > Capacity) entries_.erase(entries_.begin());
        return entries_.find(display_time) != entries_.end();
    }

    std::optional<T> take(std::int64_t display_time, std::uint64_t generation) {
        if (display_time <= 0 || generation == 0) return {};
        std::scoped_lock lock(mutex_);
        auto it = entries_.find(display_time);
        if (it == entries_.end()) return {};
        if (it->second.generation != generation) {
            entries_.erase(it);
            return {};
        }
        auto result = std::move(it->second.packet);
        entries_.erase(it); // exactly once, including multiple projection layers
        return result;
    }

    void retire() {
        std::scoped_lock lock(mutex_);
        entries_.clear();
    }

    std::size_t pending() const {
        std::scoped_lock lock(mutex_);
        return entries_.size();
    }
private:
    struct Entry { std::uint64_t generation, frame; T packet; };
    mutable std::mutex mutex_;
    std::map<std::int64_t, Entry> entries_;
};
} // namespace uevr::duoview
