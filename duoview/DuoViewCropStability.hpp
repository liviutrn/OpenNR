#pragma once
// Frame-atomic gaze with a one-output-pixel fixation guard and instant saccades.
#include "DuoViewConfig.hpp"
#include <cmath>
#include <cstdint>
namespace uevr::duoview {
class CropStability {
public:
 UV update(FrameKey key,uint32_t w,uint32_t h,const Settings& s,
           GazeSample sample,uint64_t now) {
    if (generation_!=key.generation || w!=width_ || h!=height_ ||
        cw_!=s.crop_width || ch_!=s.crop_height ||
        (last_tick_ && now<last_tick_)) {
        reset(); generation_=key.generation; width_=w; height_=h;
        cw_=s.crop_width; ch_=s.crop_height;
    }
    last_tick_=now;
    if (!s.eye_tracked) { have_=false; return {}; }
    if (sample.invalidated) {
        have_=false;
        last_valid_=0;
        return {};
    }
    if (sample.uv && std::isfinite(sample.uv->u) && std::isfinite(sample.uv->v) &&
        sample.uv->u>=0.f && sample.uv->u<=1.f &&
        sample.uv->v>=0.f && sample.uv->v<=1.f) {
        const auto arrival=sample.timestamped && sample.host_arrival_ms<=now
            ? sample.host_arrival_ms : now;
        // Only a new sensor packet advances expiry. A cached packet can seed a
        // reset state, but it retains its original arrival timestamp.
        const bool new_to_state=sample.fresh || !have_ || arrival>last_valid_;
        if (new_to_state) {
            const bool inside_fixation_guard=have_ && s.stabilize_crop && w && h &&
                std::abs(sample.uv->u-current_.u)*w<=1.f &&
                std::abs(sample.uv->v-current_.v)*h<=1.f;
            if (!inside_fixation_guard) current_=*sample.uv;
            have_=true;
            last_valid_=arrival;
        }
        if (have_ && now>=last_valid_ && now-last_valid_<=50) {
            return current_; // new valid eye sample always wins instantly
        }
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
