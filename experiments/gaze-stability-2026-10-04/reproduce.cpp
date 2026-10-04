#ifndef CROP_GEOMETRY_HEADER
#define CROP_GEOMETRY_HEADER "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
#endif
#include CROP_GEOMETRY_HEADER
#include <cstdio>
#include <cstdlib>
#include <limits>

using namespace FoveatedRenderImpl::CropGeometry;

struct AxisMap {
    double scale, offset;
    double sample(double displayCenter) const { return displayCenter * scale + offset; }
};

AxisMap WorldToLocal(const PixelRect& input, unsigned fullInput, unsigned fullOutput, unsigned outputExtent)
{
    return {double(fullInput) * outputExtent / (double(fullOutput) * input.width),
        -double(input.x) * outputExtent / input.width};
}

double StripeArea(double begin, double end)
{
    double sum = 0;
    for (int x = int(std::floor(begin)); x < int(std::ceil(end)); ++x)
        sum += (x & 1) * std::max(0.0, std::min(end, double(x + 1)) - std::max(begin, double(x)));
    return sum / (end - begin);
}

double ModelProxy(double scene, double origin, double pitch)
{
    const double pixel = (scene - origin) / pitch - 0.5;
    const double left = std::floor(pixel), fraction = pixel - left;
    const double a = origin + left * pitch;
    return StripeArea(a, a + pitch) * (1.0 - fraction) + StripeArea(a + pitch, a + 2.0 * pitch) * fraction;
}

int main()
{
    std::puts("sample,input_origin,output_origin,marker_error_display_px,guide_error_render_px");
    for (float x : {0.10010f, 0.10045f, 0.10070f, 0.10090f}) {
        const auto eye = MakeEyePlan(x, 0.1f, 0.5f, 0.5f, 1600, 1600, 2400, 2400);
        const double scene = 1200.5;
        const double local = (scene / 1.5 - eye.input.x) * eye.output.width / eye.input.width;
        const double guide = eye.input.x + (scene - eye.output.x) * eye.input.width / eye.output.width;
        std::printf("%.7f,%u,%u,%.6f,%.6f\n", x, eye.input.x, eye.output.x,
            eye.output.x + local - scene, guide - scene / 1.5);
    }
    std::puts("sweep,input_width,output_width,crop_width,error_range_display_px,max_step_display_px,affine_residual_px");
    for (auto dimensions : {std::array<unsigned,2>{1600,2400}, {1600,1600}, {1703,2555}, {1703,2400}}) {
        for (float width : {0.5f, 0.6f, 0.8f}) {
            double minimum = std::numeric_limits<double>::infinity(), maximum = -minimum;
            double previous = 0, maxStep = 0, residual = 0;
            const double fullScale = double(dimensions[1]) / dimensions[0];
            const double scene = dimensions[1] * 0.5 + 0.5;
            for (unsigned frame = 0; frame < 10001; ++frame) {
                const float x = 0.05f + frame * 0.000005f;
                const auto eye = MakeEyePlan(x, x, width, width,
                    dimensions[0], dimensions[0], dimensions[1], dimensions[1]);
                const double local = (scene / fullScale - eye.input.x) * eye.output.width / eye.input.width;
                const double error = eye.output.x + local - scene;
                minimum = std::min(minimum, error);
                maximum = std::max(maximum, error);
                if (frame) maxStep = std::max(maxStep, std::abs(error - previous));
                previous = error;
                const auto map = WorldToLocal(eye.input, dimensions[0], dimensions[1], eye.output.width);
                const double corrected = (eye.input.x + map.sample(scene) * eye.input.width / eye.output.width) * fullScale;
                residual = std::max(residual, std::abs(corrected - scene));
            }
            std::printf("moving,%u,%u,%.2f,%.9f,%.9f,%.12f\n", dimensions[0], dimensions[1], width,
                maximum - minimum, maxStep, residual);
            if (residual > 1e-9 || (dimensions[0] == dimensions[1] && maximum - minimum > 1e-9))
                return EXIT_FAILURE;
        }
    }
    std::puts("NR_proxy,origin,local_grid_sample,global_grid_sample");
    double minimum = 1, maximum = 0;
    const double pitch = 1000.0 / 700.0;
    const double stable = ModelProxy(550.5, 0, pitch);
    for (unsigned origin = 100; origin < 111; ++origin) {
        const double local = ModelProxy(550.5, origin, pitch);
        const double anchoredOrigin = std::floor(origin / pitch) * pitch;
        const double anchored = ModelProxy(550.5, anchoredOrigin, pitch);
        std::printf("70pct,%u,%.9f,%.9f\n", origin, local, anchored);
        minimum = std::min(minimum, local);
        maximum = std::max(maximum, local);
        if (std::abs(anchored - stable) > 1e-10) return EXIT_FAILURE;
    }
    if (maximum - minimum < 0.01) return EXIT_FAILURE;
    std::printf("NR_proxy_range,%.9f\n", maximum - minimum);
    return EXIT_SUCCESS;
}
