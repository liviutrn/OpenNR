#ifndef CROP_GEOMETRY_HEADER
#define CROP_GEOMETRY_HEADER "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
#endif
#ifndef CROP_HISTORY_HEADER
#define CROP_HISTORY_HEADER "../../runtime/open-shaders/src/Features/Upscaling/CropMotionHistory.h"
#endif
#include CROP_GEOMETRY_HEADER
#include CROP_HISTORY_HEADER
#include <cstdio>
#include <cstdlib>

using namespace FoveatedRenderImpl;

bool Near(double a, double b) { return std::abs(a - b) < 1e-6; }

int main()
{
    const CropMotion::History previous{{120, 112, 601, 561}, {2, 2}, 10, true};
    bool reset = false;
    auto offset = CropMotion::Offset(previous, {121, 112, 601, 561}, {2, 2}, 11, reset);
    if (reset || !Near(offset[0] * 1202.0, 1) || !Near(offset[1], 0)) return EXIT_FAILURE;
    std::puts("ordinary SR translation: compensated; no reset");
    for (unsigned failure = 0; failure < 5; ++failure) {
        auto history = previous;
        auto region = previous.region;
        auto scale = previous.scale;
        unsigned frame = 11;
        reset = false;
        if (failure == 0) history.valid = false;
        if (failure == 1) frame = 12;
        if (failure == 2) region.width -= 1;
        if (failure == 3) scale[0] = 1;
        if (failure == 4) reset = true;
        offset = CropMotion::Offset(history, region, scale, frame, reset);
        if (!reset || offset[0] != 0 || offset[1] != 0) return EXIT_FAILURE;
    }
    std::puts("invalid/discontinuous/resize/scale/explicit-reset protections: retained");
    reset = false;
    offset = CropMotion::Offset(previous, {421, 112, 601, 561}, {2, 2}, 11, reset);
#ifdef EXPECT_LARGE_JUMP_RESET
    if (!reset) return EXIT_FAILURE;
    std::puts("50%-crop jump: original v00 resets history");
#else
    if (reset) return EXIT_FAILURE;
    std::puts("50%-crop jump: current v6 retains history; original v00 would reset");
#endif

    std::puts("input_origin,output_origin,local_SR_history_shift,atlas_color_history_shift,disagreement");
    auto before = CropGeometry::MakeEyePlan(0.10010f, 0.1f, 0.5f, 0.5f, 1200,1200,2400,2400);
    for (float x : {0.10045f, 0.10090f}) {
        const auto current = CropGeometry::MakeEyePlan(x, 0.1f, 0.5f, 0.5f, 1200,1200,2400,2400);
        const double srShift = (double(current.input.x) - before.input.x) * 2;
        const double atlasShift = double(current.output.x) - before.output.x;
        std::printf("%u,%u,%.1f,%.1f,%.1f\n", current.input.x, current.output.x,
            srShift, atlasShift, atlasShift - srShift);
        if (Near(srShift, atlasShift)) return EXIT_FAILURE;
        before = current;
    }

    std::puts("crop_width,input_extent,output_extent,local_scale,full_eye_scale");
    for (float width : {0.5f, 0.4f, 0.3f}) {
        const auto crop = CropGeometry::MakeEyePlan(0.1f, 0.1f, width, width, 1202,1122,2404,2244);
        std::printf("%.2f,%u,%u,%.9f,2.000000000\n", width, crop.input.width, crop.output.width,
            double(crop.output.width) / crop.input.width);
    }

    std::puts("model_pct,legacy_compensated_color_shift,strict_color_shift");
    for (unsigned model : {1200u, 1020u, 840u}) {
        const float scale = 1200.0f * model / 1200.0f / 600.0f;
        const CropMotion::History nrPrevious{{240, 0, 1200, 1200}, {scale, scale}, 10, true};
        reset = false;
        offset = CropMotion::Offset(nrPrevious, {241, 0, 1200, 1200}, {scale, scale}, 11, reset);
        const double colorShift = offset[0] * 2400.0;
        if (reset || !Near(colorShift, 1200.0 / model)) return EXIT_FAILURE;
        std::printf("%u,%.9f,1.000000000\n", model * 100 / 1200, colorShift);
    }
    std::puts("same-position residual stabilization (mode 1): no crop-motion reprojection in shader");
    return EXIT_SUCCESS;
}
