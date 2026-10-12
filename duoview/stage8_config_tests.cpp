#include "DuoViewConfig.hpp"
#include <cassert>
#include <cmath>
#include <iostream>
namespace d=uevr::duoview;
static bool near(float a,float b){return std::fabs(a-b)<.0001f;}
int main() {
    d::ConfigLatch latch;
    auto first=latch.for_frame({5,10},3000,3000,{.5f,.5f});
    assert(first && first->layout.fovea.width==1500);
    assert(first->layout.periphery.width==600 && first->settings_revision==1);
    d::Settings modified{};
    modified.crop_width=.30f;modified.crop_height=.30f;
    modified.peripheral_scale=.15f;modified.feather_fraction=.04f;
    assert(latch.set_settings(modified));
    // Deliberately alter gaze and size mid-frame: immutable frame's
    // geometry must remain unchanged for both views and DX12 shader.
    auto same=latch.for_frame({5,10},2000,2000,{.9f,.8f});
    assert(same && same->layout.fovea.width==1500);
    assert(near(same->gaze.u,.5f) && same->settings_revision==1);
    auto next=latch.for_frame({5,11},3000,3000,{.9f,.8f});
    assert(next && next->settings_revision==2);
    assert(next->layout.fovea.width==900);
    assert(next->layout.periphery.width==450);
    assert(near(next->layout.u0,.7f) && near(next->layout.u1,1.f));
    assert(!latch.for_frame({5,10},3000,3000,{.9f,.8f}));
    assert(!latch.for_frame({5,12},3000,3000,{-1.f,.5f}));
    auto invalid=modified;invalid.feather_fraction=2.f;
    assert(!latch.set_settings(invalid));
    auto still=latch.for_frame({5,12},3000,3000,{.5f,.5f});
    assert(still && still->settings_revision==2);
    latch.retire();
    assert(!latch.for_frame({5,12},3000,3000,{.5f,.5f}));
    auto fresh=latch.for_frame({6,1},3000,3000,{.5f,.5f});
    assert(fresh && fresh->key.generation==6);
    std::cout<<"DuoView immutable per-frame config/gaze tests passed\n";
}
