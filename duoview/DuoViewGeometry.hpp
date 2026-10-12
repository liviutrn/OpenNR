#pragma once
// DuoView Mono: renderer-independent two-view layout, projection crop and
// compositor coordinate model. No UE/UESDK dependencies.
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>

namespace uevr::duoview {

constexpr int renderer_view_index(int raw, bool double_precision) {
    if (double_precision) return raw >= 0 && raw <= 1 ? raw : -1;
    return raw >= 1 && raw <= 2 ? raw - 1 : -1;
}

struct Rect {
    uint32_t x{}, y{}, width{}, height{};
};
struct Layout {
    Rect fovea{}, periphery{};
    uint32_t atlas_width{}, atlas_height{};
    float u0{}, u1{}, v0{}, v1{}; // ROI on the full Mono image, top-left UV convention
    float peripheral_scale{};
    float crop_width{}, crop_height{};
};
struct Tans {
    // Left < right; top > bottom. Represent tangent-space extent of the
    // centered combined Mono projection, NOT angular percentages.
    float left{}, right{}, top{}, bottom{};
};

// Diagnostic defaults: preserve ~3000² baseline render density in the fovea
// without silently increasing the output/swapchain resolution.
inline std::optional<Layout> make_layout(
    uint32_t output_width, uint32_t output_height,
    float crop_width = 0.50f, float crop_height = 0.50f,
    float peripheral_scale = 0.20f, float foveal_density = 1.0f,
    float gaze_u = 0.50f, float gaze_v = 0.50f)
{
    if (!output_width || !output_height || output_width > 8192 || output_height > 16384 ||
        !std::isfinite(crop_width) || !std::isfinite(crop_height) ||
        !std::isfinite(peripheral_scale) || !std::isfinite(foveal_density) ||
        !std::isfinite(gaze_u) || !std::isfinite(gaze_v) ||
        crop_width < .05f || crop_height < .05f ||
        crop_width > 1.f || crop_height > 1.f ||
        peripheral_scale < .05f || peripheral_scale > .50f ||
        foveal_density < .25f || foveal_density > 4.f ||
        gaze_u < 0.f || gaze_u > 1.f || gaze_v < 0.f || gaze_v > 1.f)
    {
        return {};
    }
    const auto round_size = [](float x) -> uint32_t {
        return static_cast<uint32_t>((std::max)(1.0f, std::round(x)));
    };
    const auto fw = round_size(output_width * crop_width * foveal_density);
    const auto fh = round_size(output_height * crop_height * foveal_density);
    const auto pw = round_size(output_width * peripheral_scale);
    const auto ph = round_size(output_height * peripheral_scale);
    // Match Joey's existing 2*W by H scene allocation for the initial
    // diagnostic. A more compact atlas is possible after DX12 validation.
    if (static_cast<uint64_t>(fw) + pw > 2ull * output_width ||
        (std::max)(fh, ph) > output_height) { return {}; }
    const float cu = std::clamp(gaze_u, crop_width * .5f, 1.f - crop_width * .5f);
    const float cv = std::clamp(gaze_v, crop_height * .5f, 1.f - crop_height * .5f);
    return Layout{
        .fovea = {0, 0, fw, fh},
        .periphery = {fw, 0, pw, ph},
        .atlas_width = output_width * 2,
        .atlas_height = output_height,
        .u0 = cu - crop_width * .5f,
        .u1 = cu + crop_width * .5f,
        .v0 = cv - crop_height * .5f,
        .v1 = cv + crop_height * .5f,
        .peripheral_scale = peripheral_scale,
        .crop_width = crop_width,
        .crop_height = crop_height
    };
}

inline std::optional<Tans> foveal_frustum(const Tans& full, const Layout& l) {
    if (!(std::isfinite(full.left) && std::isfinite(full.right) &&
          std::isfinite(full.top) && std::isfinite(full.bottom)) ||
        full.right <= full.left || full.top <= full.bottom) { return {}; }
    const float span_x = full.right - full.left;
    const float span_y = full.top - full.bottom;
    return Tans{
        .left = full.left + span_x * l.u0,
        .right = full.left + span_x * l.u1,
        .top = full.top - span_y * l.v0,
        .bottom = full.top - span_y * l.v1
    };
}

// Modify the x/y clip-space rows of ANY compatible GLM-style 4x4 perspective
// matrix, leaving depth and w untouched. Works for reversed-Z projections:
// maps full-frustum UV [u0,u1]x[v0,v1] to the entire cropped viewport.
template <typename Matrix>
void apply_foveal_crop(Matrix& matrix, const Layout& l) {
    const auto x_scale = 1.f / (l.u1 - l.u0);
    const auto y_scale = 1.f / (l.v1 - l.v0);
    const auto x_shift = (1.f - l.u0 - l.u1) * x_scale;
    const auto y_shift = (l.v0 + l.v1 - 1.f) * y_scale;
    for (int col = 0; col < 4; ++col) {
        const auto old_x = matrix[col][0];
        const auto old_y = matrix[col][1];
        const auto old_w = matrix[col][3];
        matrix[col][0] = old_x * x_scale + old_w * x_shift;
        matrix[col][1] = old_y * y_scale + old_w * y_shift;
    }
}

inline float foveal_blend(const Layout& l, float u, float v, float feather) {
    if (u < l.u0 || u > l.u1 || v < l.v0 || v > l.v1) return 0.f;
    if (feather <= 0.f) return 1.f;
    const auto du = (std::min)((u - l.u0) / l.crop_width, (l.u1 - u) / l.crop_width);
    const auto dv = (std::min)((v - l.v0) / l.crop_height, (l.v1 - v) / l.crop_height);
    const float edge = std::clamp((std::min)(du, dv) / feather, 0.f, 1.f);
    return edge * edge * (3.f - 2.f * edge);
}

inline uint64_t rendered_pixels(const Layout& l) {
    return static_cast<uint64_t>(l.fovea.width) * l.fovea.height +
           static_cast<uint64_t>(l.periphery.width) * l.periphery.height;
}

} // namespace uevr::duoview
