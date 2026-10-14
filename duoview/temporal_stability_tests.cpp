#include "DuoViewState.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    Settings settings;settings.r10_crop_policy=true;settings.quantization_pixels=8;
    settings.smoothing_ms=0;settings.compact_atlas=true;settings.hold_tracking_loss=true;
    settings.gaze_camera=true;
    CropStability crop;
    const auto first=crop.update({1,1},5000,5000,settings,UV{.5f,.5f},1000,.5f,.5f);
    const auto noise=crop.update({1,2},5000,5000,settings,UV{.501f,.499f},1010,.5f,.5f);
    assert(first.u==noise.u && first.v==noise.v);
    const auto moved=crop.update({1,3},5000,5000,settings,UV{.7f,.3f},1020,.5f,.5f);
    assert(std::abs(moved.u-.7f)<.002f && std::abs(moved.v-.3f)<.002f);
    const float step=8.f/2504;
    assert(std::abs((moved.u-.25f)/step-std::round((moved.u-.25f)/step))<1e-4f);
    for (unsigned n=4;n<100;++n) {
        const auto stopped=crop.update({1,n},5000,5000,settings,UV{.7f,.3f},1020+n*10,.5f,.5f);
        assert(stopped.u==moved.u && stopped.v==moved.v);
    }
    settings.smoothing_ms=250;
    const auto saccade=crop.update({1,100},5000,5000,settings,UV{.3f,.7f},2500,.5f,.5f);
    assert(std::abs(saccade.u-.3f)<.002f && std::abs(saccade.v-.7f)<.002f);
    settings.stabilize_crop=false;
    const auto raw=crop.update({1,101},5000,5000,settings,UV{.61123f,.42123f},2510);
    assert(raw.u==.61123f && raw.v==.42123f);
    State state;settings.stabilize_crop=true;settings.smoothing_ms=0;
    assert(state.configure(settings));
    const std::array<float,16> projection{.55f,0,0,0,0,.75f,0,0,0,0,0,1,0,0,.1f,0};
    auto begin=[&](unsigned n,UV gaze) {
        return state.begin({2,n},5000,5000,projection,[gaze]()->std::optional<UV>{return gaze;},3000+n*10);
    };
    const auto initial=begin(1,{.5f,.5f});assert(initial);
    const auto held=begin(2,{.501f,.499f});assert(held);
    assert(initial->config.layout.u0==held->config.layout.u0 &&
        initial->config.foveal_camera.forward==held->config.foveal_camera.forward);
    const auto changed=begin(3,{.7f,.3f});assert(changed);
    assert(changed->config.layout.u0!=held->config.layout.u0);
    for (unsigned n=4;n<100;++n) {
        const auto stopped=begin(n,{.7f,.3f});assert(stopped);
        assert(stopped->config.layout.u0==changed->config.layout.u0 &&
            stopped->config.layout.v0==changed->config.layout.v0 &&
            stopped->config.foveal_camera.forward==changed->config.foveal_camera.forward);
    }
    settings.eye_tracked=false;assert(state.configure(settings));
    const auto fixed=begin(100,{.7f,.3f});assert(fixed && !fixed->config.foveal_camera.enabled);
    assert(fixed->config.layout.u0==.25f && fixed->config.layout.v0==.25f);
    std::cout << "OpenNR quantized fixation, instant saccades, zero camera settling drift and fixed-center restoration passed\n";
}
