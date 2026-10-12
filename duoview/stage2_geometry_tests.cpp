#include "DuoViewGeometry.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <iostream>
namespace d = uevr::duoview;

static bool near(float a, float b, float tolerance = .0001f) {
    return std::fabs(a-b) < tolerance;
}

int main() {
    assert(d::renderer_view_index(-1,true) == -1 && d::renderer_view_index(2,true) == -1);
    assert(d::renderer_view_index(0,true) == 0 && d::renderer_view_index(1,true) == 1);
    assert(d::renderer_view_index(0,false) == -1 && d::renderer_view_index(3,false) == -1);
    assert(d::renderer_view_index(1,false) == 0 && d::renderer_view_index(2,false) == 1);
    const auto a = d::make_layout(3000,3000,.50f,.50f);
    assert(a && a->fovea.width == 1500 && a->fovea.height == 1500);
    assert(a->periphery.x == 1500 && a->periphery.width == 600);
    assert(a->periphery.height == 600 && a->atlas_width == 6000);
    assert(d::rendered_pixels(*a) == 2610000ull);
    assert(near(a->u0,.25f) && near(a->u1,.75f));
    assert(near(a->v0,.25f) && near(a->v1,.75f));

    const auto b = d::make_layout(3000,3000,.30f,.30f);
    assert(b && b->fovea.width == 900 && b->fovea.height == 900);
    assert(b->periphery.x == 900 && d::rendered_pixels(*b) == 1170000ull);
    assert(near(b->u0,.35f) && near(b->u1,.65f));

    const auto dense = d::make_layout(3000,3000,.30f,.30f,.20f,3.f);
    assert(dense && dense->fovea.width == 2700 && dense->fovea.height == 2700);
    assert(d::rendered_pixels(*dense) == 7650000ull);
    assert(!d::make_layout(8193,3000));
    assert(!d::make_layout(3000,3000,.30f,.30f,.20f,4.f));
    const auto gaze = d::make_layout(3000,3000,.50f,.50f,.20f,1.f,.90f,.85f);
    assert(gaze && near(gaze->u0,.50f) && near(gaze->u1,1.f));
    assert(near(gaze->v0,.50f) && near(gaze->v1,1.f));
    const auto f = d::foveal_frustum({-1.f,1.f,1.f,-1.f}, *a);
    assert(f && near(f->left,-.5f) && near(f->right,.5f));
    assert(near(f->top,.5f) && near(f->bottom,-.5f));
    const auto f_shifted = d::foveal_frustum({-1.f,1.f,1.f,-1.f}, *gaze);
    assert(f_shifted && near(f_shifted->left,0.f) && near(f_shifted->right,1.f));

    // Matrix[col][row], UE's GLM convention. A canonical projection with
    // clipW=Z makes crop off-axis motion easy to verify.
    using Mat = std::array<std::array<float,4>,4>;
    Mat m{};
    m[0][0] = .8f;
    m[1][1] = .9f;
    m[2][3] = 1.f;
    m[3][2] = .1f;
    d::apply_foveal_crop(m,*a);
    assert(near(m[0][0],1.6f) && near(m[1][1],1.8f));
    assert(near(m[2][0],0.f) && near(m[2][1],0.f));
    assert(near(m[3][2],.1f) && near(m[2][3],1.f));

    Mat g{};
    g[0][0] = .8f; g[1][1] = .9f; g[2][3] = 1.f; g[3][2] = .1f;
    d::apply_foveal_crop(g,*gaze);
    assert(near(g[2][0],-1.f) && near(g[2][1],1.f));

    assert(near(d::foveal_blend(*a,.5f,.5f,.05f),1.f));
    assert(near(d::foveal_blend(*a,.25f,.5f,.05f),0.f));
    assert(near(d::foveal_blend(*a,.01f,.5f,.05f),0.f));
    assert(d::foveal_blend(*a,.26f,.5f,.05f) > 0.f);
    assert(d::foveal_blend(*a,.26f,.5f,.05f) < 1.f);
    assert(!d::make_layout(0,3000) && !d::make_layout(3000,0));
    assert(!d::make_layout(3000,3000,.0f,.50f));
    assert(!d::make_layout(3000,3000,.50f,.50f,2.0f));
    assert(!d::make_layout(3000,3000,1.0f,1.0f,.20f,2.0f)); // vertical > output
    std::cout << "DuoView geometry/projection/blending tests passed\n";
}
