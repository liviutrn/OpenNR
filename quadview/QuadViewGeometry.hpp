#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>

namespace uevr::quadview {

struct Rect {
    uint32_t x{}, y{}, width{}, height{};
    friend bool operator==(const Rect&, const Rect&) = default;
};

struct Crop {
    float u0{}, v0{}, u1{1.f}, v1{1.f};
};

struct Layout {
    // Engine view order is explicitly zero based:
    // 0 left context, 1 right context, 2 left focus, 3 right focus.
    std::array<Rect, 4> views{};
    uint32_t eye_width{}, eye_height{}, atlas_width{}, atlas_height{};
    Crop focus_crop{};
    float context_scale{};
};

inline std::optional<Layout> make_layout(
    uint32_t eye_width, uint32_t eye_height,
    float crop_width = .50f, float crop_height = .50f,
    float context_scale = .20f, float focus_density = 1.f,
    float focus_u = .50f, float focus_v = .50f)
{
    if (!eye_width || !eye_height || eye_width > 8192 || eye_height > 8192 ||
        !std::isfinite(crop_width) || !std::isfinite(crop_height) ||
        !std::isfinite(context_scale) || !std::isfinite(focus_density) ||
        !std::isfinite(focus_u) || !std::isfinite(focus_v) ||
        crop_width < .05f || crop_width > 1.f || crop_height < .05f || crop_height > 1.f ||
        context_scale < .05f || context_scale > .5f || focus_density < .25f || focus_density > 2.f ||
        focus_u < 0.f || focus_u > 1.f || focus_v < 0.f || focus_v > 1.f) return {};

    const auto rounded = [](float value) {
        return static_cast<uint32_t>((std::max)(1.0f, std::round(value)));
    };
    const auto context_width = rounded(eye_width * context_scale);
    const auto context_height = rounded(eye_height * context_scale);
    const auto focus_width = rounded(eye_width * crop_width * focus_density);
    const auto focus_height = rounded(eye_height * crop_height * focus_density);
    // The pair is packed horizontally within each eye's existing half of the
    // 2W x H render target. The crops preserve each source rectangle's aspect.
    if (uint64_t(context_width) + focus_width > eye_width ||
        context_height > eye_height || focus_height > eye_height) return {};

    const float cu = std::clamp(focus_u, crop_width * .5f, 1.f - crop_width * .5f);
    const float cv = std::clamp(focus_v, crop_height * .5f, 1.f - crop_height * .5f);
    Layout result{};
    result.eye_width = eye_width;
    result.eye_height = eye_height;
    result.atlas_width = eye_width * 2;
    result.atlas_height = eye_height;
    result.focus_crop = {cu - crop_width * .5f, cv - crop_height * .5f,
                         cu + crop_width * .5f, cv + crop_height * .5f};
    result.context_scale = context_scale;
    for (uint32_t eye = 0; eye != 2; ++eye) {
        const auto base_x = eye * eye_width;
        result.views[eye] = {base_x, 0, context_width, context_height};
        result.views[eye + 2] = {base_x + context_width, 0, focus_width, focus_height};
    }
    return result;
}

constexpr bool valid_view_index(int32_t index) { return index >= 0 && index < 4; }
constexpr uint32_t eye_for_view(uint32_t index) { return index & 1u; }
constexpr bool is_focus_view(uint32_t index) { return index >= 2u && index < 4u; }

template <typename Matrix>
inline void apply_focus_crop(Matrix& matrix, const Crop& crop) {
    const auto width = crop.u1 - crop.u0;
    const auto height = crop.v1 - crop.v0;
    if (!(std::isfinite(width) && std::isfinite(height)) || width <= 0.f || height <= 0.f) return;
    const auto x_scale = 1.f / width;
    const auto y_scale = 1.f / height;
    const auto x_shift = (1.f - crop.u0 - crop.u1) * x_scale;
    const auto y_shift = (crop.v0 + crop.v1 - 1.f) * y_scale;
    for (int col = 0; col != 4; ++col) {
        const auto old_x = matrix[col][0];
        const auto old_y = matrix[col][1];
        const auto old_w = matrix[col][3];
        matrix[col][0] = old_x * x_scale + old_w * x_shift;
        matrix[col][1] = old_y * y_scale + old_w * y_shift;
    }
}

} // namespace uevr::quadview
