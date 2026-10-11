#!/usr/bin/env python3
"""Reproducible Cheeky v0.5.5 port: PSVR2 OpenXR fallback and OpenNR r10 gaze stability.
Strict source anchors: exit rather than silently patching an incompatible version.
"""
from pathlib import Path
import argparse
import shutil

p = argparse.ArgumentParser()
p.add_argument("cheeky", type=Path)
p.add_argument("--overrides", type=Path, required=True)
args = p.parse_args()
root = args.cheeky.resolve()
overrides = args.overrides.resolve()

def replace_once(file, needle, replacement):
    path = root / file
    text = path.read_text(encoding="utf-8")
    count = text.count(needle)
    if count != 1:
        raise RuntimeError(f"{file}: expected one anchor, found {count} for {needle[:100]!r}")
    path.write_text(text.replace(needle, replacement), encoding="utf-8")
    print(f"PATCHED {file}: {needle[:65]!r}")

for rel in ["openxr_layer/psvr2_native_gaze.hpp", "src/OpenNR_R10_GazeCropPolicy.h"]:
    dest = root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(overrides / rel, dest)
    print(f"IMPORTED {rel}")

# Fix A: Use the installed Toolkit's CAPI as an alternate input source only
# after the normal OpenXR action path fails. Leave every game input action untouched.
replace_once("openxr_layer/openxr_layer.cpp",
    '#include "projection_selection.hpp"',
    '#include "projection_selection.hpp"\n#include "psvr2_native_gaze.hpp"')
replace_once("openxr_layer/openxr_layer.cpp",
    '    const bool orientation_valid =\n        (gaze_location.locationFlags &',
    '''    // PSVR2 native fallback: neither create nor synchronize extra OpenXR
    // actions; use the Toolkit's calibrated head-relative gaze when OpenXR
    // did not publish a usable orientation.
    bool native_psvr2_valid = false;
    if (!simulated && view_state != nullptr &&
        (view_state->viewStateFlags & XR_VIEW_STATE_ORIENTATION_VALID_BIT) != 0 &&
        (gaze_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) == 0) {
        XrQuaternionf local_gaze{};
        if (cheeky_psvr2::read_orientation(local_gaze)) {
            auto head = effective_views[0].pose.orientation;
            const auto right = effective_views[1].pose.orientation;
            const float dot = head.x*right.x + head.y*right.y + head.z*right.z + head.w*right.w;
            const float sign = dot < 0.F ? -1.F : 1.F;
            head.x += sign*right.x; head.y += sign*right.y;
            head.z += sign*right.z; head.w += sign*right.w;
            const float length = std::sqrt(head.x*head.x + head.y*head.y +
                head.z*head.z + head.w*head.w);
            if (length > 0.0001F) {
                head.x /= length; head.y /= length; head.z /= length; head.w /= length;
                gaze_location.pose.orientation = multiply_rotation(head, local_gaze);
                for (int axis = 0; axis < 3; ++axis) {
                    float a = axis == 0 ? effective_views[0].pose.position.x :
                        axis == 1 ? effective_views[0].pose.position.y : effective_views[0].pose.position.z;
                    float b = axis == 0 ? effective_views[1].pose.position.x :
                        axis == 1 ? effective_views[1].pose.position.y : effective_views[1].pose.position.z;
                    float average = (a + b) * 0.5F;
                    if (axis == 0) gaze_location.pose.position.x = average;
                    else if (axis == 1) gaze_location.pose.position.y = average;
                    else gaze_location.pose.position.z = average;
                }
                gaze_location.locationFlags |= XR_SPACE_LOCATION_ORIENTATION_VALID_BIT;
                sample_time.time = locate_info->displayTime;
                action_active = true;
                native_psvr2_valid = true;
            }
        }
    }
    const bool orientation_valid =
        (gaze_location.locationFlags &''')
replace_once("openxr_layer/openxr_layer.cpp",
    '            state.gaze_valid = action_active && projections_valid &&\n                !state.unsupported_view_configuration;',
    '''            state.gaze_valid = action_active && projections_valid &&
                !state.unsupported_view_configuration;
            if (native_psvr2_valid) state.system_supported = true;''')

# Fix B stage 1: exact r10 fixation noise policy. Bypass filter on deliberate
# eye movement >2 px; this also removes delayed smoothing of saccades.
replace_once("src/gaze_foveation.cpp",
    '#include "gaze_foveation.hpp"',
    '#include "gaze_foveation.hpp"\n#include "OpenNR_R10_GazeCropPolicy.h"')
replace_once("src/gaze_policy.cpp",
    '#include "gaze_policy.hpp"',
    '#include "gaze_policy.hpp"\n#include "OpenNR_R10_GazeCropPolicy.h"')
replace_once("src/gaze_policy.hpp",
    '    bool sample_valid{};\n};\n\nstruct GazeTemporalPolicyResult',
    '    bool sample_valid{};\n    std::uint32_t view_width{}, view_height{};\n};\n\nstruct GazeTemporalPolicyResult')
replace_once("src/gaze_policy.cpp",
    '''                state.filtered_u += static_cast<float>(
                    alpha * (raw_u - state.filtered_u)
                );
                state.filtered_v += static_cast<float>(
                    alpha * (raw_v - state.filtered_v)
                );''',
    '''                if (input.view_width != 0 && input.view_height != 0) {
                    // This is exactly OpenNR r10's Filter() policy.
                    const auto v = FoveatedRenderImpl::GazeCropPolicy::Filter(
                        {state.filtered_u, state.filtered_v}, {raw_u, raw_v},
                        static_cast<float>(dt * 1000.0), input.smoothing_ms,
                        input.view_width, input.view_height);
                    state.filtered_u = v[0];
                    state.filtered_v = v[1];
                } else {
                    // Preserve the original behavior for existing unit tests
                    // that do not supply an output grid.
                    state.filtered_u += static_cast<float>(
                        alpha * (raw_u - state.filtered_u));
                    state.filtered_v += static_cast<float>(
                        alpha * (raw_v - state.filtered_v));
                }''')
replace_once("src/gaze_foveation.cpp",
    'settings.gaze_smoothing_ms, gaze_hold_seconds(settings), gaze_return_seconds, valid});',
    'settings.gaze_smoothing_ms, gaze_hold_seconds(settings), gaze_return_seconds, valid, rw, rh});')
replace_once("src/gaze_foveation.cpp",
    '''             use_sample,
         }
     );''',
    '''             use_sample,
             render_width, render_height,
         }
     );''') if False else None
replace_once("src/gaze_foveation.cpp",
    '''             use_sample,
         }
     );'''.replace("             ", "            "),
    '''             use_sample,
             render_width, render_height,
         }
     );'''.replace("             ", "            ")) if False else None
# More robust direct anchor for the normal path.
replace_once("src/gaze_foveation.cpp",
    '''            use_sample,
        }
    );''',
    '''            use_sample,
            render_width, render_height,
        }
    );''')

# R10 stable center guard: prefer exactly the prior crop origin inside the
# fixation guard; do not slew the crop on larger deliberate gaze movements.
replace_once("src/gaze_foveation.cpp",
    '''    const auto reset_result = evaluate_gaze_reset(
        {
            state.last_crop.input_base_x,''',
    '''    // r10's ResolveOrigin() is applied only when crop dimensions match,
    // never when the user changed crop size or tracking geometry.
    if (state.has_crop && render_width && render_height &&
        state.last_crop.input_width == crop.input_width &&
        state.last_crop.input_height == crop.input_height) {
        const float xextent = static_cast<float>(crop.input_width) / render_width;
        const float yextent = static_cast<float>(crop.input_height) / render_height;
        const float xorigin = FoveatedRenderImpl::GazeCropPolicy::ResolveOrigin(
            static_cast<float>(state.last_crop.input_base_x) / render_width,
            temporal_result.center_u, xextent, render_width,
            settings.gaze_quantization_pixels, true);
        const float yorigin = FoveatedRenderImpl::GazeCropPolicy::ResolveOrigin(
            static_cast<float>(state.last_crop.input_base_y) / render_height,
            temporal_result.center_v, yextent, render_height,
            settings.gaze_quantization_pixels, true);
        CropGeometry stabilized{};
        if (calculate_foveation_geometry_at_center(
                foveation_parameters(fixed_settings),
                {xorigin + 0.5F*xextent, yorigin + 0.5F*yextent, 1U},
                render_width, render_height, output_width, output_height,
                output_origin_x, output_origin_y, stabilized) &&
            stabilized.input_width == crop.input_width &&
            stabilized.input_height == crop.input_height) {
            crop = stabilized;
        }
    }
    const auto reset_result = evaluate_gaze_reset(
        {
            state.last_crop.input_base_x,''')
# Preserve history across reacquisition when eye identity, origin, and shape
# remain compatible. Still reset if the crop moves completely out of overlap.
replace_once("src/gaze_policy.cpp",
    '''    } else if (reacquired) {
        result.reason = GazeResetReason::reacquired;
    } else if (remapped) {''',
    '''    } else if (reacquired && !previous.valid) {
        result.reason = GazeResetReason::reacquired;
    } else if (remapped) {''')
replace_once("src/gaze_policy.cpp",
    '''        const auto threshold_x = (std::max)(
            64U,
            static_cast<std::uint32_t>(std::lround(current.width * ratio))
        );
        const auto threshold_y = (std::max)(
            64U,
            static_cast<std::uint32_t>(std::lround(current.height * ratio))
        );''',
    '''        // The original 12.5%-of-crop threshold resets on normal saccades.
        // Reuse overlapping history and let per-backend MV correction handle
        // movement. Do not reuse history when the two crops do not overlap.
        // Fixed/automatic alignment is not a moving eye-tracked crop:
        // keep Cheeky's original safety reset for substantial fallback jumps.
        // For valid tracked gaze, reset only when overlap is exhausted.
        const auto threshold_x = using_valid_sample ? current.width : (std::max)(
            64U, static_cast<std::uint32_t>(std::lround(current.width * ratio)));
        const auto threshold_y = using_valid_sample ? current.height : (std::max)(
            64U, static_cast<std::uint32_t>(std::lround(current.height * ratio)));''')

# Update Cheeky's old regression expectations to match overlap-based r10 policy.
replace_once("tests/gaze_tests.cpp",
    '''    expect(result.reason == GazeResetReason::large_jump,
        "origin jump at the 64-pixel floor resets history");''',
    '''    expect(result.reason == GazeResetReason::none,
        "overlapping 64px gaze movement preserves history");''')
replace_once("tests/gaze_tests.cpp",
    '''    expect(result.reason == GazeResetReason::large_jump,
        "origin jump above 64 pixels resets history");''',
    '''    expect(result.reason == GazeResetReason::none,
        "overlapping 80px gaze movement preserves history");
    const GazeCropPolicyState no_overlap{520U, 100U, 400U, 300U, true};
    result = evaluate_gaze_reset(first, no_overlap, true, false, false, 0.125F);
    expect(result.reason == GazeResetReason::large_jump,
        "history resets only on non-overlapping gaze movement");''')

# Expose a small, isolated CLI regression suite that cannot accidentally
# hang in heavyweight graphics fixture tests on a headless CI runner.
replace_once("tests/gaze_tests.cpp",
    'int main(int argc, char** argv) {',
    '''int main(int argc, char** argv) {
    if (argc == 2 && std::strcmp(argv[1], "--opennr-r10-gaze") == 0) {
        test_reset_policy();
        test_temporal_policy();
        return failures == 0 ? 0 : 1;
    }''')
print("Cheeky v0.5.5 PSVR2/OpenNR-r10 source port applied successfully")
