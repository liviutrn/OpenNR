#pragma once
// OpenNR fixation policy operates on coordinates; it never holds scene color.
#include "DuoViewConfig.hpp"
#include "DuoViewOpenNRCropPolicy.hpp"
#include <cmath>
#include <cstdint>
namespace uevr::duoview {
class CropStability {
public:
 UV update(FrameKey key,uint32_t w,uint32_t h,const Settings& s,
           std::optional<UV> sample,uint64_t now,float input_scale_x=1.f,float input_scale_y=1.f) {
    const float delta=last_tick_ && now>=last_tick_ ? static_cast<float>(now-last_tick_) : 16.67f;
    if (generation_!=key.generation || w!=width_ || h!=height_ ||
        cw_!=s.crop_width || ch_!=s.crop_height ||
        (last_tick_ && now<last_tick_)) {
        reset(); generation_=key.generation; width_=w; height_=h;
        cw_=s.crop_width; ch_=s.crop_height;
    }
    last_tick_=now;
    if (!s.eye_tracked) { have_=false; return {}; }
    if (sample && std::isfinite(sample->u) && std::isfinite(sample->v) &&
        sample->u>=0.f && sample->u<=1.f && sample->v>=0.f && sample->v<=1.f) {
        last_valid_=now;
        if (s.r10_crop_policy && s.stabilize_crop) {
            const auto layout=make_layout(w,h,s.crop_width,s.crop_height,s.peripheral_scale,s.foveal_density,
                .5f,.5f,s.compact_atlas);
            const auto input_width=layout ? static_cast<uint32_t>(std::round(layout->fovea.width/s.crop_width*input_scale_x)) : w;
            const auto input_height=layout ? static_cast<uint32_t>(std::round(layout->fovea.height/s.crop_height*input_scale_y)) : h;
            const std::array<float,2> raw{sample->u,sample->v};
            filtered_=have_ ? opennr::filter(filtered_,raw,delta,s.smoothing_ms,input_width,input_height) : raw;
            const auto u0=opennr::resolve_origin(current_.u-s.crop_width*.5f,filtered_[0],
                s.crop_width,input_width,s.quantization_pixels,have_);
            const auto v0=opennr::resolve_origin(current_.v-s.crop_height*.5f,filtered_[1],
                s.crop_height,input_height,s.quantization_pixels,have_);
            current_={u0+s.crop_width*.5f,v0+s.crop_height*.5f};
        } else { current_=*sample; filtered_={sample->u,sample->v}; }
        have_=true;
        return current_;
    }
    if (have_ && now>=last_valid_ && (s.hold_tracking_loss || now-last_valid_<=50))
        return current_;
    have_=false;
    return {}; // stale tracking -> center, never old color/history
 }
 void reset() { generation_=last_tick_=last_valid_=0; width_=height_=0;
                cw_=ch_=0.f; current_={}; filtered_={}; have_=false; }
private:
 uint64_t generation_{},last_tick_{},last_valid_{};
 uint32_t width_{},height_{};
 float cw_{},ch_{};
 UV current_{};
 std::array<float,2> filtered_{};
 bool have_{};
};
}
