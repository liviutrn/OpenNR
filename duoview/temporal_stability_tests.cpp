#include "DuoViewState.hpp"
#include "DuoViewDlssHistoryPolicy.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
struct Parameters {
    unsigned value{},writes{};bool available{true};
    bool get_reset(unsigned& x) { x=value;return available; }
    void set_reset(unsigned x) { value=x;++writes; }
};
int main() {
    Settings settings;settings.r10_crop_policy=true;settings.quantization_pixels=8;
    settings.smoothing_ms=0;settings.compact_atlas=true;settings.hold_tracking_loss=true;
    settings.gaze_camera=true;settings.dlss_history_protection=true;
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
    assert(begin(1,{.5f,.5f})->config.foveal_history_reset);
    assert(begin(2,{.5f,.5f})->config.foveal_history_reset);
    assert(!begin(3,{.501f,.499f})->config.foveal_history_reset);
    const auto changed=begin(4,{.7f,.3f});assert(changed->config.foveal_history_reset);
    assert(begin(5,{.7f,.3f})->config.foveal_history_reset);
    assert(!begin(6,{.7f,.3f})->config.foveal_history_reset);
    assert(protect_dlss_history(changed->config,2504,2504));
    assert(!protect_dlss_history(changed->config,1000,1000));
    assert(!protect_dlss_history(changed->config,5000,5000));
    Parameters parameters;
    { DlssResetScope reset{parameters,true};assert(reset.active() && parameters.value==1); }
    assert(parameters.value==0 && parameters.writes==2);
    parameters.value=1;parameters.writes=0;
    { DlssResetScope reset{parameters,true};assert(!reset.active() && parameters.value==1); }
    assert(parameters.value==1 && parameters.writes==0);
    parameters.value=0;parameters.available=false;
    { DlssResetScope reset{parameters,true};assert(!reset.active()); }
    assert(parameters.value==0 && parameters.writes==0);
    settings.eye_tracked=false;assert(state.configure(settings));
    assert(begin(7,{.5f,.5f})->config.foveal_history_reset);
    assert(!begin(8,{.5f,.5f})->config.foveal_history_reset);
    std::cout << "OpenNR quantized fixation, instant saccades, zero settling drift, fovea-only history and SDK-reset restoration passed\n";
}
