#include "../DuoViewRestartDiagnostics.hpp"

#include <cmath>
#include <thread>

using namespace uevr::duoview_restart;

namespace {
int fail(int line) { return line; }
#define CHECK(condition) do { if (!(condition)) { return fail(__LINE__); } } while (false)
}

int main() {
    const auto fixed = replay_mask(ReplayPattern::fixed, 300, 60);
    CHECK(fixed && fixed->center_u == 0.5f && fixed->center_v == 0.5f);

    const auto step_a = replay_mask(ReplayPattern::step, 0, 10);
    const auto step_b = replay_mask(ReplayPattern::step, 10, 10);
    CHECK(step_a && step_b && step_a->center_u == 0.32f && step_b->center_u == 0.68f);
    CHECK(step_a->center_u == replay_mask(ReplayPattern::step, 0, 10)->center_u);

    const auto ramp_start = replay_mask(ReplayPattern::ramp, 0, 10);
    const auto ramp_mid = replay_mask(ReplayPattern::ramp, 10, 10);
    const auto ramp_end = replay_mask(ReplayPattern::ramp, 20, 10);
    CHECK(ramp_start && ramp_mid && ramp_end);
    CHECK(ramp_start->center_u == 0.25f && ramp_mid->center_u == 0.75f && ramp_end->center_u == 0.25f);

    const auto alternate = replay_mask(ReplayPattern::alternating, 30, 10);
    CHECK(alternate && alternate->center_u == 0.32f && alternate->center_v == 0.68f);
    CHECK(!replay_mask(ReplayPattern::step, 0, 0));
    CHECK(!replay_mask(ReplayPattern::fixed, 0, 60, NAN));
    CHECK(!replay_mask(static_cast<ReplayPattern>(255), 0, 60));

    // Width 200 has only source x=[0, 100) as its valid Mono image.
    const auto left_edge = left_eye_source_uv(200, 100, 0.f, 0.5f);
    const auto right_edge = left_eye_source_uv(200, 100, 1.f, 0.5f);
    CHECK(left_edge && right_edge);
    CHECK(left_edge->u == 0.5f / 200.f);
    CHECK(right_edge->u == 99.5f / 200.f);
    CHECK(right_edge->u < 0.5f);
    CHECK(!left_eye_source_uv(201, 100, 0.5f, 0.5f));
    CHECK(!left_eye_source_uv(200, 100, 1.1f, 0.5f));

    ObservationRing<4> ring;
    FrameObservation item{};
    FrameObservation output{};
    item.producer_frame = 47;
    item.observed_path = EffectivePath::mono_copy;
    CHECK(ring.try_push(item));
    for (uint64_t frame = 1; frame <= 2; ++frame) {
        item.producer_frame = frame;
        CHECK(ring.try_push(item));
    }
    item.producer_frame = 3;
    CHECK(!ring.try_push(item));
    CHECK(ring.dropped() == 1);
    CHECK(ring.try_pop(output) && output.producer_frame == 47);
    CHECK(ring.try_pop(output) && output.producer_frame == 1);
    item.producer_frame = 3;
    CHECK(ring.try_push(item));
    item.producer_frame = 4;
    CHECK(ring.try_push(item));
    item.producer_frame = 5;
    CHECK(!ring.try_push(item));
    CHECK(ring.try_pop(output) && output.producer_frame == 2);
    CHECK(ring.try_pop(output) && output.producer_frame == 3);
    CHECK(ring.try_pop(output) && output.producer_frame == 4);
    CHECK(!ring.try_pop(output));

    CHECK(copy_accepted_path(true, true, false) == EffectivePath::stable_source_mask);
    CHECK(copy_accepted_path(true, false, true) == EffectivePath::mono_copy);
    CHECK(copy_accepted_path(false, true, true) == EffectivePath::unknown);
    CHECK(copy_accepted_path(true, false, false) == EffectivePath::unknown);

    ObservationRing<64> concurrent;
    constexpr uint64_t count = 100000;
    std::atomic<bool> producer_done{};
    std::atomic<bool> ordered{true};
    std::thread producer([&] {
        FrameObservation record{};
        for (uint64_t frame = 1; frame <= count; ++frame) {
            record.producer_frame = frame;
            while (!concurrent.try_push(record)) { std::this_thread::yield(); }
        }
        producer_done.store(true, std::memory_order_release);
    });
    std::thread consumer([&] {
        uint64_t expected = 1;
        FrameObservation record{};
        while (expected <= count) {
            if (!concurrent.try_pop(record)) { std::this_thread::yield(); continue; }
            if (record.producer_frame != expected++) { ordered.store(false, std::memory_order_relaxed); }
        }
    });
    producer.join();
    consumer.join();
    CHECK(ordered.load(std::memory_order_relaxed));
    CHECK(producer_done.load(std::memory_order_acquire));
    return 0;
}
