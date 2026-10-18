#include "DuoViewGaze.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
namespace d = uevr::duoview;
static bool near(float a,float b){return std::abs(a-b)<.0001f;}
int main() {
    const d::Tans f{-1.f,1.f,1.f,-1.f};
    const std::array<float,9> identity{1,0,0,0,1,0,0,0,1};
    auto optical=d::optical_ray({.3f,.4f,1.f},identity);
    assert(optical && near(optical->right,.3f) && near(optical->up,.4f) && near(optical->forward,1.f));
    const float angle=.2f, c=std::cos(angle), s=std::sin(angle);
    optical=d::optical_ray({0,0,1},{c,0,-s,0,1,0,s,0,c});
    assert(optical && near(optical->right,s) && near(optical->forward,c));
    auto optical_uv=d::ray_to_uv(*optical,f);
    assert(optical_uv && near(optical_uv->u,.5f+.5f*std::tan(angle)));
    optical=d::optical_ray({0,0,1},{1,0,0,0,c,s,0,-s,c});
    assert(optical && near(optical->up,-s) && near(optical->forward,c));
    optical_uv=d::ray_to_uv(*optical,f);
    assert(optical_uv && near(optical_uv->v,.5f+.5f*std::tan(angle)));
    optical=d::optical_ray({.3f,.4f,1},{c,s,0,-s,c,0,0,0,1});
    assert(optical && near(optical->right,.3f*c+.4f*s) && near(optical->up,-.3f*s+.4f*c));
    auto invalid_rotation=identity; invalid_rotation[0]=NAN;
    assert(!d::optical_ray({0,0,1},invalid_rotation));
    assert(!d::optical_ray({0,0,-1},identity));
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
    // A single blink must retain the last good gaze and never snap to center.
    d::RayRecovery recovery;
    recovery.controls(350,2);
    auto tracked=recovery.update(1000,d::Ray{.2f,0.f,1.f});
    assert(tracked && near(tracked->right,.2f));
    tracked=recovery.update(1011,{},true); // blink or invalid Toolkit packet
    assert(tracked && near(tracked->right,.2f));
    tracked=recovery.update(1190,{});
    assert(tracked && near(tracked->right,.2f)); // held 190ms
    tracked=recovery.update(1200,d::Ray{-.4f,0.f,1.f}); // first post-blink outlier
    assert(tracked && near(tracked->right,.2f)); // does not jump
    tracked=recovery.update(1211,d::Ray{-.401f,0.f,1.f});
    assert(tracked && near(tracked->right,-.401f)); // confirmed in second valid sample
    tracked=recovery.update(1222,d::Ray{.1f,0.f,1.f});
    assert(tracked && near(tracked->right,.1f)); // continuous eye movement immediate
    tracked=recovery.update(1600,{},true);
    assert(!tracked); // sensor ray expires after specified hold; crop keeps position
    recovery.controls(1000,1);
    tracked=recovery.update(1611,d::Ray{.3f,0.f,1.f});
    assert(tracked && near(tracked->right,.3f)); // instant mode
    recovery.reset();
    assert(!recovery.update(100,{}));
    std::cout<<"DuoView gaze geometry/stale-frame policy tests passed\n";
}
