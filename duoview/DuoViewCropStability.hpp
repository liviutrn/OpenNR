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
            have_=false;
            return UV{};
        }
        // A PSVR2 blink or transient invalid sample must never reset the
        // crop to center. Keep the last accepted position until fresh tracking
        // returns, even if the Toolkit is temporarily unavailable.
        if (!sample) return have_ ? center_ : UV{};
        const UV adjusted{
            std::clamp(sample->u+s.gaze_offset_u,0.f,1.f),
            std::clamp(sample->v+s.gaze_offset_v,0.f,1.f)
        };
        if (!s.stabilize_crop) {
            have_=true;
            center_=adjusted;
            last_valid_=now;
            return center_;
        }
        const auto layout=make_layout(w,h,s.crop_width,s.crop_height,s.peripheral_scale,s.foveal_density);
        if (!layout) { have_=false; return {}; }
        const auto resolve=[&](float old, float gaze, float extent, uint32_t pixels) {
            const float maximum=(std::max)(0.f,1.f-extent);
            const float desired=std::clamp(gaze-extent*.5f,0.f,maximum);
            const float guard=(std::min)(.02f,extent*s.guard_fraction);
            if (have_ && std::abs(desired-old)<=guard) return old;
            // Snap the crop origin on a stable source-pixel grid.
            // Quantization is independent from the deadzone/guard control.
            const float pixel=pixels ? extent/static_cast<float>(pixels) : 0.f;
            const float step=s.gaze_quant_pixels && pixel>0.f
                ? static_cast<float>(s.gaze_quant_pixels)*pixel : 0.f;
            return step>0.f ? std::clamp(std::round(desired/step)*step,0.f,maximum) : desired;
        };
        origin_u_=resolve(origin_u_,adjusted.u,s.crop_width,layout->fovea.width);
        origin_v_=resolve(origin_v_,adjusted.v,s.crop_height,layout->fovea.height);
        center_={origin_u_+s.crop_width*.5f,origin_v_+s.crop_height*.5f};
        last_valid_=now; have_=true;
        return center_;
    }
    void reset() { have_=false; last_tick_=last_valid_=generation_=0; }
private:
    uint64_t generation_{}, last_tick_{}, last_valid_{};
    uint32_t width_{}, height_{}, source_{};
    float crop_width_{},crop_height_{},density_{},origin_u_{},origin_v_{};
    UV center_{};
    bool have_{};
};
}
