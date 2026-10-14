#pragma once
// OpenNR r10: 3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98, GazeCropPolicy.h.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
namespace uevr::duoview::opennr {
inline std::array<float,2> filter(const std::array<float,2>& previous,
    const std::array<float,2>& sample,float delta_ms,float smoothing_ms,uint32_t width,uint32_t height) {
    if (!width || !height || std::abs(sample[0]-previous[0])*width>2.f ||
        std::abs(sample[1]-previous[1])*height>2.f) return sample;
    const float duration=std::clamp(std::isfinite(smoothing_ms)?smoothing_ms:0.f,0.f,250.f);
    const float elapsed=std::clamp(std::isfinite(delta_ms)?delta_ms:16.67f,.1f,250.f);
    const float alpha=duration>0.f?elapsed/(duration+elapsed):1.f;
    return {previous[0]+(sample[0]-previous[0])*alpha,previous[1]+(sample[1]-previous[1])*alpha};
}
inline float resolve_origin(float previous,float sample,float extent,uint32_t pixels,
    uint32_t quantization,bool have_previous) {
    const float max_origin=(std::max)(0.f,1.f-extent);
    const float desired=std::clamp(sample-extent*.5f,0.f,max_origin);
    const float guard=(std::min)(.02f,extent*.05f);
    if (have_previous && std::abs(desired-previous)<=guard) return previous;
    const float step=pixels?(std::min)(static_cast<float>(quantization)/pixels,guard):0.f;
    return step>0.f?std::clamp(std::round(desired/step)*step,0.f,max_origin):desired;
}
}
