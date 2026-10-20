#pragma once

// Stereo adaptation of the published v186.1 DuoView gaze mapping. The CAPI
// ray is recovered once in head space; each eye then applies its own optical
// rotation and its own full projection matrix before the crop is frozen.
#include "DuoViewGaze.hpp"
#include "QuadViewGeometry.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <optional>

namespace uevr::quadview::gaze {

using Quaternion = std::array<float, 4>; // OpenXR x, y, z, w
using Projection = std::array<float, 16>; // GLM/OpenXR column-major projection

inline bool valid_perspective_projection(const Projection& p) {
    for (const float v : p) if (!std::isfinite(v)) return false;
    // UEVR's +Z-forward perspective has a nonzero focal scale, positive
    // forward clip-w, and no homogeneous identity term. This rejects the
    // finite all-zero/identity matrices observed before the first XR update.
    return std::abs(p[0])>1.0e-6f && std::abs(p[5])>1.0e-6f &&
        p[11]>.01f && std::abs(p[15])<1.0e-4f;
}

inline std::optional<Quaternion> normalize(Quaternion q) {
    float length2{};
    for (const float v : q) {
        if (!std::isfinite(v)) return {};
        length2 += v * v;
    }
    if (!std::isfinite(length2) || length2 < .0001f) return {};
    const float inverse = 1.f / std::sqrt(length2);
    for (auto& v : q) v *= inverse;
    return q;
}

inline Quaternion multiply(const Quaternion& a, const Quaternion& b) {
    return {
        a[3]*b[0] + a[0]*b[3] + a[1]*b[2] - a[2]*b[1],
        a[3]*b[1] - a[0]*b[2] + a[1]*b[3] + a[2]*b[0],
        a[3]*b[2] + a[0]*b[1] - a[1]*b[0] + a[2]*b[3],
        a[3]*b[3] - a[0]*b[0] - a[1]*b[1] - a[2]*b[2]
    };
}

// qHead maps head-space directions into stage space; qEye maps eye-local
// directions into stage space. qHead^-1*qEye is therefore the eye rotation in
// head coordinates, which the production optical_ray helper transposes.
inline std::optional<std::array<float, 9>> eye_rotation_in_head(
    Quaternion head, Quaternion eye)
{
    head = normalize(head).value_or(Quaternion{});
    eye = normalize(eye).value_or(Quaternion{});
    if (head == Quaternion{} || eye == Quaternion{}) return {};
    const Quaternion head_inverse{-head[0], -head[1], -head[2], head[3]};
    const auto q = normalize(multiply(head_inverse, eye));
    if (!q) return {};
    const auto [x, y, z, w] = *q;
    // Column-major, matching OpenXR/GLM storage expected by the exact
    // v186.1 optical_ray helper. It transposes this eye-local-to-head matrix.
    return std::array<float, 9>{
        1.f-2.f*(y*y+z*z), 2.f*(x*y+z*w), 2.f*(x*z-y*w),
        2.f*(x*y-z*w), 1.f-2.f*(x*x+z*z), 2.f*(y*z+x*w),
        2.f*(x*z+y*w), 2.f*(y*z-x*w), 1.f-2.f*(x*x+y*y)
    };
}

// This is the same projective mapping used by v186.1's PSVR2 Reader, exposed
// here as a portable helper so both eyes can use their own full matrix.
inline std::optional<duoview::UV> projection_uv(
    const duoview::Ray& ray, const Projection& p)
{
    if (!std::isfinite(ray.right) || !std::isfinite(ray.up) ||
        !std::isfinite(ray.forward) || ray.forward <= .1f) return {};
    for (const float v : p) if (!std::isfinite(v)) return {};
    const float x = p[0]*ray.right + p[4]*ray.up + p[8]*ray.forward;
    const float y = p[1]*ray.right + p[5]*ray.up + p[9]*ray.forward;
    const float w = p[3]*ray.right + p[7]*ray.up + p[11]*ray.forward;
    if (!std::isfinite(w) || w <= .01f) return {};
    const float u = (x/w + 1.f)*.5f;
    const float v = (1.f - y/w)*.5f;
    if (!std::isfinite(u) || !std::isfinite(v)) return {};
    return duoview::UV{std::clamp(u, 0.f, 1.f), std::clamp(v, 0.f, 1.f)};
}

struct Tangents { float left{}, right{}, up{}, down{}; };

inline std::optional<Tangents> tangents_from_fov(
    float angle_left, float angle_right, float angle_up, float angle_down) {
    if (!std::isfinite(angle_left) || !std::isfinite(angle_right) ||
        !std::isfinite(angle_up) || !std::isfinite(angle_down) ||
        angle_left >= angle_right || angle_down >= angle_up ||
        std::abs(angle_left) >= 1.55f || std::abs(angle_right) >= 1.55f ||
        std::abs(angle_up) >= 1.55f || std::abs(angle_down) >= 1.55f) return {};
    const float left=std::tan(angle_left), right=std::tan(angle_right);
    const float top=std::tan(angle_up), bottom=std::tan(angle_down);
    if (!std::isfinite(left) || !std::isfinite(right) ||
        !std::isfinite(top) || !std::isfinite(bottom) ||
        right-left < .01f || top-bottom < .01f) return {};
    return Tangents{left,right,top,bottom};
}

inline std::optional<Projection> projection_from_tangents(Tangents t) {
    if (!std::isfinite(t.left) || !std::isfinite(t.right) ||
        !std::isfinite(t.up) || !std::isfinite(t.down) ||
        t.right-t.left < .01f || t.up-t.down < .01f) return {};
    Projection p{};
    p[0]=2.f/(t.right-t.left); p[5]=2.f/(t.up-t.down);
    p[8]=-(t.right+t.left)/(t.right-t.left); p[9]=-(t.up+t.down)/(t.up-t.down);
    p[10]=1.f; p[11]=1.f; p[14]=.01f;
    return p;
}

// OpenXR applies UEVR's horizontal and vertical projection overrides to the
// same raw per-eye FOV pair before building runtime matrices. These mode IDs
// intentionally match VR::{HORIZONTAL,VERTICAL}_PROJECTION_OVERRIDE.
inline std::optional<std::array<Projection,2>> projections_from_fovs(
    const std::array<Tangents,2>& raw, int32_t horizontal_mode, int32_t vertical_mode) {
    if (horizontal_mode<0 || horizontal_mode>2 || vertical_mode<0 || vertical_mode>2) return {};
    auto effective=raw;
    if (horizontal_mode==1) {
        const float outer=std::max({-raw[0].left,raw[0].right,-raw[1].left,raw[1].right});
        effective[0].left=effective[1].left=-outer;
        effective[0].right=effective[1].right=outer;
    } else if (horizontal_mode==2) {
        const float outer=std::max(-raw[0].left,raw[1].right);
        const float inner=std::max(raw[0].right,-raw[1].left);
        effective[0].left=-outer; effective[0].right=inner;
        effective[1].left=-inner; effective[1].right=outer;
    }
    if (vertical_mode==1) {
        const float half=std::max({raw[0].up,-raw[0].down,raw[1].up,-raw[1].down});
        effective[0].up=effective[1].up=half;
        effective[0].down=effective[1].down=-half;
    } else if (vertical_mode==2) {
        const float top=std::max(raw[0].up,raw[1].up);
        const float bottom=std::max(-raw[0].down,-raw[1].down);
        effective[0].up=effective[1].up=top;
        effective[0].down=effective[1].down=-bottom;
    }
    const auto left=projection_from_tangents(effective[0]);
    const auto right=projection_from_tangents(effective[1]);
    if (!left || !right) return {};
    return std::array<Projection,2>{*left,*right};
}

// Build the full default OpenXR-style +Z projection from one eye FOV.
inline std::optional<Projection> projection_from_fov(
    float angle_left, float angle_right, float angle_up, float angle_down) {
    const auto tangent=tangents_from_fov(angle_left,angle_right,angle_up,angle_down);
    return tangent ? projection_from_tangents(*tangent) : std::nullopt;
}

inline std::optional<duoview::UV> project_head_ray(
    const duoview::Ray& head_ray, Quaternion head_orientation,
    Quaternion eye_orientation, const Projection& full_eye_projection)
{
    const auto rotation = eye_rotation_in_head(head_orientation, eye_orientation);
    if (!rotation) return {};
    const auto eye_ray = duoview::optical_ray(head_ray, *rotation);
    if (!eye_ray) return {};
    return projection_uv(*eye_ray, full_eye_projection);
}

inline std::optional<std::array<duoview::UV, 2>> project_stereo_head_ray(
    const duoview::Ray& head_ray, Quaternion head_orientation,
    const std::array<Quaternion, 2>& eye_orientations,
    const std::array<Projection, 2>& full_eye_projections)
{
    std::array<duoview::UV, 2> result{};
    for (size_t eye = 0; eye != 2; ++eye) {
        const auto uv = project_head_ray(head_ray, head_orientation,
                                        eye_orientations[eye], full_eye_projections[eye]);
        if (!uv) return {};
        result[eye] = *uv;
    }
    return result;
}

} // namespace uevr::quadview::gaze
