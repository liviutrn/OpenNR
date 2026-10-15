#pragma once
// v46 renderer-side temporal math.
//
// Unreal's FMatrix multiplies row vectors and is laid out as M[row][column].
// Joey/UESDK exposes the same 128 bytes through a GLM-shaped Matrix4x4d, so
// the frame snapshots below are kept as the physical 16-double payload and
// are converted to an explicit row-major semantic matrix only while doing
// the calculation.  This keeps the crop operation identical to the existing
// production projection hook while making the temporal transform testable
// without UE or D3D headers.
#include "DuoViewFrame.hpp"
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <utility>

namespace uevr::duoview::temporal {

using RawMatrix4d = std::array<double, 16>;

struct Matrix4d {
    // Explicit Unreal semantic indexing: [row][column].
    double m[4][4]{};
};

struct ViewInput {
    std::array<float, 16> projection{}; // Physical FMatrix bytes.
    Layout layout{};
    uint32_t fovea_view{};
    std::array<double, 3> origin{};
    RawMatrix4d view_rotation{}; // Physical FMatrix bytes.
    bool valid{};
};

inline Matrix4d load_raw(const RawMatrix4d& raw) {
    Matrix4d result{};
    for (int row = 0; row < 4; ++row)
        for (int col = 0; col < 4; ++col)
            result.m[row][col] = raw[static_cast<size_t>(row * 4 + col)];
    return result;
}

inline RawMatrix4d store_raw(const Matrix4d& matrix) {
    RawMatrix4d result{};
    for (int row = 0; row < 4; ++row)
        for (int col = 0; col < 4; ++col)
            result[static_cast<size_t>(row * 4 + col)] = matrix.m[row][col];
    return result;
}

inline Matrix4d multiply(const Matrix4d& a, const Matrix4d& b) {
    Matrix4d result{};
    for (int row = 0; row < 4; ++row) {
        for (int col = 0; col < 4; ++col) {
            double value = 0.0;
            for (int k = 0; k < 4; ++k)
                value += a.m[row][k] * b.m[k][col];
            result.m[row][col] = value;
        }
    }
    return result;
}

inline Matrix4d identity() {
    Matrix4d result{};
    for (int i = 0; i < 4; ++i) result.m[i][i] = 1.0;
    return result;
}

inline bool finite(const Matrix4d& matrix) {
    for (const auto& row : matrix.m)
        for (const double value : row)
            if (!std::isfinite(value)) return false;
    return true;
}

inline std::optional<Matrix4d> inverse(const Matrix4d& input) {
    if (!finite(input)) return {};
    double augmented[4][8]{};
    for (int row = 0; row < 4; ++row) {
        for (int col = 0; col < 4; ++col) augmented[row][col] = input.m[row][col];
        augmented[row][row + 4] = 1.0;
    }
    constexpr double epsilon = 1.0e-12;
    for (int pivot_col = 0; pivot_col < 4; ++pivot_col) {
        int pivot_row = pivot_col;
        double pivot_abs = std::abs(augmented[pivot_row][pivot_col]);
        for (int row = pivot_col + 1; row < 4; ++row) {
            const double candidate = std::abs(augmented[row][pivot_col]);
            if (candidate > pivot_abs) {
                pivot_abs = candidate;
                pivot_row = row;
            }
        }
        if (!std::isfinite(pivot_abs) || pivot_abs <= epsilon) return {};
        if (pivot_row != pivot_col) {
            for (int col = 0; col < 8; ++col)
                std::swap(augmented[pivot_row][col], augmented[pivot_col][col]);
        }
        const double pivot = augmented[pivot_col][pivot_col];
        for (int col = 0; col < 8; ++col) augmented[pivot_col][col] /= pivot;
        for (int row = 0; row < 4; ++row) {
            if (row == pivot_col) continue;
            const double factor = augmented[row][pivot_col];
            if (factor == 0.0) continue;
            for (int col = 0; col < 8; ++col)
                augmented[row][col] -= factor * augmented[pivot_col][col];
        }
    }
    Matrix4d result{};
    for (int row = 0; row < 4; ++row)
        for (int col = 0; col < 4; ++col)
            result.m[row][col] = augmented[row][col + 4];
    return finite(result) ? std::optional<Matrix4d>{result} : std::nullopt;
}

inline Matrix4d translation(const std::array<double, 3>& origin) {
    auto result = identity();
    // FTranslationMatrix(-ViewOrigin) uses the final row for UE row vectors.
    result.m[3][0] = -origin[0];
    result.m[3][1] = -origin[1];
    result.m[3][2] = -origin[2];
    return result;
}

inline Matrix4d projection_for_view(const ViewInput& input, unsigned view) {
    RawMatrix4d raw{};
    for (size_t i = 0; i < raw.size(); ++i) raw[i] = input.projection[i];
    auto result = load_raw(raw);
    if (view == input.fovea_view) {
        const double x_scale = 1.0 / (input.layout.u1 - input.layout.u0);
        const double y_scale = 1.0 / (input.layout.v1 - input.layout.v0);
        const double x_shift = (1.0 - input.layout.u0 - input.layout.u1) * x_scale;
        const double y_shift = (input.layout.v0 + input.layout.v1 - 1.0) * y_scale;
        for (int row = 0; row < 4; ++row) {
            const double old_x = result.m[row][0];
            const double old_y = result.m[row][1];
            const double old_w = result.m[row][3];
            result.m[row][0] = old_x * x_scale + old_w * x_shift;
            result.m[row][1] = old_y * y_scale + old_w * y_shift;
        }
    }
    return result;
}

inline Matrix4d view_projection_for_view(const ViewInput& input, unsigned view) {
    const RawMatrix4d rotation_raw = input.view_rotation;
    return multiply(multiply(translation(input.origin), load_raw(rotation_raw)),
                    projection_for_view(input, view));
}

// Unreal's ClipToPrevClipOverride is populated by nDisplay as
// InvViewProj * PrevViewProj.  Both matrices here use the same row-vector
// convention and exclude temporal AA jitter, matching ComputeProjectionNoAA.
inline std::optional<RawMatrix4d> make_clip_to_prev_clip(
    const ViewInput& previous, const ViewInput& current, unsigned view) {
    if (!previous.valid || !current.valid || view > 1 || view >= 2 ||
        !layout_valid(previous.layout) || !layout_valid(current.layout)) return {};
    const auto current_view_projection = view_projection_for_view(current, view);
    const auto previous_view_projection = view_projection_for_view(previous, view);
    const auto inverse_current = inverse(current_view_projection);
    if (!inverse_current) return {};
    const auto result = multiply(*inverse_current, previous_view_projection);
    return finite(result) ? std::optional<RawMatrix4d>{store_raw(result)} : std::nullopt;
}

inline std::array<double, 4> transform_row(
    const std::array<double, 4>& vector, const Matrix4d& matrix) {
    std::array<double, 4> result{};
    for (int col = 0; col < 4; ++col)
        for (int row = 0; row < 4; ++row)
            result[col] += vector[row] * matrix.m[row][col];
    return result;
}

inline std::array<double, 4> transform_raw_row(
    const std::array<double, 4>& vector, const RawMatrix4d& raw) {
    return transform_row(vector, load_raw(raw));
}

} // namespace uevr::duoview::temporal
