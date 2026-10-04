#include "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/Bridge.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/CropMotionHistory.h"

#include <cassert>
#include <iostream>
#include <random>

using namespace FoveatedRenderImpl;

int main()
{
    std::mt19937 rng(24);
    std::uniform_real_distribution<float> origins(0.0f, 0.5f);
    unsigned oldPhaseErrors = 0;
    for (unsigned input : { 1201u, 1202u, 1700u }) {
        for (unsigned output : { input, input * 2u, input * 3u / 2u, 2404u }) {
            for (float coverage : { 0.30f, 0.40f, 0.50f, 0.75f }) {
                for (unsigned n = 0; n < 400; ++n) {
                    const float origin = origins(rng);
                    CropGeometry::FramePlan plan{ input, input, output, output, {} };
                    const auto eye = CropGeometry::MakeEyePlan(origin, origin, coverage, coverage, input, input, output, output);
                    plan.eyes = { eye, eye };
                    assert(eye.input.width && eye.output.width);
                    assert(eye.output.x + eye.output.width <= output);
                    const auto color = CropGeometry::ColorSampling(plan, 0);
                    const auto guide = CropGeometry::GuideSampling(plan, 0);
                    const double localDisplay = 0.5 * eye.output.width;
                    const double localSR = localDisplay * color.scale[0] + color.offset[0];
                    const double worldFromSR = (eye.input.x + localSR * eye.input.width / eye.output.width) * output / input;
                    const double worldDisplay = eye.output.x + localDisplay;
                    assert(std::abs(worldFromSR - worldDisplay) < 0.0002);
                    const double localGuide = (localDisplay * eye.input.width / eye.output.width) * guide.scale[0] + guide.offset[0];
                    const double worldFromGuide = (eye.input.x + localGuide) * output / input;
                    assert(std::abs(worldFromGuide - worldDisplay) < 0.0002);
                    if (output == input * 2u) {
                        assert(eye.output.x == eye.input.x * 2u);
                        assert(eye.output.width == eye.input.width * 2u);
                        assert((color.scale == std::array<float, 2>{ 1, 1 }));
                        assert((color.offset == std::array<float, 2>{}));
                        const auto old = CropGeometry::MakePixelRect(origin, origin, coverage, coverage, output, output);
                        if (old.x != eye.input.x * 2u || old.width != eye.input.width * 2u) ++oldPhaseErrors;
                    }
                    // A world point must land on the same crop-local ray used by depth.
                    const auto clip = CropGeometry::ClipTransform(input, input, eye.input);
                    const double fullX = 2.0 * (eye.input.x + eye.input.width * 0.37) / input - 1.0;
                    const double fullY = 1.0 - 2.0 * (eye.input.y + eye.input.height * 0.63) / input;
                    assert(std::abs(fullX * clip[0] + clip[2] - (2.0 * 0.37 - 1.0)) < 0.000001);
                    assert(std::abs(fullY * clip[1] + clip[3] - (1.0 - 2.0 * 0.63)) < 0.000001);
                }
            }
        }
    }
    assert(oldPhaseErrors > 1000);

    // Retained history must follow the scene marker, including real head motion.
    for (unsigned percent : { 100u, 85u, 70u }) {
        for (unsigned currentWidth : { 721u, 961u, 1202u }) {
            const unsigned currentModel = (currentWidth * percent + 50u) / 100u;
            const auto current = CropGeometry::ModelSampling(currentWidth, currentWidth, currentModel, currentModel, percent, 241, 301, true);
            for (unsigned previousPercent : { 100u, 85u, 70u }) {
                const unsigned previousWidth = 1202;
                const unsigned previousModel = (previousWidth * previousPercent + 50u) / 100u;
                const auto previous = CropGeometry::ModelSampling(previousWidth, previousWidth, previousModel, previousModel, previousPercent, 239, 299, true);
                for (double headMotion : { -2.5, 0.0, 1.75 }) {
                    const double modelPosition = 100.5;
                    const double colorPosition = modelPosition * current[0] + current[2];
                    const double previousColor = colorPosition + 241 - 239 + headMotion;
                    const double previousPosition = (previousColor - previous[2]) / previous[0];
                    const double previousWorld = 239 + previousPosition * previous[0] + previous[2];
                    const double currentWorld = 241 + colorPosition;
                    assert(std::abs(previousWorld - (currentWorld + headMotion)) < 0.000001);
                    // Round-trip model resolve preserves the display pixel location.
                    const double resolvedPosition = (colorPosition - current[2]) / current[0];
                    assert(std::abs(resolvedPosition - modelPosition) < 0.000001);
                }
            }
            const auto flat = CropGeometry::ModelSampling(currentWidth, currentWidth, currentModel, currentModel, percent, 241, 301, false);
            assert(std::abs(flat[0] * currentModel - currentWidth) < 0.0002f);
            assert(flat[2] == 0 && flat[3] == 0);
            for (unsigned x = 238; x <= 244; ++x) {
                const auto grid = CropGeometry::ModelSampling(currentWidth, currentWidth, currentModel, currentModel, percent, x, 0, true);
                const double globalCenter = x + (100.5 * grid[0] + grid[2]);
                const double latticeIndex = globalCenter * percent / 100.0 - 0.5;
                assert(std::abs(latticeIndex - std::round(latticeIndex)) < 0.00002);
            }
        }
        const float fullColor = 2404;
        const unsigned colorWidth = 1202;
        const float scale = fullColor / colorWidth;
        const CropMotion::History history{ { 239, 299, colorWidth, 1202 }, { scale, scale }, 10, true };
        bool reset = false;
        const auto offset = CropMotion::Offset(history, { 241, 301, colorWidth, 1202 }, { scale, scale }, 11, reset);
        assert(!reset);
        // Physical crop displacement cannot vary with NR model resolution.
        assert(std::abs(offset[0] * fullColor - 2.0f) < 0.000001f);
    }
    CropGeometry::FramePlan first{ 1202, 1202, 2404, 2404, {} };
    first.eyes.fill(CropGeometry::MakeEyePlan(0.1f, 0.1f, 0.5f, 0.5f, 1202, 1202, 2404, 2404));
    Bridge::SetCropForFrame(10, first);
    Bridge::CommitCropFrame(true);
    assert(Bridge::cropHistoryValid && Bridge::previousCropFrame == 10);
    Bridge::SetCropForFrame(11, {});
    Bridge::CommitCropFrame(false);
    assert(!Bridge::cropHistoryValid && Bridge::previousCropFrame == 10);
    assert(Bridge::previousCrop.eyes[0].input.x == first.eyes[0].input.x);
    std::cout << "Crop/world/guide alignment, retained model history, flat parity, and successful-frame ownership passed; old mismatches=" << oldPhaseErrors << '\n';
}
