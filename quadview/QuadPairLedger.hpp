#pragma once
// Portable, fail-closed QuadView transaction contract.
// No Unreal allocation, API hooking, GPU execution or XR presentation here.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::quadview {
enum class Eye : uint8_t { Left, Right };
enum class Role : uint8_t { Fovea, Periphery };
enum class Phase : uint8_t { LeftPair, RightPair };
enum class SubmitBackend : uint8_t { OpenXR, OpenVR };
struct Key { uint64_t generation{},simulation_tick{},xr_frame{},serial{}; bool operator==(const Key&) const = default; };
struct Pose {
    std::array<double,3> position{};
    std::array<double,4> orientation{0.,0.,0.,1.};
    bool operator==(const Pose&) const = default;
};
struct Frustum {
    double left{},right{},top{},bottom{};
    bool valid() const {
        return std::isfinite(left)&&std::isfinite(right)&&std::isfinite(top)&&std::isfinite(bottom)
            && left<right && bottom<top;
    }
    bool operator==(const Frustum&) const = default;
};
struct Crop { double u0{},v0{},u1{},v1{}; };
inline std::optional<Crop> centered_crop(double w,double h,double center_v) {
    if(!std::isfinite(w)||!std::isfinite(h)||!std::isfinite(center_v)||
       w<.05||w>1.||h<.05||h>1.||center_v<0.||center_v>1.)return {};
    const double cy=std::clamp(center_v,h/2.,1.-h/2.);
    return Crop{.5-w/2.,cy-h/2.,.5+w/2.,cy+h/2.};
}
inline std::optional<Frustum> fovea_frustum(Frustum full,Crop c) {
    if(!full.valid()||!(c.u0>=0.&&c.v0>=0.&&c.u1<=1.&&c.v1<=1.&&c.u0<c.u1&&c.v0<c.v1))return {};
    const double dx=full.right-full.left,dy=full.top-full.bottom;
    return Frustum{full.left+dx*c.u0,full.left+dx*c.u1,full.top-dy*c.v0,full.top-dy*c.v1};
}
inline bool finite_pose(const Pose& p) {
    for(double n:p.position)if(!std::isfinite(n))return false;
    double qnorm=0.;
    for(double n:p.orientation){if(!std::isfinite(n))return false;qnorm+=n*n;}
    return std::abs(qnorm-1.)<.02;
}
struct EyePlan { Pose pose; Frustum full; };
struct Plan {
    Key key{};
    std::array<EyePlan,2> eyes{};
    Crop crop{};
    uint32_t full_width{},full_height{};
    uint32_t fovea_width{},fovea_height{},peripheral_width{},peripheral_height{};
};
inline bool valid_plan(const Plan& p) {
    if(p.key.generation==0||p.key.serial==0||p.full_width==0||p.full_height==0||
       p.full_width>8192||p.full_height>8192||
       p.fovea_width==0||p.fovea_height==0||p.peripheral_width==0||p.peripheral_height==0||
       p.fovea_width>8192||p.fovea_height>8192||p.peripheral_width>8192||p.peripheral_height>8192||
       !p.eyes[0].full.valid()||!p.eyes[1].full.valid()||
       !finite_pose(p.eyes[0].pose)||!finite_pose(p.eyes[1].pose)||
       p.eyes[0].pose==p.eyes[1].pose||!fovea_frustum(p.eyes[0].full,p.crop)||
       !fovea_frustum(p.eyes[1].full,p.crop))return false;
    return true;
}
struct Source {
    Key key{};
    Eye eye{};
    Role role{};
    // Opaque evidence IDs only, never owned engine pointers.
    uint64_t family_id{},scene_id{},view_state_id{},target_id{},capture_generation{};
    Pose pose{};
    Frustum projection{};
    uint32_t width{},height{};
    bool native_fix_singleton_complete{};
    bool independent_history_validated{};
    bool gpu_producer_complete{};
};
class Ledger {
public:
    bool begin(Plan p) {
        if(!valid_plan(p))return false;
        if(active_&&!done_&&!failed_)return false;
        plan_=p;active_=true;failed_=false;done_=false;draws_={};sources_={};
        family_={};scene_={};submission_started_=false;left_submit_=false;
        return true;
    }
    bool draw(Phase phase,uint64_t family_id,uint64_t scene_id,uint64_t tick,uint64_t xr_frame) {
        if(!active_||failed_||done_||family_id==0||scene_id==0||
           tick!=plan_.key.simulation_tick||xr_frame!=plan_.key.xr_frame)return reject();
        auto e=phase==Phase::LeftPair?0:1;
        if(draws_[e]||(e==1&&!draws_[0])||
           (e==1&&(family_id==family_[0]||scene_id!=scene_[0])))return reject();
        draws_[e]=true;family_[e]=family_id;scene_[e]=scene_id;return true;
    }
    bool record(Source s) {
        if(!active_||failed_||done_||submission_started_||s.key!=plan_.key)return reject();
        auto e=s.eye==Eye::Left?0:1,r=s.role==Role::Fovea?0:1,idx=e*2+r;
        const auto& target=plan_.eyes[e];
        auto expected=r==0?fovea_frustum(target.full,plan_.crop):std::optional<Frustum>{target.full};
        uint32_t w=r==0?plan_.fovea_width:plan_.peripheral_width;
        uint32_t h=r==0?plan_.fovea_height:plan_.peripheral_height;
        if(!draws_[e]||sources_[idx]||s.family_id!=family_[e]||s.scene_id!=scene_[e]||
           s.view_state_id==0||s.target_id==0||s.capture_generation==0||
           s.pose!=target.pose||!expected||s.projection!=*expected||s.width!=w||s.height!=h||
           !s.native_fix_singleton_complete||!s.independent_history_validated||
           !s.gpu_producer_complete)return reject();
        for(auto& previous:sources_)
            if(previous&&(previous->view_state_id==s.view_state_id||previous->target_id==s.target_id))return reject();
        sources_[idx]=s;return true;
    }
    bool begin_submit(SubmitBackend backend) {
        if(!active_||failed_||done_||submission_started_||!draws_[0]||!draws_[1])return false;
        for(const auto& s:sources_)if(!s)return false;
        backend_=backend;submission_started_=true;return true;
    }
    // Only AFTER actual runtime acknowledgment. Never infer from GPU enqueue.
    bool acknowledge_openvr(Eye eye,bool accepted) {
        if(!submission_started_||backend_!=SubmitBackend::OpenVR||failed_||done_||!accepted)return reject();
        if(eye==Eye::Left){if(left_submit_)return reject();left_submit_=true;return true;}
        if(!left_submit_)return reject();
        done_=true;return true;
    }
    bool acknowledge_openxr(bool endframe_accepted,unsigned submitted_projection_views) {
        if(!submission_started_||backend_!=SubmitBackend::OpenXR||failed_||done_||
           !endframe_accepted||submitted_projection_views!=2)return reject();
        done_=true;return true;
    }
    bool presented()const{return active_&&done_&&!failed_;}
    bool failed()const{return failed_;}
    void reset(){
        active_=false;failed_=false;done_=false;draws_={};sources_={};
        family_={};scene_={};submission_started_=false;left_submit_=false;
    }
private:
    bool reject(){if(active_)failed_=true;return false;}
    Plan plan_{};
    std::array<bool,2> draws_{};
    std::array<uint64_t,2> family_{},scene_{};
    std::array<std::optional<Source>,4> sources_{};
    SubmitBackend backend_{};
    bool active_{},failed_{},done_{},submission_started_{},left_submit_{};
};
} // namespace uevr::quadview
