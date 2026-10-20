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
    // Regression: the outer producer sees the pre-engine 0xffffffff frame.
    // The GT extension callback binds each exact draw serial to the assigned
    // frame before UE copies its FSceneViewFamily/FSceneView objects. Persistent
    // scene states and even reused view addresses therefore cannot alias frames.
    {
        Ledger strict;
        Source first{};
        first.packet = std::make_shared<const Token>(Token{1, 7});
        first.generation = 1; first.serial = 1; first.engine_frame = 0xffffffffu;
        first.pose_frame_token = 7; first.family = 0x3000;
        first.target = 0x4000; first.scene = 0x5000;
        first.view_ids = {0x1010, 0x2020, 0x3030, 0x4040};
        Source second = first;
        second.packet = std::make_shared<const Token>(Token{2, 8});
        second.serial = 2; second.pose_frame_token = 8;
        if (!strict.family(first)) throw std::runtime_error("Exact-view registration failed");
        if (!strict.family(second)) throw std::runtime_error("Second queued draw registration failed");
        if (strict.render(1, 0xffffffffu, 0x3800, first.target, first.scene))
            throw std::runtime_error("Pre-engine sentinel was treated as an assigned frame");
        if (strict.bind_engine_frame(1, first.serial, first.family + 1, first.target, first.scene,
                first.view_ids, 100))
            throw std::runtime_error("Wrong original family was allowed to bind");
        if (strict.bind_engine_frame(1, first.serial, first.family, first.target, first.scene,
                {0x1010, 0x2020, 0x3030, 0x5050}, 100))
            throw std::runtime_error("Wrong ordered game-thread view IDs were allowed to bind");
        const auto second_bound = strict.bind_engine_frame(1, second.serial, second.family,
            second.target, second.scene, second.view_ids, 102);
        const auto first_bound = strict.bind_engine_frame(1, first.serial, first.family,
            first.target, first.scene, first.view_ids, 101);
        if (!second_bound || !first_bound || !second_bound->engine_frame_bound || !first_bound->engine_frame_bound)
            throw std::runtime_error("Assigned engine frame did not bind to both queued owners");
        if (strict.bind_engine_frame(1, first.serial, first.family, first.target, first.scene,
                first.view_ids, 101))
            throw std::runtime_error("Duplicate BeginRenderViewFamily binding was accepted");
        Source conflicting = first;
        conflicting.serial = 3;
        conflicting.packet = std::make_shared<const Token>(Token{3, 9});
        if (!strict.family(conflicting)) throw std::runtime_error("Conflicting draw registration failed unexpectedly");
        if (strict.bind_engine_frame(1, conflicting.serial, conflicting.family, conflicting.target,
                conflicting.scene, conflicting.view_ids, 101))
            throw std::runtime_error("Ambiguous frame/target/scene tuple acquired a second owner");

        const auto matched_second = strict.render(1, 102, 0x3900, second.target, second.scene);
        if (!matched_second || !matched_second->same_owner(*second_bound))
            throw std::runtime_error("Renderer-owned family copy did not match its frame-bound source");
        if (strict.render(1, 101, 0x3901, first.target + 1, first.scene))
            throw std::runtime_error("Wrong target matched a bound source");
        if (strict.render(1, 101, 0x3901, first.target, first.scene + 1))
            throw std::runtime_error("Wrong scene matched a bound source");
        const auto matched_first = strict.render(1, 101, 0x3901, first.target, first.scene);
        if (!matched_first || !matched_first->same_owner(*first_bound))
            throw std::runtime_error("Out-of-order render callback was paired with the wrong draw");
        if (strict.render(1, 101, 0x3901, first.target, first.scene))
            throw std::runtime_error("Duplicate render-family callback was accepted");

        Source invalid_advance_guard = first;
        invalid_advance_guard.serial = 4;
        invalid_advance_guard.packet = std::make_shared<const Token>(Token{4, 10});
        if (!strict.family(invalid_advance_guard)) throw std::runtime_error("Additional queued owner registration failed");
        const auto guard_bound = strict.bind_engine_frame(1, invalid_advance_guard.serial,
            invalid_advance_guard.family, invalid_advance_guard.target, invalid_advance_guard.scene,
            invalid_advance_guard.view_ids, 103);
        if (!guard_bound) throw std::runtime_error("Additional queued owner did not bind");
        if (strict.bind_engine_frame(2, 5, 0x6000, 0x4000, 0x5000, first.view_ids, 0xffffffffu))
            throw std::runtime_error("Unassigned sentinel was bound as a render frame");
        const auto guard_render = strict.render(1, 103, 0x3902, first.target, first.scene);
        if (!guard_render || !guard_render->same_owner(*guard_bound))
            throw std::runtime_error("Rejected invalid binding advanced and cleared the active generation");

        Source restarted = first;
        restarted.generation = 2; restarted.serial = 1;
        restarted.packet = std::make_shared<const Token>(Token{4, 10});
        if (!strict.family(restarted)) throw std::runtime_error("New generation registration failed");
        const auto restarted_bound = strict.bind_engine_frame(2, restarted.serial, restarted.family,
            restarted.target, restarted.scene, restarted.view_ids, 1);
        if (!restarted_bound || strict.render(1, 101, first.family, first.target, first.scene) ||
            !strict.render(2, 1, restarted.family + 0x800, restarted.target, restarted.scene))
            throw std::runtime_error("Generation restart retained a stale frame owner");
    }
    {
        Ledger gt_before_outer;
        Source source{};
        source.packet=std::make_shared<const Token>(Token{1,3});
        source.generation=2; source.serial=1; source.engine_frame=0xffffffffu;
        source.pose_frame_token=3;source.family=0x501;source.target=0x601;source.scene=0x701;
        source.view_ids={0x101,0x102,0x103,0x104};
        if (!gt_before_outer.observe_gt_frame(source.generation,source.serial,source.family,source.target,
            source.scene,source.view_ids,777)) throw std::runtime_error("GT pre-render ticket rejected");
        const auto frame=gt_before_outer.take_observed_gt_frame(source.generation,source.serial,source.family,
            source.target,source.scene,source.view_ids);
        if(!frame || *frame!=777 || gt_before_outer.take_observed_gt_frame(source.generation,source.serial,
            source.family,source.target,source.scene,source.view_ids))
            throw std::runtime_error("One-time GT frame ticket invalid");
        if(!gt_before_outer.family(source)) throw std::runtime_error("Late outer-producer registration rejected");
        const auto bound=gt_before_outer.bind_engine_frame(source.generation,source.serial,
            source.family,source.target,source.scene,source.view_ids,*frame);
        if(!bound || !gt_before_outer.render(source.generation,*frame,0x999,source.target,source.scene))
            throw std::runtime_error("Late producer could not use preceding GT assigned frame");
    }
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
                source.engine_frame = 0xffffffffu; // Outer producer has not seen the assigned FrameNumber yet.
                source.pose_frame_token = serial % 3;
                source.family = 0x300 + 16 * static_cast<uintptr_t>(serial % 4);
                source.target = 0x1000;
                source.scene = 0x2000;
                source.view_ids = {0x1010, 0x2020, 0x3030, 0x4040}; // Unreal may reuse these allocations and histories.
                if (!delivery.family(source)) throw std::runtime_error("Producer registration lost a queued family");
                const auto engine_frame = static_cast<uint32_t>(0xffffffffull + source.serial); // Exercise rollover to frame zero.
                const auto bound = delivery.bind_engine_frame(source.generation, source.serial, source.family,
                    source.target, source.scene, source.view_ids, engine_frame);
                if (!bound) throw std::runtime_error("BeginRenderViewFamily failed to bind the queued source");
                source = *bound;
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
