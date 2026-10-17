#pragma once
// Portable scheduling contract. NO Unreal hooks, allocations, GPU/XR submission.
#include "QuadPairLedger.hpp"
#include <array>
#include <cstdint>
#include <optional>
#include <thread>

namespace uevr::quadview {
struct ViewEvidence {
    uint64_t family{},scene{},view{},view_state{},capture_target{},capture_generation{};
    Role role{};
    Pose physical_eye_pose{};
    Frustum projection{};
    uint32_t width{},height{};
    bool native_fix_transaction_completed{};
};
struct PhaseToken {
    Key key{};
    Phase phase{};
    uint64_t nonce{};
    bool operator==(const PhaseToken&) const = default;
};
class TwoPairCoordinator {
public:
    bool begin(Plan plan,uint64_t world_scene,uint64_t world_advance_count) {
        if((state_!=State::Idle && state_!=State::Complete) || world_scene==0 ||
           world_advance_count!=plan.key.simulation_tick || !valid_plan(plan)) return reject();
        if(has_previous_ && (plan.key.generation!=previous_generation_ ||
           world_scene!=previous_scene_ || plan.key.serial<=previous_serial_ ||
           plan.key.simulation_tick<=previous_tick_ ||
           plan.key.xr_frame<=previous_xr_frame_)) return reject();
        plan_=plan;scene_=world_scene;world_advance_=world_advance_count;
        state_=State::Ready;phase_={};observations_={};families_={};
        entered_={};closed_={};thread_=std::this_thread::get_id();++nonce_;
        return true;
    }
    // Enter exactly one original viewport Draw; copy token to immutable packets.
    std::optional<PhaseToken> enter(Phase phase,Key current,uint64_t world_scene,
                                    uint64_t world_advance_count) {
        const int e=phase==Phase::LeftPair?0:1;
        if(std::this_thread::get_id()!=thread_ || state_!=State::Ready ||
           current!=plan_.key || world_scene!=scene_ ||
           world_advance_count!=world_advance_ || entered_[e] ||
           (e==1 && !closed_[0])){reject();return {};}
        state_=State::Inside;entered_[e]=true;phase_=PhaseToken{plan_.key,phase,++nonce_};
        return phase_;
    }
    // Observe actual engine-constructed views. NEVER manufacture ViewStates.
    bool observe(PhaseToken token,ViewEvidence v) {
        if(!in_phase(token) || std::this_thread::get_id()!=thread_) return reject();
        const int e=token.phase==Phase::LeftPair?0:1;
        const int r=v.role==Role::Fovea?0:1;
        const int index=e*2+r;
        const auto& eye=plan_.eyes[e];
        const auto projection=r==0?fovea_frustum(eye.full,plan_.crop):
            std::optional<Frustum>{eye.full};
        const auto w=r==0?plan_.fovea_width:plan_.peripheral_width;
        const auto h=r==0?plan_.fovea_height:plan_.peripheral_height;
        if(observations_[index] || !v.family || v.scene!=scene_ || !v.view ||
           !v.view_state || !v.capture_target || !v.capture_generation ||
           v.width!=w || v.height!=h || v.physical_eye_pose!=eye.pose ||
           !projection || !near_frustum(v.projection,*projection) ||
           !v.native_fix_transaction_completed) return reject();
        if(!families_[e]) families_[e]=v.family;
        else if(families_[e]!=v.family) return reject();
        for(const auto& old:observations_) if(old && (old->view==v.view ||
            old->view_state==v.view_state || old->capture_target==v.capture_target))
            return reject();
        if(has_previous_ && history_[index]!=v.view_state) return reject();
        observations_[index]=v;return true;
    }
    bool leave(PhaseToken token,Key current,uint64_t world_scene,
               uint64_t world_advance_count) {
        if(!in_phase(token) || std::this_thread::get_id()!=thread_ ||
           current!=plan_.key || world_scene!=scene_ ||
           world_advance_count!=world_advance_) return reject();
        const int e=token.phase==Phase::LeftPair?0:1;
        if(!observations_[e*2] || !observations_[e*2+1]) return reject();
        if(e==1 && (!families_[0] || families_[0]==families_[1])) return reject();
        closed_[e]=true;phase_={};state_=State::Ready;return true;
    }
    // Constructor/phase validation only. NOT an XR submission acknowledgement.
    bool complete() {
        if(std::this_thread::get_id()!=thread_ || state_!=State::Ready ||
           !closed_[0] || !closed_[1]) return reject();
        for(const auto& v:observations_) if(!v) return reject();
        for(unsigned i=0;i<4;++i) history_[i]=observations_[i]->view_state;
        previous_generation_=plan_.key.generation;previous_scene_=scene_;
        previous_serial_=plan_.key.serial;previous_tick_=plan_.key.simulation_tick;
        previous_xr_frame_=plan_.key.xr_frame;has_previous_=true;
        state_=State::Complete;return true;
    }
    bool failed() const{return state_==State::Failed;}
    bool validated() const{return state_==State::Complete;}
    bool active() const{return state_==State::Inside;}
    std::optional<Eye> physical_eye(PhaseToken t) const {
        if(!in_phase(t)) return {};
        return t.phase==Phase::LeftPair?Eye::Left:Eye::Right;
    }
    // Only after scene/mode reset and GPU resource retirement.
    void reset_epoch() {
        state_=State::Idle;phase_={};observations_={};families_={};
        entered_={};closed_={};has_previous_=false;history_={};++nonce_;
    }
private:
    enum class State:uint8_t{Idle,Ready,Inside,Complete,Failed};
    static bool near_frustum(const Frustum& a,const Frustum& b) {
        if(!a.valid()||!b.valid())return false;
        constexpr double eps=1e-5;
        return std::abs(a.left-b.left)<=eps && std::abs(a.right-b.right)<=eps &&
               std::abs(a.top-b.top)<=eps && std::abs(a.bottom-b.bottom)<=eps;
    }
    bool in_phase(PhaseToken t) const {
        return state_==State::Inside && phase_.has_value() && *phase_==t;
    }
    bool reject(){state_=State::Failed;phase_={};return false;}
    Plan plan_{};
    uint64_t scene_{},world_advance_{},nonce_{};
    uint64_t previous_generation_{},previous_scene_{},previous_serial_{},
             previous_tick_{},previous_xr_frame_{};
    std::array<uint64_t,4> history_{};
    std::array<uint64_t,2> families_{};
    std::array<bool,2> entered_{},closed_{};
    std::array<std::optional<ViewEvidence>,4> observations_{};
    std::optional<PhaseToken> phase_{};
    std::thread::id thread_{};
    State state_{State::Idle};
    bool has_previous_{};
};
} // namespace uevr::quadview
