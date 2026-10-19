#include "QuadViewDelivery.hpp"
#include <atomic>
#include <condition_variable>
#include <deque>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

struct Token { uint64_t serial{}, pose_frame{}; };

int main() {
    using Ledger = uevr::quadview::Delivery<Token>;
    using Source = Ledger::Source;
    constexpr uint64_t count = 100000;
    constexpr uint32_t rhi_thread = 42;
    Ledger delivery;
    std::mutex mutex;
    std::condition_variable changed;
    std::deque<Source> pending;
    bool done = false;
    std::atomic<bool> failed{};
    std::string error;
    uint64_t consumed{};
    const auto abort = [&](const std::string& message) {
        {
            std::scoped_lock lock{mutex};
            if (error.empty()) error = message;
            failed.store(true);
        }
        changed.notify_all();
    };
    std::thread producer([&] {
        try {
            for (uint64_t serial = 1; serial <= count; ++serial) {
                {
                    std::unique_lock lock{mutex};
                    changed.wait(lock, [&] { return pending.size() < 4 || failed.load(); });
                    if (failed.load()) return;
                }
                Source source{};
                source.packet = std::make_shared<const Token>(Token{serial, serial % 3});
                source.generation = 1;
                source.serial = serial;
                source.engine_frame = static_cast<uint32_t>(0xfffffff0ull + serial);
                source.pose_frame_token = serial % 3;
                source.family = 0x300 + 16 * static_cast<uintptr_t>(serial % 4);
                source.target = 0x1000;
                source.scene = 0x2000;
                if (!delivery.family(source)) throw std::runtime_error("Producer registration lost a queued family");
                {
                    std::scoped_lock lock{mutex};
                    pending.push_back(std::move(source));
                }
                changed.notify_all();
            }
            {
                std::scoped_lock lock{mutex};
                done = true;
            }
            changed.notify_all();
        } catch (const std::exception& exception) { abort(exception.what()); }
    });
    std::thread rhi([&] {
        try {
            std::deque<Source> in_flight;
            for (;;) {
                Source source;
                {
                    std::unique_lock lock{mutex};
                    changed.wait(lock, [&] { return !pending.empty() || done || failed.load(); });
                    if (failed.load()) return;
                    if (pending.empty()) break;
                    source = std::move(pending.front());
                    pending.pop_front();
                }
                changed.notify_all();
                const auto render = delivery.render(source.generation, source.engine_frame,
                    source.family + 0x800, source.target, source.scene); // Renderer owns a distinct family copy.
                if (!render || !render->same_owner(source)) throw std::runtime_error("Render-ahead replaced an unexecuted owner");
                const auto command = 0x9000 + static_cast<uintptr_t>(source.serial % 8);
                if (!delivery.tail_hooked(source, command) || !delivery.executed(source, command, rhi_thread))
                    throw std::runtime_error("RHI command lost its producer owner");
                if (delivery.select(1, rhi_thread + 1)) throw std::runtime_error("Wrong thread selected the atlas");
                const unsigned attempts = source.serial % 7 == 0 ? 3 : 1;
                for (unsigned attempt = 0; attempt < attempts; ++attempt) {
                    const auto selected = delivery.select(1, rhi_thread);
                    if (!selected || !selected->same_owner(source) || selected->packet->serial != source.serial ||
                        selected->packet->pose_frame != source.pose_frame_token)
                        throw std::runtime_error("Queued game frames invalidated the currently executed atlas/pose");
                    if (delivery.submitted(source, 0)) throw std::runtime_error("Unavailable XR output consumed the source");
                }
                if (!delivery.submitted(source, 0x8000 + source.serial % 3)) throw std::runtime_error("Accepted output lost source ownership");
                if (delivery.select(1, rhi_thread)) throw std::runtime_error("Duplicate Present consumed a second source");
                in_flight.push_back(std::move(source));
                if (in_flight.size() > 3) {
                    if (!delivery.retire(in_flight.front().generation, in_flight.front().serial))
                        throw std::runtime_error("Submitted owner disappeared before slot retirement");
                    in_flight.pop_front();
                }
                ++consumed;
            }
            for (const auto& source : in_flight) {
                if (!delivery.retire(source.generation, source.serial)) throw std::runtime_error("Final source retirement failed");
            }
        } catch (const std::exception& exception) { abort(exception.what()); }
    });
    producer.join();
    rhi.join();
    if (failed.load() || consumed != count) {
        std::cerr << "Asynchronous QuadView delivery failed at " << consumed << ": " << error << '\n';
        return 1;
    }
    std::cout << "100000 asynchronous QuadView transactions passed with producer lead, frame wrap, reused identifiers and XR retries.\n";
}
