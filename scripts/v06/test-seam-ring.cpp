#include "../../runtime/open-shaders/src/Features/Upscaling/NeuralRendering/OutsideTonePolicy.h"
#include <cassert>
#include <iostream>
#include <random>
#include <vector>

using namespace NeuralRendering::OutsideTone;
int main()
{
    std::mt19937 random(107);
    std::uint64_t checked = 0, skipped = 0;
    for (bool oval : { false, true }) {
        for (float scale : { 1.0f, 0.8f, 0.6f, 0.01f }) {
            for (unsigned iteration = 0; iteration < 80; ++iteration) {
                const unsigned eyeWidth = 233, eyeHeight = 197, eyeX = (iteration & 1u) * eyeWidth;
                const unsigned width = 1 + random() % 230, height = 1 + random() % 194;
                Geometry g{ eyeX + std::uint32_t(random() % (eyeWidth-width+1)), std::uint32_t(random() % (eyeHeight-height+1)), width, height, eyeX, eyeWidth, eyeHeight, oval, scale };
                const auto roi = MakeRegion(g, float(8 + random() % 120));
                const auto ring = MakeRing(g, roi);
                std::vector<bool> visited(roi.width*roi.height,false);
                assert(ring.totalPixels <= visited.size());
                for (unsigned index = 0; index < ring.totalPixels; ++index) {
                    unsigned x, y;
                    if (index < ring.topCount) { x = index % roi.width; y = index / roi.width; }
                    else if (index < ring.topCount + ring.sideCount) {
                        const auto local = index-ring.topCount, sideWidth = roi.width-ring.innerSize[0];
                        assert(sideWidth > 0);
                        x = local % sideWidth;
                        if (x >= ring.innerOrigin[0]) x += ring.innerSize[0];
                        y = ring.innerOrigin[1] + local / sideWidth;
                    } else {
                        const auto local = index-ring.topCount-ring.sideCount;
                        x = local % roi.width; y = ring.innerOrigin[1]+ring.innerSize[1]+local/roi.width;
                    }
                    assert(x < roi.width && y < roi.height);
                    assert(!visited[y*roi.width+x]); visited[y*roi.width+x] = true;
                    ++checked;
                }
                for (unsigned y = 0; y < roi.height; ++y) {
                    for (unsigned x = 0; x < roi.width; ++x) {
                        if (!visited[y*roi.width+x]) {
                            assert(Distance(float(int(roi.x+x)-int(g.x)),float(int(roi.y+y)-int(g.y)),g) <= 0);
                            ++skipped;
                        }
                    }
                }
            }
        }
    }
    const Geometry large{ 500,500,1000,1000,0,2000,2000,false,1 };
    const auto roi = MakeRegion(large,128);
    const auto ring = MakeRing(large,roi);
    assert(ring.totalPixels < roi.width*roi.height / 2);
    assert(!MakeRing(large,{}).totalPixels);
    Config c; c.contrast = -3; c.nonlinear = 8; c.plateau = 1; c.blackProtection = -1;
    c = Sanitize(c);
    assert(c.contrast == 0 && c.nonlinear == 1 && c.plateau == .8f && c.blackProtection == 0);
    std::cout << "Compact ring has complete outside coverage, no duplicates, eye isolation and only protected omissions; checked=" << checked << ", skipped=" << skipped << '\n';
}
