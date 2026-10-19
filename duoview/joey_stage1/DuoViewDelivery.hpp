#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>

namespace uevr::duoview {

enum class SourceRole : uint8_t { primary, secondary, auxiliary };
enum class DeliveryEvent : uint8_t { family, render, hook, duplicate, conflict, execute, select, miss, copy, submit };
struct DeliveryTrace {
    uint64_t sequence{}, time_us{}, generation{}, serial{};
    uintptr_t command{}, target{};
    uint32_t frame{}, thread{};
    DeliveryEvent event{};
    SourceRole role{SourceRole::auxiliary};
    uint64_t draw{}, capture_generation{};
    uint32_t pose{};
};

struct DeliveryCounts {
    uint64_t produced{}, ready{}, matched{}, enqueued{}, submitted{}, duplicate_presents{}, overwritten{}, failed{}, blocked{};
};

template<class Packet, size_t Capacity = 128>
class Delivery {
public:
    struct Source {
        std::shared_ptr<const Packet> packet{};
        uint64_t generation{};
        uintptr_t target{}, scene{};
        uint32_t frame{};
        SourceRole role{SourceRole::auxiliary};
        explicit operator bool() const { return role != SourceRole::auxiliary; }
        bool same_owner(const Source& other) const {
            return generation == other.generation && packet == other.packet &&
                target == other.target && scene == other.scene && frame == other.frame && role == other.role;
        }
    };

    enum class Attachment { added, duplicate, conflict };
    struct Command {
        std::array<Source,2> sources{};
        Source original{};
        Source owner() const { return original; }
        Attachment attach(const Source& source) {
            if (!source) return Attachment::conflict;
            auto& slot=sources[static_cast<size_t>(source.role)];
            if (slot) return slot.same_owner(source) ? Attachment::duplicate : Attachment::conflict;
            const auto existing=owner();
            if (existing && (existing.packet!=source.packet || existing.generation!=source.generation ||
                existing.scene!=source.scene || existing.target==source.target)) return Attachment::conflict;
            slot=source;
            if (!original) original=source;
            return Attachment::added;
        }
    };

    bool family(Source source, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !source.packet || !advance(source.generation) || source.packet->serial<=blocked_serial_) return false;
        targets_[static_cast<size_t>(source.role)] = source.target;
        largest_registered_serial_ = (std::max)(largest_registered_serial_, source.packet->serial);
        for (auto& entry : families_) {
            if (entry && entry.generation == source.generation && entry.frame == source.frame &&
                entry.target == source.target && entry.scene == source.scene) return entry.same_owner(source);
        }
        for (auto& entry : families_) {
            if (!entry) { entry = source; if (source.role==SourceRole::primary) ++counts_.produced; trace(DeliveryEvent::family, source, 0, thread); return true; }
        }
        trace(DeliveryEvent::conflict, source, 0, thread);
        return false;
    }

    Source render(uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        for (auto& entry : families_) {
            if (entry && entry.frame == frame && entry.target == target && entry.scene == scene) {
                auto result = entry; entry = {}; trace(DeliveryEvent::render, result, 0, thread); return result;
            }
        }
        Source missing{{}, generation, target, scene, frame,
            target && target == targets_[0] ? SourceRole::primary :
            target && target == targets_[1] ? SourceRole::secondary : SourceRole::auxiliary};
        if (missing) trace(DeliveryEvent::miss, missing, 0, thread);
        return missing;
    }

    void executed(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation) || (source.packet && source.packet->serial<=blocked_serial_)) return;
        const auto& old=sources_[0].packet;
        if (old && old==sources_[1].packet && old!=source.packet && old->serial!=last_submitted_) ++counts_.overwritten;
        const auto index = static_cast<size_t>(source.role);
        sources_[index] = source;
        threads_[index] = thread;
        if (sources_[0].packet && sources_[0].packet==sources_[1].packet && source.packet->serial!=last_ready_) {
            last_ready_=source.packet->serial; ++counts_.ready;
        }
        trace(DeliveryEvent::execute, source, command, thread);
    }

    void block(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation)) return;
        ++counts_.blocked;
        blocked_serial_ = (std::max)(blocked_serial_, source.packet ? source.packet->serial : largest_registered_serial_);
        trace(DeliveryEvent::conflict, source, command, thread);
    }

    std::shared_ptr<const Packet> select(uint64_t generation, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};
        const auto& a = sources_[0]; const auto& b = sources_[1];
        if (!a.packet || a.packet != b.packet || a.packet->serial <= blocked_serial_ ||
            threads_[0] != thread || threads_[1] != thread) {
            trace(DeliveryEvent::miss, a, 0, thread); return {};
        }
        if (a.packet->serial!=last_matched_) { last_matched_=a.packet->serial; ++counts_.matched; }
        trace(DeliveryEvent::select, a, 0, thread);
        return a.packet;
    }

    void retire(uint64_t generation=0) {
        std::scoped_lock lock{mutex_};
        if (generation && generation<generation_) return;
        if (generation>generation_) advance(generation);
        blocked_serial_=(std::max)(blocked_serial_,largest_registered_serial_);
        families_={}; sources_={}; threads_={}; targets_={};
    }

    DeliveryCounts counts() const { std::scoped_lock lock{mutex_}; return counts_; }
    void reset_counts() { std::scoped_lock lock{mutex_}; counts_={}; }
    void result(DeliveryEvent event, uint64_t serial, bool success, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        if (!success || !serial) ++counts_.failed;
        else if (event==DeliveryEvent::copy && serial!=last_enqueued_) { last_enqueued_=serial; ++counts_.enqueued; }
        else if (event==DeliveryEvent::submit) {
            if (serial!=last_submitted_) { last_submitted_=serial; ++counts_.submitted; }
            else ++counts_.duplicate_presents;
        }
        Source source=sources_[0];
        if (!source.packet || source.packet->serial!=serial) source.packet.reset();
        trace(event, source, 0, thread);
        trace_[(sequence_-1)%trace_.size()].serial=serial;
    }

    void note(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_}; trace(event, source, command, thread);
    }

    std::array<DeliveryTrace, 64> recent() const {
        std::scoped_lock lock{mutex_};
        std::array<DeliveryTrace, 64> result{};
        for (size_t i=0; i<result.size(); ++i) {
            if (sequence_ > i) result[result.size()-1-i] = trace_[(sequence_-1-i)%trace_.size()];
        }
        return result;
    }

private:
    bool advance(uint64_t generation) {
        if (!generation || generation < generation_) return false;
        if (generation != generation_) {
            generation_ = generation; families_ = {}; sources_ = {}; threads_ = {}; targets_ = {};
            blocked_serial_ = 0; largest_registered_serial_ = 0;
            last_ready_=0; last_matched_=0; last_enqueued_=0; last_submitted_=0; counts_={};
        }
        return true;
    }
    void trace(DeliveryEvent event, const Source& source, uintptr_t command, uint32_t thread) {
        const auto us = std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now().time_since_epoch()).count();
        trace_[sequence_%trace_.size()] = {sequence_+1, static_cast<uint64_t>(us), source.generation,
            source.packet ? source.packet->serial : 0, command, source.target, source.frame, thread, event, source.role};
        if constexpr (requires { source.packet->duoview_frame; source.packet->duoview_mono_source_frame; source.packet->capture_generation; }) {
            auto& event_trace=trace_[sequence_%trace_.size()];
            if (source.packet) {
                event_trace.draw=source.packet->duoview_frame ? source.packet->duoview_frame->config.key.frame : 0;
                event_trace.pose=source.packet->duoview_mono_source_frame;
                event_trace.capture_generation=source.packet->capture_generation;
            }
        }
        ++sequence_;
    }
    mutable std::mutex mutex_{};
    uint64_t generation_{}, sequence_{}, blocked_serial_{}, largest_registered_serial_{};
    uint64_t last_ready_{}, last_matched_{}, last_enqueued_{}, last_submitted_{};
    DeliveryCounts counts_{};
    std::array<Source, Capacity> families_{};
    std::array<Source, 2> sources_{};
    std::array<uintptr_t, 2> targets_{};
    std::array<uint32_t, 2> threads_{};
    std::array<DeliveryTrace, 8192> trace_{};
};

template<class ReadNext>
std::optional<uintptr_t> command_tail(uintptr_t root, ReadNext&& read_next) {
    constexpr size_t maximum_commands = 65536;
    auto current = root;
    for (size_t i=0; current && i<maximum_commands; ++i) {
        const auto next = read_next(current);
        if (!next) return {};
        if (!*next) return current;
        current = *next;
    }
    return {};
}

} // namespace uevr::duoview
