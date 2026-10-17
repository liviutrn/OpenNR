#include "../QuadStereoCompositeCPU.hpp"
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <cmath>
#include <limits>
#include <iostream>
using namespace uevr::quadview;
int main(){
    CompositorCrop c{.25,.25,.75,.75,.02};
    assert(c.valid());
    assert(composite_weight(c,0.0,0.5)==0.0);
    assert(composite_weight(c,.25,.5)==0.0);
    assert(composite_weight(c,.26,.5)>.49);
    assert(composite_weight(c,.26,.5)<.51);
    assert(composite_weight(c,.5,.5)==1.0);
    assert(composite_weight(c,.75,.5)==0.0);
    auto uv=to_fovea_uv(c,.5,.5);
    assert(uv && std::abs((*uv)[0]-.5)<1e-10 &&
                 std::abs((*uv)[1]-.5)<1e-10);
    assert(!to_fovea_uv(c,0.1,0.1));
    // Crop shifted toward the upper HMD region without affecting full eye UV.
    CompositorCrop up{.25,.10,.75,.60,.03};
    auto top=to_fovea_uv(up,.5,.35);
    assert(top && std::abs((*top)[1]-.5)<1e-10);
    assert(composite_weight(up,.5,.85)==0.0);
    // No feather still does not cover the exact outer border.
    c.feather=0;
    assert(composite_weight(c,.5,.5)==1.0);
    assert(composite_weight(c,.25,.5)==0.0);
    c.u1=c.u0;
    assert(!c.valid() && composite_weight(c,.5,.5)==0.0);
    c.u1=.75;c.feather=std::numeric_limits<double>::quiet_NaN();
    assert(!c.valid() && composite_weight(c,.5,.5)==0.0);
    std::cout<<"Quad stereo full-eye UV remap, feathering, invalid-crop gates OK\\n";
}
