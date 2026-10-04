#include "../../runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
#include "../../runtime/open-shaders/src/Features/Upscaling/GazeCropPolicy.h"

#include <cassert>
#include <iostream>

int main()
{
    using namespace FoveatedRenderImpl;
    for (unsigned color : { 500u, 1201u, 2404u, 3400u }) {
        for (unsigned guide : { color, color * 2u / 3u, color / 2u }) {
            for (unsigned percent : { 100u, 85u, 70u }) {
                const unsigned model = color * percent / 100u;
                const float guideScale = static_cast<float>(guide) * 2.0f;
                const float legacy = guideScale * static_cast<float>(model) / color;
                const float native = CropGeometry::NativeGuideMotionScale(guideScale, model, color);
                assert(native == legacy);
                if (percent == 100u) assert(native == guideScale);
                if (guide != color) {
                    const float broken = guideScale * static_cast<float>(model) / guide;
                    assert(std::abs(broken / native - static_cast<float>(color) / guide) < 0.000001f);
                }
            }
        }
    }
    const std::array<float, 2> previous{ 0.5f, 0.5f };
    for (float displacement : { -0.00001f, 0.00001f, 0.0001f, 0.1f }) {
        const std::array<float, 2> sample{ 0.5f + displacement, 0.5f - displacement };
        assert(GazeCropPolicy::Filter(previous, sample, 11.1f, 0.0f, 3400, 3172) == sample);
        const float desired = sample[0] - 0.25f;
        assert(GazeCropPolicy::ResolveOrigin(0.25f, sample[0], 0.5f, 3400, 0, true, false, 0.0f) == desired);
        assert(GazeCropPolicy::ResolveOrigin(0.25f, sample[0], 0.5f, 3400, 0, true, true, 0.0f) == desired);
    }
    assert(GazeCropPolicy::ResolveOrigin(0.25f, 0.501f, 0.5f, 3400, 0, true, true, 1.0f) == 0.25f);
    assert(CropGeometry::NativeGuideMotionScale(10.0f, 10, 0) == 0.0f);
    std::cout << "Native atlas/legacy guide-scale parity and zero-lag gaze tests passed\n";
}
