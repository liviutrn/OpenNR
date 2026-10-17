#include "../FourHistoryLease.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <array>
#include <iostream>
using namespace uevr::quadview;
namespace {
using StateArray = std::array<uint64_t,4>;
HistoryObservation source(unsigned index,uint64_t lifecycle=1) {
    return HistoryObservation{
        100, 200+index, 300+index, 400, lifecycle,
        500+(index/2), 600+index, 1
    };
}
auto inspector(const StateArray& states) {
    return [&states](uint64_t owner,uint64_t slot)->std::optional<uint64_t>{
        if(owner!=100 || slot<200 || slot>=204)return {};
        if(states[slot-200]==0)return {};
        return states[slot-200];
    };
}
void collect(FourHistoryLease& lease,const InspectReference& inspect,uint64_t tick=1) {
    assert(lease.begin(Key{1,tick,tick,tick},400,1));
    for(unsigned i=0;i<4;++i)
        assert(lease.observe(i<2?Eye::Left:Eye::Right,
                             (i%2)?Role::Periphery:Role::Fovea,source(i),inspect));
    assert(lease.seal(inspect));
}
void submit(FourHistoryLease& lease,uint64_t queue=7) {
    for(unsigned i=0;i<4;++i)
        assert(lease.submitted_source(i<2?Eye::Left:Eye::Right,
               i%2?Role::Periphery:Role::Fovea,queue,10+i));
    assert(lease.submitted_composite(queue,14));
}
}
int main() {
    StateArray states{300,301,302,303};
    auto read=inspector(states);
    FourHistoryLease ok;
    collect(ok,read);
    assert(!ok.ready_for_next_frame());
    submit(ok);
    assert(ok.gpu_pending());
    assert(!ok.retire(8,14,read)); // wrong D3D12 queue
    assert(!ok.retire(7,13,read)); // queued is not retired
    assert(ok.retire(7,14,read));
    assert(ok.ready_for_next_frame());
    collect(ok,read,2);
    submit(ok);
    assert(ok.retire(7,14,read));
    assert(!ok.begin(Key{1,2,2,2},400,1));
    assert(ok.failed());
    assert(!ok.reset_epoch(false,2)); // cannot discard in-flight ownership
    assert(ok.reset_epoch(true,2));
    assert(ok.begin(Key{2,1,1,1},400,2)); // new owner epoch

    FourHistoryLease duplicate;
    assert(duplicate.begin(Key{1,1,1,1},400,1));
    assert(duplicate.observe(Eye::Left,Role::Fovea,source(0),read));
    auto aliased=source(1);aliased.reference_slot=200;
    assert(!duplicate.observe(Eye::Left,Role::Periphery,aliased,read));
    assert(duplicate.failed());

    FourHistoryLease stale_owner;
    assert(stale_owner.begin(Key{1,1,1,1},400,1));
    for(unsigned i=0;i<4;++i)
        assert(stale_owner.observe(i<2?Eye::Left:Eye::Right,
                  i%2?Role::Periphery:Role::Fovea,source(i),read));
    states[3]=999; // externally mutated owner between two render phases
    assert(!stale_owner.seal(read) && stale_owner.failed());
    states[3]=303;

    FourHistoryLease incomplete;
    collect(incomplete,read);
    assert(!incomplete.submitted_composite(7,14) && incomplete.failed());

    FourHistoryLease bad_queue;
    collect(bad_queue,read);
    assert(bad_queue.submitted_source(Eye::Left,Role::Fovea,7,10));
    assert(!bad_queue.submitted_source(Eye::Left,Role::Periphery,8,11));
    assert(bad_queue.failed());

    FourHistoryLease old_state;
    collect(old_state,read);
    submit(old_state);
    states[0]=999; // last reference changes while GPU is retiring
    assert(!old_state.retire(7,14,read) && old_state.failed());
    states[0]=300;

    FourHistoryLease same_history;
    collect(same_history,read);
    submit(same_history);
    assert(same_history.retire(7,14,read));
    assert(same_history.begin(Key{1,2,2,2},400,1));
    assert(same_history.observe(Eye::Left,Role::Fovea,source(0),read));
    auto drift=source(1);drift.reference_slot=201;drift.scene_state=999;
    StateArray new_states{300,999,302,303}; auto drift_read=inspector(new_states);
    assert(!same_history.observe(Eye::Left,Role::Periphery,drift,drift_read));
    assert(same_history.failed());
    std::cout<<"Engine ViewState reference, four-history separation and exact GPU fence retirement OK\n";
}
