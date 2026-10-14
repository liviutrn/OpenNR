#pragma once
// v24: instantaneous, frame-atomic gaze. No spatial guard, smoothing,
// speed cap or source-pixel quantization. Brief acquisition gaps hold the
// last good *coordinate*, not any previous rendered image or projection.
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
        last_valid_=now; current_=*sample; have_=true;
        return current_; // new valid eye sample always wins instantly
    }
    if (have_ && now>=last_valid_ && now-last_valid_<=50)
        return current_;
    have_=false;
    return {}; // stale tracking -> center, never old color/history
 }
 void reset() { generation_=last_tick_=last_valid_=0; width_=height_=0;
                cw_=ch_=0.f; current_={}; have_=false; }
private:
 uint64_t generation_{},last_tick_{},last_valid_{};
 uint32_t width_{},height_{};
 float cw_{},ch_{};
 UV current_{};
 bool have_{};
};
}
