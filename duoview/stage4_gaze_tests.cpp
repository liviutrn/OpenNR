#include "DuoViewGaze.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
namespace d = uevr::duoview;
static bool near(float a,float b){return std::abs(a-b)<.0001f;}
int main() {
    const d::Tans f{-1.f,1.f,1.f,-1.f};
    // Regression: the HMD-local gaze ray reaches the frustum mapper unchanged.
    // No inverse head/eye rotation is applied (v23 Build29/32 trembling).
    auto straight = d::ray_to_uv({0.f,0.f,1.f},f);
    assert(straight && near(straight->u,.5f) && near(straight->v,.5f));
    auto right_and_up = d::ray_to_uv({.5f,.5f,1.f},f);
    assert(right_and_up && near(right_and_up->u,.75f) && near(right_and_up->v,.25f));
    assert(!d::ray_to_uv({0.f,0.f,-1.f},f));
    assert(!d::ray_to_uv({0.f,0.f,0.f},f));
    assert(!d::ray_to_uv({0.f,0.f,1.f},{1.f,-1.f,1.f,-1.f}));
    auto edge=d::ray_to_uv({10.f,-10.f,1.f},f);
    assert(edge && near(edge->u,1.f) && near(edge->v,1.f));
    d::GazeCache gaze{50};
    auto a=gaze.update(1000,d::UV{.7f,.3f});
    assert(near(a.u,.7f) && near(a.v,.3f));
    a=gaze.update(1048,{});
    assert(near(a.u,.7f));
    a=gaze.update(1051,{});
    assert(near(a.u,.5f) && near(a.v,.5f));
    a=gaze.update(1052,d::UV{.62f,.44f});
    assert(near(a.u,.62f));
    a=gaze.update(500,{});
    assert(near(a.u,.5f)); // reset on counter reset
    std::cout<<"DuoView gaze geometry/stale-frame policy tests passed\n";
}
