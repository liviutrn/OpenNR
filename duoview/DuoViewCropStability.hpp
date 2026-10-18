#pragma once
#include "DuoViewConfig.hpp"

namespace uevr::duoview {
class CropStability {
public:
    UV update(FrameKey key, uint32_t w, uint32_t h, const Settings& s,
              std::optional<UV> sample, uint64_t now) {
        if (generation_ != key.generation || width_ != w || height_ != h ||
            crop_width_ != s.crop_width || crop_height_ != s.crop_height ||
            density_ != s.foveal_density || source_ != s.fovea_view || now < last_tick_) {
            reset();
            generation_=key.generation; width_=w; height_=h;
            crop_width_=s.crop_width; crop_height_=s.crop_height;
            density_=s.foveal_density; source_=s.fovea_view;
        }
        last_tick_=now;
        if (!s.eye_tracked) {
            // Manual fovea position is independent of eye tracking and must
            // never be lost when tracking is disabled or unavailable.
            // Also clear the old gaze state so re-enabling starts clean.
            have_=false;
            fast_tracking_=false;
            last_gaze_.reset();
            quiet_samples_=0;
            return UV{
                std::clamp(.5f+s.gaze_offset_u, s.crop_width*.5f, 1.f-s.crop_width*.5f),
                std::clamp(.5f+s.gaze_offset_v, s.crop_height*.5f, 1.f-s.crop_height*.5f)
            };
        }
        // A PSVR2 blink or transient invalid sample must never reset the
        // crop to center. Keep the last accepted position until fresh tracking
        // returns, even if the Toolkit is temporarily unavailable.
        if (!sample) {
            // Tracking loss relocks the last valid crop. Recovery is handled
            // by the independent PSVR2 ray gate; never inject a center jump.
            fast_tracking_=false;
            quiet_samples_=0;
            last_gaze_.reset();
            return have_ ? center_ : UV{};
        }
        const UV adjusted{
            std::clamp(sample->u+s.gaze_offset_u,0.f,1.f),
            std::clamp(sample->v+s.gaze_offset_v,0.f,1.f)
        };
        if (!s.stabilize_crop) {
            fast_tracking_=false;
            quiet_samples_=0;
            last_gaze_.reset();
            have_=true;
            center_=adjusted;
            last_valid_=now;
            return center_;
        }
        const auto layout=make_layout(w,h,s.crop_width,s.crop_height,s.peripheral_scale,s.foveal_density);
        if (!layout) { reset(); return {}; }

        // Measure distance to the ACHIEVABLE crop center, not an unclamped
        // gaze outside the full crop's valid viewport bounds.
        const UV feasible{
            std::clamp(adjusted.u, s.crop_width*.5f, 1.f-s.crop_width*.5f),
            std::clamp(adjusted.v, s.crop_height*.5f, 1.f-s.crop_height*.5f)
        };
        UV target=feasible;
        if (have_) {
            const float delta_u=feasible.u-center_.u;
            const float delta_v=feasible.v-center_.v;
            const float travel=std::hypot(delta_u,delta_v);
            if (!fast_tracking_) {
                if (travel >= s.gaze_breakout_radius) {
                    // A genuine saccade has no smoothing: move 1:1 this frame
                    // and keep tracking the ensuing motion at full speed.
                    fast_tracking_=true;
                    quiet_samples_=0;
                } else {
                    // Tiny motion is locked (gain=0) or followed slowly.
                    // The existing guard is an optional hard noise floor.
                    const float guard=(std::min)(.02f,
                        (std::min)(s.crop_width,s.crop_height)*s.guard_fraction);
                    const float gain=travel<=guard ? 0.f : s.gaze_micro_gain;
                    target={center_.u+delta_u*gain, center_.v+delta_v*gain};
                }
            } else if (last_gaze_) {
                const float step=std::hypot(feasible.u-last_gaze_->u,
                                           feasible.v-last_gaze_->v);
                quiet_samples_=step<=s.gaze_still_radius ? quiet_samples_+1u : 0u;
                if (quiet_samples_>=s.gaze_relock_samples) {
                    fast_tracking_=false;
                    quiet_samples_=0;
                    // One stationary frame must not produce another gaze jump.
                    target=center_;
                }
            }
        }
        last_gaze_=feasible;
        const auto resolve=[&](float old, float gaze, float extent, uint32_t pixels) {
            const float maximum=(std::max)(0.f,1.f-extent);
            const float desired=std::clamp(gaze-extent*.5f,0.f,maximum);
            // Full-speed saccades bypass all crop-guard smoothing.
            // Stationary deadzone behavior was already applied in 2D above.
            // Snap the crop origin on a stable source-pixel grid.
            // Quantization is independent from the deadzone/guard control.
            const float pixel=pixels ? extent/static_cast<float>(pixels) : 0.f;
            const float step=s.gaze_quant_pixels && pixel>0.f
                ? static_cast<float>(s.gaze_quant_pixels)*pixel : 0.f;
            return step>0.f ? std::clamp(std::round(desired/step)*step,0.f,maximum) : desired;
        };
        origin_u_=resolve(origin_u_,target.u,s.crop_width,layout->fovea.width);
        origin_v_=resolve(origin_v_,target.v,s.crop_height,layout->fovea.height);
        center_={origin_u_+s.crop_width*.5f,origin_v_+s.crop_height*.5f};
        last_valid_=now; have_=true;
        return center_;
    }
    void reset() {
        have_=false;
        fast_tracking_=false;
        quiet_samples_=0;
        last_gaze_.reset();
        last_tick_=last_valid_=generation_=0;
    }
private:
    uint64_t generation_{}, last_tick_{}, last_valid_{};
    uint32_t width_{}, height_{}, source_{};
    float crop_width_{},crop_height_{},density_{},origin_u_{},origin_v_{};
    UV center_{};
    std::optional<UV> last_gaze_{};
    uint32_t quiet_samples_{};
    bool have_{},fast_tracking_{};
};
}
