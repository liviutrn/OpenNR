#include "../QuadPairCoordinator.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>
#include <thread>
using namespace uevr::quadview;
static Plan plan(uint64_t n=1,uint64_t gen=1) {
    Plan p{};p.key={gen,n,n,n};p.crop=*centered_crop(.5,.5,.5);
    p.full_width=p.full_height=3000;
    p.fovea_width=p.fovea_height=1500;p.peripheral_width=p.peripheral_height=900;
    p.eyes[0].full={-1.841771,.947191,1.328981,-1.328981};
    p.eyes[1].full={-.947191,1.841771,1.328981,-1.328981};
    p.eyes[0].pose.position={-.032,0,0};
    p.eyes[1].pose.position={.032,0,0};
    return p;
}
static ViewEvidence view(Plan p,int e,int r,uint64_t scene=100) {
    ViewEvidence v{};
    v.family=10+e;v.scene=scene;v.view=20+e*2+r;
    v.view_state=40+e*2+r;v.capture_target=60+e*2+r;
    v.capture_generation=1;v.role=r?Role::Periphery:Role::Fovea;
    v.physical_eye_pose=p.eyes[e].pose;
    v.projection=r?p.eyes[e].full:*fovea_frustum(p.eyes[e].full,p.crop);
    v.width=r?p.peripheral_width:p.fovea_width;
    v.height=r?p.peripheral_height:p.fovea_height;
    v.native_fix_transaction_completed=true;return v;
}
static void frame(TwoPairCoordinator& c,Plan p) {
    assert(c.begin(p,100,p.key.simulation_tick));
    for(int e=0;e<2;++e) {
        const auto phase=e?Phase::RightPair:Phase::LeftPair;
        auto t=c.enter(phase,p.key,100,p.key.simulation_tick);
        assert(t && c.physical_eye(*t)==(e?Eye::Right:Eye::Left));
        assert(c.observe(*t,view(p,e,0)));
        assert(c.observe(*t,view(p,e,1)));
        assert(c.leave(*t,p.key,100,p.key.simulation_tick));
    }
    assert(c.complete() && c.validated());
}
int main() {
    TwoPairCoordinator c;auto p=plan();
    frame(c,p);frame(c,plan(2));
    assert(!c.begin(plan(2),100,2) && c.failed());
    c.reset_epoch();frame(c,plan(1,2));
    c.reset_epoch();assert(c.begin(p,100,1));
    assert(!c.enter(Phase::RightPair,p.key,100,1) && c.failed());
    assert(!c.begin(p,100,1)); // explicitly reset after faults
    c.reset_epoch();assert(c.begin(p,100,1));
    auto t=c.enter(Phase::LeftPair,p.key,100,1);assert(t);
    assert(!c.enter(Phase::LeftPair,p.key,100,1) && c.failed());
    c.reset_epoch();assert(c.begin(p,100,1));
    t=c.enter(Phase::LeftPair,p.key,100,1);assert(t);
    assert(c.observe(*t,view(p,0,0)));
    assert(!c.leave(*t,p.key,100,2) && c.failed());
    c.reset_epoch();assert(c.begin(p,100,1));
    t=c.enter(Phase::LeftPair,p.key,100,1);assert(t);
    auto wrong=view(p,0,0);wrong.physical_eye_pose=p.eyes[1].pose;
    assert(!c.observe(*t,wrong) && c.failed());
    c.reset_epoch();assert(c.begin(p,100,1));
    t=c.enter(Phase::LeftPair,p.key,100,1);assert(t);
    assert(c.observe(*t,view(p,0,0)));
    wrong=view(p,0,1);wrong.view_state=40;
    assert(!c.observe(*t,wrong) && c.failed());
    c.reset_epoch();assert(c.begin(p,100,1));
    t=c.enter(Phase::LeftPair,p.key,100,1);assert(t);
    assert(!c.observe(*t,view(p,0,0,200)) && c.failed());
    c.reset_epoch();frame(c,p);
    auto next=plan(2);assert(c.begin(next,100,2));
    t=c.enter(Phase::LeftPair,next.key,100,2);assert(t);
    wrong=view(next,0,0);wrong.view_state=400;
    assert(!c.observe(*t,wrong) && c.failed());
    c.reset_epoch();frame(c,plan(1,2));
    c.reset_epoch();assert(c.begin(p,100,1));
    bool accepted=false;
    std::thread worker([&]{accepted=c.enter(Phase::LeftPair,p.key,100,1).has_value();});
    worker.join();assert(!accepted && c.failed());
    c.reset_epoch();frame(c,p);assert(c.validated());
    std::cout<<"QuadPair scheduler, four temporal identities and phase gates OK\n";
}
