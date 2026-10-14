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
        const auto elapsed=now>=last_tick_ ? now-last_tick_ : 0;
        last_tick_=now;
        if (!s.stabilize_crop || !s.eye_tracked) {
            have_=false;
            return sample.value_or(UV{});
        }
        if (!sample) {
            if (have_ && now>=last_valid_ && now-last_valid_<=100) return center_;
            have_=false;
            return {};
        }
        UV filtered=*sample;
        if (have_ && std::abs(sample->u-center_.u)*w<=2.f &&
            std::abs(sample->v-center_.v)*h<=2.f) {
            const float dt=std::clamp(static_cast<float>(elapsed),.1f,250.f);
            const float alpha=s.fixation_ms>0.f ? dt/(s.fixation_ms+dt) : 1.f;
            filtered={center_.u+(sample->u-center_.u)*alpha,
                      center_.v+(sample->v-center_.v)*alpha};
        }
        const auto resolve=[&](float old, float gaze, float extent, uint32_t pixels) {
            const float maximum=std::max(0.f,1.f-extent);
            const float desired=std::clamp(gaze-extent*.5f,0.f,maximum);
            const float guard=std::min(.02f,extent*.05f);
            if (have_ && std::abs(desired-old)<=guard) return old;
            const float step=pixels ? std::min(4.f/pixels,guard) : 0.f;
            return step>0.f ? std::clamp(std::round(desired/step)*step,0.f,maximum) : desired;
        };
        origin_u_=resolve(origin_u_,filtered.u,s.crop_width,w);
        origin_v_=resolve(origin_v_,filtered.v,s.crop_height,h);
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
