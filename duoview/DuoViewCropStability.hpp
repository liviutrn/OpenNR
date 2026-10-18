#pragma once
// Temporal, source-pixel-aligned gaze tracking. Never changes an accepted
// frame's projection or compositor rectangle after State::begin has latched it.
#include "DuoViewConfig.hpp"
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace uevr::duoview {
class CropStability {
public:
    UV update(FrameKey key, uint32_t w, uint32_t h, const Settings& s,
              std::optional<UV> sample, uint64_t now) {
        if (generation_ != key.generation || width_ != w || height_ != h ||
            crop_width_ != s.crop_width || crop_height_ != s.crop_height ||
            density_ != s.foveal_density || source_ != s.fovea_view ||
            (last_tick_ && now < last_tick_)) {
            reset();
            generation_ = key.generation; width_ = w; height_ = h;
            crop_width_ = s.crop_width; crop_height_ = s.crop_height;
            density_ = s.foveal_density; source_ = s.fovea_view;
        }
        // Clamp long pauses/hitches: never teleport the projection after a
        // delayed frame. Tick once per accepted source frame, not per eye.
        const float dt_ms = last_tick_ && now > last_tick_
            ? static_cast<float>((std::min)(now-last_tick_,uint64_t{33})) : 11.f;
        last_tick_ = now;
        if (!s.stabilize_crop || !s.eye_tracked) {
            have_ = false;
            return sample.value_or(UV{});
        }
        const auto layout=make_layout(w,h,s.crop_width,s.crop_height,
                                      s.peripheral_scale,s.foveal_density);
        if (!layout) { have_=false; return {}; }

        const bool valid=sample && std::isfinite(sample->u) && std::isfinite(sample->v) &&
                         sample->u>=0.f && sample->u<=1.f &&
                         sample->v>=0.f && sample->v<=1.f;
        if (valid) last_valid_=now;
        else if (!have_) return {};
        else if (now>=last_valid_ && now-last_valid_<=250) return center_;

        // v24c: saccadic ROI updates. A continuously gliding crop keeps the
        // projection in perpetual motion so TAA/DLSS/Lumen never converge
        // (the interior "shake" during motion). Instead the ROI holds static
        // for crop_hold_ms after each move, then snaps (single-frame jump)
        // to the new gaze — like a real saccade: jump, then fixate.
        // First valid lock-on is still an immediate snap.
        const UV target = valid ? *sample : UV{};
        const auto maximum_u=(std::max)(0.f,1.f-s.crop_width);
        const auto maximum_v=(std::max)(0.f,1.f-s.crop_height);
        const auto desired_u=std::clamp(target.u-s.crop_width*.5f,0.f,maximum_u);
        const auto desired_v=std::clamp(target.v-s.crop_height*.5f,0.f,maximum_v);
        const auto align_u=[&](float v){
            const float pixel=layout->fovea.width
                ? s.crop_width/static_cast<float>(layout->fovea.width) : 0.f;
            return pixel>0.f ? std::clamp(std::round(v/pixel)*pixel,0.f,maximum_u) : v;
        };
        const auto align_v=[&](float v){
            const float pixel=layout->fovea.height
                ? s.crop_height/static_cast<float>(layout->fovea.height) : 0.f;
            return pixel>0.f ? std::clamp(std::round(v/pixel)*pixel,0.f,maximum_v) : v;
        };
        // Deadzone: no move unless the gaze demands it. Tracking loss has no
        // deadzone so it converges to center rather than getting stuck.
        const float guard_u=valid ? s.crop_width*s.guard_fraction : 0.f;
        const float guard_v=valid ? s.crop_height*s.guard_fraction : 0.f;
        const bool needs_move = !have_ ||
            (std::max)(0.f,std::abs(desired_u-origin_u_)-guard_u) > 0.f ||
            (std::max)(0.f,std::abs(desired_v-origin_v_)-guard_v) > 0.f;
        const bool hold = needs_move && have_ && s.crop_hold_ms>0 &&
            last_roi_move_!=0 && now>=last_roi_move_ &&
            now-last_roi_move_ < s.crop_hold_ms;
        if (needs_move && !hold) {
            if ((!have_ || s.crop_snap) && valid) {
                // Saccadic snap: first lock-on or gaze following. Single-frame
                // jump; bypasses smoothing/speed cap. Tracking loss (!valid)
                // still eases home via the glide path below.
                origin_u_=align_u(desired_u);
                origin_v_=align_v(desired_v);
            } else {
                const auto move=[&](float old,float gaze,float extent,uint32_t pixels) {
                    const float maximum=(std::max)(0.f,1.f-extent);
                    const float desired=std::clamp(gaze-extent*.5f,0.f,maximum);
                    const float pixel=pixels ? extent/static_cast<float>(pixels) : 0.f;
                    const auto align=[&](float value) {
                        return pixel>0.f
                            ? std::clamp(std::round(value/pixel)*pixel,0.f,maximum)
                            : value;
                    };
                    // Tracking loss must converge to center rather than getting stuck
                    // in the normal fixation deadzone.
                    const float guard=valid ? extent*s.guard_fraction : 0.f;
                    const float diff=desired-old;
                    const float excess=(std::max)(0.f,std::abs(diff)-guard);
                    if (excess==0.f) return old;
                    // Continuous deadzone: no hard re-centering jump at the boundary.
                    const float smoothing=(std::max)(0.f,s.smoothing_ms);
                    const float alpha=smoothing>0.f ? 1.f-std::exp(-dt_ms/smoothing) : 1.f;
                    // Hard velocity limit also bounds changes when smoothing is zero.
                    const float max_step=3.0f*dt_ms/1000.f;
                    const float travel=(std::min)(excess*alpha,max_step);
                    const float candidate=old+std::copysign(travel,diff);
                    return align(std::clamp(candidate,0.f,maximum));
                };
                origin_u_=move(origin_u_,target.u,s.crop_width,layout->fovea.width);
                origin_v_=move(origin_v_,target.v,s.crop_height,layout->fovea.height);
            }
            last_roi_move_=now;
        }
        center_={origin_u_+s.crop_width*.5f,origin_v_+s.crop_height*.5f};
        have_=true;
        return center_;
    }
    void reset() {
        have_=false; last_tick_=last_valid_=generation_=0;
        origin_u_=origin_v_=0.f; center_={}; last_roi_move_=0;
    }
private:
    uint64_t generation_{},last_tick_{},last_valid_{},last_roi_move_{};
    uint32_t width_{},height_{},source_{};
    float crop_width_{},crop_height_{},density_{},origin_u_{},origin_v_{};
    UV center_{};
    bool have_{};
};
}
