#include "DuoViewState.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    State state;
    const FrameKey first{1,100}, second{1,101};
    std::array<float,16> matrix{};
    matrix[0]=matrix[5]=matrix[10]=matrix[15]=1;
    int gaze_reads{};
    auto read = [&]() -> std::optional<UV> { ++gaze_reads; return UV{.25f,.75f}; };
    auto a=state.begin(first,3000,3000,matrix,read);
    assert(a && a->gaze_valid && gaze_reads==1);
    Settings changed; changed.crop_width=.3f; changed.fovea_view=1;
    assert(state.configure(changed));
    assert(state.begin(first,3000,3000,matrix,read)->config.layout.crop_width==.5f && gaze_reads==1);
    assert(!state.consume(first));
    assert(state.rectangle(first,0) && state.rectangle(first,1));
    assert(state.projection(first,0) && state.projection(first,1));
    CameraPose pose{{10.,20.,30.},{100.,200.,300.}};
    assert(state.camera(first,0,pose));
    assert(state.camera(first,1)->position==pose.position);
    CameraPose other{{20.,30.,40.},{300.,400.,500.}};
    assert(state.camera(first,1,pose));
    assert(state.camera(first,1)->position==pose.position);
    assert(!state.family(first,false,2) && !state.family(first,true,1));
    assert(state.family(first,true,2));
    auto b=state.begin(second,3000,3000,matrix,read);
    assert(b && b->config.settings.fovea_view==1 && gaze_reads==2);
    assert(state.snapshot(first)->config.layout.crop_width==.5f);
    assert(state.consume(first) && !state.consume(first));
    assert(!state.begin({1,99},3000,3000,matrix,read));
    assert(state.snapshot(second));
    assert(state.camera(second,0,pose));
    assert(!state.camera(second,1,other));
    assert(!state.camera(second,1) && !state.consume(second));
    state.retire();
    assert(!state.snapshot(first));
    assert(state.begin({2,1},3000,3000,matrix,read));
    std::cout << "DuoView frame ring, camera latch and queued-pair gating passed\n";
}
