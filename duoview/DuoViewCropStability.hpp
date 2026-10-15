#pragma once
// Native Reader exclusively owns the 50-ms gaze expiry. No second hold here.
// Valid saccades are instant; <=1 output-pixel fixation noise is guarded.
#include "DuoViewConfig.hpp"
#include <cmath>
#include <cstdint>
namespace uevr::duoview {
class CropStability {
public:
 UV update(FrameKey key,uint32_t w,uint32_t h,const Settings& s,
           std::optional<UV> sample,uint64_t now) {
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
        if(have_ && s.stabilize_crop && w && h &&
           std::abs(sample->u-current_.u)*w<=1.f &&
           std::abs(sample->v-current_.v)*h<=1.f) return current_;
        current_=*sample; have_=true;
        return current_; // new valid eye sample always wins instantly
    }
    have_=false;
    return {}; // stale tracking -> center, never old color/history
 }
 void reset() { generation_=last_tick_=0; width_=height_=0;
                cw_=ch_=0.f; current_={}; have_=false; }
private:
 uint64_t generation_{},last_tick_{};
 uint32_t width_{},height_{};
 float cw_{},ch_{};
 UV current_{};
 bool have_{};
};
}
