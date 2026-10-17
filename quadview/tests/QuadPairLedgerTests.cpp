#include "../QuadPairLedger.hpp"
#ifdef NDEBUG
#undef NDEBUG // Contract assertions must still run in Release CI.
#endif
#include <cassert>
#include <iostream>
#include <limits>
using namespace uevr::quadview;
static Plan plan(){
    Plan p;
    p.key={2,100,50,1};p.crop=*centered_crop(.5,.5,.5);
    p.full_width=p.full_height=3000;p.fovea_width=p.fovea_height=1500;
    p.peripheral_width=p.peripheral_height=900;
    p.eyes[0].full={-1.841771,.947191,1.328981,-1.328981};
    p.eyes[1].full={-.947191,1.841771,1.328981,-1.328981};
    p.eyes[0].pose.position={-.032,0,0};p.eyes[1].pose.position={.032,0,0};
    return p;
}
static Source source(Plan p,Eye eye,Role role){
    const int e=eye==Eye::Left?0:1,r=role==Role::Fovea?0:1;
    Source s;s.key=p.key;s.eye=eye;s.role=role;s.family_id=10+e;s.scene_id=100;
    s.view_state_id=40+e*2+r;s.target_id=50+e*2+r;s.capture_generation=1;
    s.pose=p.eyes[e].pose;
    s.projection=r==0?*fovea_frustum(p.eyes[e].full,p.crop):p.eyes[e].full;
    s.width=r==0?p.fovea_width:p.peripheral_width;
    s.height=r==0?p.fovea_height:p.peripheral_height;
    s.native_fix_singleton_complete=s.independent_history_validated=s.gpu_producer_complete=true;
    return s;
}
static void start(Ledger& l,const Plan& p){
    assert(l.begin(p));
    assert(l.draw(Phase::LeftPair,10,100,100,50));
    assert(l.draw(Phase::RightPair,11,100,100,50));
}
static void populate(Ledger& l,const Plan& p){
    for(Eye e:{Eye::Left,Eye::Right})
        for(Role r:{Role::Fovea,Role::Periphery})assert(l.record(source(p,e,r)));
}
int main(){
    const auto p=plan();assert(valid_plan(p));
    assert(fovea_frustum(p.eyes[0].full,p.crop)!=fovea_frustum(p.eyes[1].full,p.crop));
    assert(!centered_crop(.5,.5,std::numeric_limits<double>::quiet_NaN()));
    auto up=centered_crop(.5,.5,0);assert(up&&up->v0==0&&up->v1==.5);
    Ledger l;start(l,p);populate(l,p);
    assert(l.begin_submit(SubmitBackend::OpenXR));assert(!l.presented());
    assert(l.acknowledge_openxr(true,2));assert(l.presented());
    l.reset();start(l,p);populate(l,p);assert(l.begin_submit(SubmitBackend::OpenVR));
    assert(l.acknowledge_openvr(Eye::Left,true));assert(!l.presented());
    assert(l.acknowledge_openvr(Eye::Right,true));assert(l.presented());
    l.reset();start(l,p);
    auto wrong=source(p,Eye::Right,Role::Fovea);wrong.pose=p.eyes[0].pose;
    assert(!l.record(wrong)&&l.failed());
    l.reset();start(l,p);assert(l.record(source(p,Eye::Left,Role::Fovea)));
    auto alias=source(p,Eye::Left,Role::Periphery);alias.view_state_id=40;
    assert(!l.record(alias)&&l.failed());
    l.reset();start(l,p);assert(l.record(source(p,Eye::Left,Role::Fovea)));
    auto duplicate_target=source(p,Eye::Left,Role::Periphery);duplicate_target.target_id=50;
    assert(!l.record(duplicate_target)&&l.failed());
    l.reset();start(l,p);auto dim=source(p,Eye::Left,Role::Fovea);dim.width=1499;
    assert(!l.record(dim)&&l.failed());
    l.reset();start(l,p);
    auto missing_fix=source(p,Eye::Left,Role::Periphery);missing_fix.native_fix_singleton_complete=false;
    assert(!l.record(missing_fix)&&l.failed());
    l.reset();assert(l.begin(p));assert(l.draw(Phase::LeftPair,10,100,100,50));
    assert(!l.draw(Phase::RightPair,10,100,100,50)&&l.failed());
    l.reset();assert(l.begin(p));assert(!l.draw(Phase::RightPair,11,100,100,50)&&l.failed());
    l.reset();start(l,p);assert(!l.begin_submit(SubmitBackend::OpenXR));
    l.reset();start(l,p);populate(l,p);assert(l.begin_submit(SubmitBackend::OpenXR));
    assert(!l.acknowledge_openxr(true,4)&&l.failed());
    l.reset();start(l,p);populate(l,p);assert(l.begin_submit(SubmitBackend::OpenVR));
    assert(!l.acknowledge_openvr(Eye::Right,true)&&l.failed());
    l.reset();start(l,p);populate(l,p);assert(l.begin_submit(SubmitBackend::OpenVR));
    assert(!l.acknowledge_openvr(Eye::Left,false)&&l.failed());
    l.reset();start(l,p);auto stale=source(p,Eye::Left,Role::Fovea);stale.key.serial--;
    assert(!l.record(stale)&&!l.presented());
    l.reset();start(l,p);populate(l,p);assert(!l.presented());
    std::cout<<"QuadPair four-source, independent histories, geometry and XR ACK contracts passed\n";
}
