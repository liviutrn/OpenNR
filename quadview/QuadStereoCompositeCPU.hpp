#pragma once
// CPU reference for the UV math in QuadStereoComposite.hlsl.
// View projection must be reconstructed from each physical eye's asymmetric
// frustum BEFORE rendering; this only maps a finished fovea to the full image.
#include <algorithm>
#include <array>
#include <cmath>
#include <optional>

namespace uevr::quadview {
struct CompositorCrop {
    double u0{},v0{},u1{},v1{},feather{};
    bool valid() const {
        return std::isfinite(u0) && std::isfinite(v0) &&
            std::isfinite(u1) && std::isfinite(v1) &&
            std::isfinite(feather) && feather >= 0.0 &&
            u0 >= 0.0 && v0 >= 0.0 && u0 < u1 && v0 < v1 &&
            u1 <= 1.0 && v1 <= 1.0;
    }
};
inline double composite_weight(CompositorCrop c,double u,double v) {
    if(!c.valid() || !std::isfinite(u) || !std::isfinite(v))
        return 0.0;
    const double edge=std::min({u-c.u0,v-c.v0,c.u1-u,c.v1-v});
    if(edge<=0.0) return 0.0;
    if(c.feather==0.0) return 1.0;
    return std::clamp(edge/c.feather,0.0,1.0);
}
inline std::optional<std::array<double,2>> to_fovea_uv(
    CompositorCrop c,double u,double v) {
    if(!c.valid() || !std::isfinite(u) || !std::isfinite(v) ||
        u<c.u0 || u>c.u1 || v<c.v0 || v>c.v1) return {};
    return std::array<double,2>{
        std::clamp((u-c.u0)/(c.u1-c.u0),0.0,1.0),
        std::clamp((v-c.v0)/(c.v1-c.v0),0.0,1.0)};
}
} // namespace uevr::quadview
