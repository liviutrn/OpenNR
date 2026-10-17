#include "../NativePairHistoryOwner.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <array>
#include <iostream>
#include <thread>
using namespace uevr::quadview;

struct EngineFixture {
    std::array<uint64_t,4> live{501,502,503,504};
    unsigned allocated{}, destroyed{};
    bool fail_third{}, duplicate_last{};
    VerifiedEngineHistoryApi callbacks() {
        return {
            [this](Eye eye, Role role, uint32_t feature) -> std::optional<EngineState> {
                assert(feature == 55);
                const unsigned index = (eye == Eye::Right ? 2u : 0u) +
                                       (role == Role::Periphery ? 1u : 0u);
                if (fail_third && index == 2) return {};
                ++allocated;
                return EngineState{100, 201 + index,
                    live[duplicate_last && index == 3 ? 2 : index],400,9};
            },
            [this](uint64_t owner, uint64_t slot)->std::optional<uint64_t> {
                if (owner != 100 || slot < 201 || slot > 204) return {};
                return live[slot - 201];
            },
            [this](const EngineState& h) {
                if (h.owner != 100 || h.reference_slot < 201 ||
                    h.reference_slot > 204) return false;
                ++destroyed; return true;
            }
        };
    }
};
int main() {
    EngineFixture fixture;
    NativePairHistoryOwner owner;
    assert(owner.allocate(400,9,1,55,fixture.callbacks()));
    assert(owner.state() == NativePairHistoryOwner::State::Ready);
    assert(fixture.allocated == 4);
    assert(owner.get(Eye::Right,Role::Periphery)->scene_state == 504);
    assert(owner.verify_frame(Key{1,1,10,1}));
    assert(owner.verify_frame(Key{1,2,11,2}));
    bool cross_thread_accepted = true;
    std::thread worker([&]{ cross_thread_accepted = owner.get(Eye::Left,Role::Fovea).has_value(); });
    worker.join();
    assert(!cross_thread_accepted);
    assert(owner.mark_composite_submitted(7,100));
    assert(!owner.retire_frame(7,99)); // GPU consumer fence not completed
    assert(!owner.retire_frame(8,100)); // unrelated GPU queue
    assert(!owner.destroy_after_retirement(7,100)); // no explicit teardown
    assert(fixture.destroyed == 0);
    assert(owner.retire_frame(7,100));
    assert(fixture.destroyed == 0); // four Lumen histories persist
    assert(owner.verify_frame(Key{1,3,12,3}));
    assert(owner.get(Eye::Right,Role::Periphery)->scene_state == 504);
    assert(owner.mark_composite_submitted(7,101));
    assert(owner.request_teardown());
    assert(!owner.retire_frame(7,101)); // teardown cannot resume normal render
    assert(!owner.destroy_after_retirement(7,100));
    assert(owner.destroy_after_retirement(7,101));
    assert(fixture.destroyed == 4);
    assert(owner.state() == NativePairHistoryOwner::State::Empty);
    assert(!owner.allocate(400,9,1,55,fixture.callbacks()));
    assert(owner.allocate(400,9,2,55,fixture.callbacks()));
    assert(owner.abandon_unsubmitted());
    assert(fixture.destroyed == 8);

    EngineFixture alloc_failure;
    alloc_failure.fail_third = true;
    NativePairHistoryOwner rollback;
    assert(!rollback.allocate(400,9,1,55,alloc_failure.callbacks()));
    assert(alloc_failure.allocated == 2 && alloc_failure.destroyed == 2);
    assert(rollback.state() == NativePairHistoryOwner::State::Empty);

    EngineFixture aliased;
    aliased.duplicate_last = true;
    NativePairHistoryOwner quarantine;
    assert(!quarantine.allocate(400,9,1,55,aliased.callbacks()));
    assert(quarantine.state() == NativePairHistoryOwner::State::Quarantined);
    assert(aliased.destroyed == 0);

    EngineFixture stale;
    NativePairHistoryOwner drift;
    assert(drift.allocate(400,9,1,55,stale.callbacks()));
    assert(drift.verify_frame(Key{1,1,10,1}));
    stale.live[2] = 999;
    assert(!drift.verify_frame(Key{1,2,11,2}));
    assert(drift.state() == NativePairHistoryOwner::State::Quarantined);
    assert(stale.destroyed == 0);

    EngineFixture wrong_clock;
    NativePairHistoryOwner monotonic;
    assert(monotonic.allocate(400,9,1,55,wrong_clock.callbacks()));
    assert(monotonic.verify_frame(Key{1,1,10,1}));
    assert(!monotonic.verify_frame(Key{1,1,11,2}));
    assert(monotonic.state() == NativePairHistoryOwner::State::Quarantined);
    std::cout << "Four engine-owned state callback contract, thread, epoch, fences OK\\n";
}
