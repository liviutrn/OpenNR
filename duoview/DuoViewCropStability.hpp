#pragma once
// Frame-atomic PSVR2 gaze. Optional time-based smoothing is applied BEFORE the
// foveal projection is constructed, never to already-rendered pixels. Zero ms
// is the exact original instant path. No smoothing history is submitted to UE.
#include "DuoViewConfig.hpp"
#include <algorithm>
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
    if (!s.eye_tracked) { have_=false; last_valid_=last_filter_ms_=0; return {}; }
    if (sample.invalidated) {
        have_=false;
        last_valid_=last_filter_ms_=0;
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
            // Never blend with a stale prior gaze or across an invalidation.
            const bool previous_valid=have_ && now>=last_valid_ &&
                now-last_valid_<=50 && last_filter_ms_ && now>=last_filter_ms_;
            UV candidate=*sample.uv;
            // Time-constant EMA: 0ms follows instantly, 1-250ms smooths all
            // small eye movements and saccades. Use actual elapsed frame time,
            // not an FPS-dependent fixed weight. No filtering of cached gaze.
            if (previous_valid && s.smoothing_ms>0.f) {
                const float dt=static_cast<float>(now-last_filter_ms_);
                const float alpha=std::clamp(-std::expm1(-dt/s.smoothing_ms),0.f,1.f);
                candidate.u=current_.u+(sample.uv->u-current_.u)*alpha;
                candidate.v=current_.v+(sample.uv->v-current_.v)*alpha;
            }
            const bool inside_fixation_guard=previous_valid && s.stabilize_crop && w && h &&
                std::abs(candidate.u-current_.u)*w<=1.f &&
                std::abs(candidate.v-current_.v)*h<=1.f;
            if (!inside_fixation_guard) current_=candidate;
            have_=true;
            last_valid_=arrival;
            last_filter_ms_=now;
        }
        if (have_ && now>=last_valid_ && now-last_valid_<=50)
            return current_;
    }
    if (have_ && now>=last_valid_ && now-last_valid_<=50)
        return current_;
    have_=false;
    last_valid_=last_filter_ms_=0;
    return {}; // expired gaze -> center, never sample stale history
 }
 void reset() { generation_=last_tick_=last_valid_=last_filter_ms_=0;
                width_=height_=0; cw_=ch_=0.f; current_={}; have_=false; }
private:
 uint64_t generation_{},last_tick_{},last_valid_{},last_filter_ms_{};
 uint32_t width_{},height_{};
 float cw_{},ch_{};
 UV current_{};
 bool have_{};
};
}
