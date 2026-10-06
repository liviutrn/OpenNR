#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/OutsideTonePolicy.h"
#include <cassert>
#include <iostream>
#include <limits>
#include <random>

using namespace NeuralRendering::OutsideTone;
int main()
{
    std::mt19937 rng(37);
    unsigned protectedPixels = 0, outerPixels = 0;
    Config c;
    for (bool oval : { false, true }) {
        for (float scale : { 1.0f, 0.8f, 0.6f }) {
            for (unsigned i = 0; i < 200; ++i) {
                const unsigned eyeX = (i & 1u) ? 1202u : 0u;
                Geometry g{ eyeX + std::uint32_t(rng() % 602u), std::uint32_t(rng() % 602u), 600, 600, eyeX, 1202, 1202, oval, scale };
                const auto roi = MakeRegion(g, c.width);
                assert(roi.width && roi.height);
                assert(roi.x >= eyeX && roi.x + roi.width <= eyeX + 1202);
                assert(roi.y + roi.height <= 1202);
                for (unsigned n = 0; n < 1000; ++n) {
                    const float x = float(int(rng() % 1000u) - 200);
                    const float y = float(int(rng() % 1000u) - 200);
                    // Independent membership from r2 SubrectBlendCS's implicit ellipse / rectangle.
                    bool inside;
                    if (oval) {
                        const float dx = (x + 0.5f - 300) / (300 * scale);
                        const float dy = (y + 0.5f - 300) / (300 * scale);
                        inside = dx*dx + dy*dy <= 1;
                    } else {
                        const float inset = 600 * (1-scale) * 0.5f;
                        inside = x >= inset && x <= 599-inset && y >= inset && y <= 599-inset;
                    }
                    const float d = Distance(x, y, g);
                    const float w = Weight(d, c, float(rng() % 1000u) / 999);
                    assert(std::isfinite(w) && w >= 0 && w <= 1);
                    if (inside) { assert(w == 0); ++protectedPixels; }
                    else if (d < c.width) ++outerPixels;
                }
            }
        }
    }
    assert(protectedPixels > 100000 && outerPixels > 100000);
    assert(Weight(0, c, 1) == 0 && Weight(c.width, c, 1) == 0);
    assert(Weight(0.0001f, c, 1) < 0.000001f);
    assert(Weight(c.width - 0.001f, c, 1) < 0.000001f);
    for (unsigned i = 1; i < 1000; ++i) {
        const float d = c.width * float(i) / 1000;
        const float a = Weight(d, c, 0), b = Weight(d, c, 1);
        assert(b-a <= c.dither * 0.005f + 0.000001f);
    }
    Geometry invalid{ 1190, 0, 40, 50, 0, 1202, 1202, false, 1 };
    assert(MakeRegion(invalid, 128).width == 0); // never cross SBS eye split
    assert(MakeRegion(invalid, std::numeric_limits<float>::infinity()).width == 0);
    c.width = std::numeric_limits<float>::quiet_NaN(); c.curve = -100; c.color = 100;
    c = Sanitize(c);
    assert(c.width == 128 && c.curve == 0.25f && c.color == 2);
    std::cout << "Outside mask protection, eye isolation, adaptive geometry, fade continuity, bounded static dither and invalid settings passed; protected=" << protectedPixels << ", outer=" << outerPixels << '\n';
}
