#include "runtime/open-shaders/src/Features/Upscaling/FoveatedRender/CropGeometry.h"
extern "C" void sampling(unsigned color, unsigned model, unsigned percent, unsigned origin, bool anchored, float* out)
{
    const auto s = FoveatedRenderImpl::CropGeometry::ModelSampling(color, color, model, model, percent, origin, origin, anchored);
    for (unsigned i = 0; i < 4; ++i) out[i] = s[i];
}
extern "C" void clip(unsigned fullW, unsigned fullH, unsigned x, unsigned y, unsigned width, unsigned height, float* out)
{
    const auto s = FoveatedRenderImpl::CropGeometry::ClipTransform(fullW, fullH, {x,y,width,height});
    for (unsigned i = 0; i < 4; ++i) out[i] = s[i];
}
