#pragma once
#include "DuoViewGeometry.hpp"

namespace uevr::duoview {
struct FovealCamera {
    std::array<float, 3> right{1,0,0}, up{0,1,0}, forward{0,0,1};
    std::array<float, 4> full_projection{};
    float scale_x{}, scale_y{};
    bool enabled{};
};

inline float dot_ray(const std::array<float,3>& a, const std::array<float,3>& b) {
    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2];
}

inline std::array<float,3> full_view_ray(const std::array<float,4>& p, float u, float v) {
    return {(2*u-1-p[2])/p[0], (1-2*v-p[3])/p[1], 1};
}

inline std::optional<FovealCamera> make_foveal_camera(
    const std::array<float,16>& projection, const Layout& layout) {
    for (float x:projection) if (!std::isfinite(x)) return {};
    if (projection[0]<=0 || projection[5]<=0 || std::abs(projection[11]-1)>1e-5f ||
        std::abs(projection[15])>1e-5f || std::abs(projection[4])>1e-5f ||
        std::abs(projection[1])>1e-5f) return {};
    FovealCamera camera{};
    camera.full_projection={projection[0],projection[5],projection[8],projection[9]};
    const auto center=full_view_ray(camera.full_projection,
        (layout.u0+layout.u1)*.5f,(layout.v0+layout.v1)*.5f);
    const auto length=std::sqrt(dot_ray(center,center));
    for (unsigned i=0;i<3;++i) camera.forward[i]=center[i]/length;
    const float horizontal=std::sqrt(1+center[0]*center[0]);
    camera.right={1/horizontal,0,-center[0]/horizontal};
    camera.up={-camera.forward[1]*center[0]/horizontal,
        horizontal/length,-camera.forward[1]/horizontal};
    float half_x{},half_y{};
    for (float u:{layout.u0,layout.u1}) for (float v:{layout.v0,layout.v1}) {
        const auto ray=full_view_ray(camera.full_projection,u,v);
        const float z=dot_ray(camera.forward,ray);
        if (!std::isfinite(z) || z<=.01f) return {};
        half_x=(std::max)(half_x,std::abs(dot_ray(camera.right,ray)/z));
        half_y=(std::max)(half_y,std::abs(dot_ray(camera.up,ray)/z));
    }
    if (half_x<=0 || half_y<=0) return {};
    camera.scale_x=1/(half_x*1.001f);
    camera.scale_y=1/(half_y*1.001f);
    camera.enabled=true;
    return camera;
}

template<typename Matrix>
void rotate_foveal_view(Matrix& matrix, const FovealCamera& camera) {
    for (int col=0;col<4;++col) {
        const auto x=matrix[col][0], y=matrix[col][1], z=matrix[col][2];
        matrix[col][0]=camera.right[0]*x+camera.right[1]*y+camera.right[2]*z;
        matrix[col][1]=camera.up[0]*x+camera.up[1]*y+camera.up[2]*z;
        matrix[col][2]=camera.forward[0]*x+camera.forward[1]*y+camera.forward[2]*z;
    }
}

inline std::array<float,2> foveal_uv(const FovealCamera& camera, float u, float v) {
    const auto ray=full_view_ray(camera.full_projection,u,v);
    const auto z=dot_ray(camera.forward,ray);
    return {.5f+.5f*camera.scale_x*dot_ray(camera.right,ray)/z,
        .5f-.5f*camera.scale_y*dot_ray(camera.up,ray)/z};
}
}
