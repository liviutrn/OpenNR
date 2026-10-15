#include "DuoViewState.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    State state;
    const FrameKey first{1,100}, second{1,101};
    std::array<float,16> matrix{};
    matrix[0]=matrix[5]=1; matrix[11]=1; matrix[14]=.1f;
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
    assert(state.scene(first,0,100) && state.scene(first,1,200));
    std::array<double,16> view_rotation{};
    view_rotation[0]=view_rotation[5]=view_rotation[10]=view_rotation[15]=1.0;
    assert(state.view_transform(first,0,{0.0,0.0,0.0},view_rotation));
    assert(state.view_transform(first,1,{0.0,0.0,0.0},view_rotation));
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
    CropStability stable;
    Settings controls; controls.stabilize_crop=true; controls.smoothing_ms=0.f; // explicit instant-mode oracle
    controls.crop_width=controls.crop_height=.3f;
    auto centre=stable.update({1,1},3000,3000,controls,UV{.5f,.5f},1000);
    assert(centre.u==.5f && centre.v==.5f);
    auto noisy=stable.update({1,2},3000,3000,controls,UV{.501f,.499f},1011);
    assert(noisy.u==.501f && noisy.v==.499f); // no latency or guard
    auto fixation=stable.update({1,20},3000,3000,controls,UV{.5011f,.4991f},1012);
    assert(fixation.u==noisy.u && fixation.v==noisy.v);
    auto moved=stable.update({1,3},3000,3000,controls,UV{.75f,.6f},1022);
    assert(moved.u==.75f && moved.v==.6f); // deliberate movement instant
    auto held=stable.update({1,4},3000,3000,controls,{},1055);
    assert(held.u==moved.u && held.v==moved.v);
    auto expired=stable.update({1,5},3000,3000,controls,{},1123);
    assert(expired.u==.5f && expired.v==.5f);
    controls.stabilize_crop=false;
    auto raw=stable.update({1,6},3000,3000,controls,UV{.61123f,.42123f},1133);
    assert(raw.u==.61123f && raw.v==.42123f);
    controls.stabilize_crop=true; controls.foveal_density=1.8f;
    auto aligned=stable.update({1,7},3400,3172,controls,UV{.71943f,.61327f},1144);
    const auto aligned_layout=make_layout(3400,3172,controls.crop_width,controls.crop_height,
        controls.peripheral_scale,controls.foveal_density,aligned.u,aligned.v);
    assert(aligned_layout);
    const float xphase=aligned_layout->u0*aligned_layout->fovea.width/controls.crop_width;
    const float yphase=aligned_layout->v0*aligned_layout->fovea.height/controls.crop_height;
    assert(std::abs(aligned.u-.71943f)<.00001f && std::abs(aligned.v-.61327f)<.00001f);
    assert(std::isfinite(xphase) && std::isfinite(yphase)); // no pixel quantization
    State temporal;
    controls.independent_shading=true;
    assert(temporal.configure(controls));
    std::array<float,16> frozen{}; frozen[0]=frozen[5]=2; frozen[11]=1; frozen[14]=.1f;
    auto packet=temporal.begin({3,1},3000,3000,frozen,[]()->std::optional<UV>{return UV{.5f,.5f};},1000);
    assert(packet);
    std::array<std::array<double,4>,4> projected{};
    for (auto& col:projected) for (auto& x:col) x=999.;
    apply_frame_projection(projected,*packet,1);
    for (int col=0;col<4;++col) for (int row=0;row<4;++row) assert(projected[col][row]==frozen[col*4+row]);
    assert(!temporal.can_independent_shading({3,1},200));
    assert(temporal.rectangle({3,1},0) && temporal.rectangle({3,1},1));
    assert(temporal.projection({3,1},0) && temporal.projection({3,1},1));
    assert(temporal.camera({3,1},0,pose));
    assert(temporal.scene({3,1},0,100));
    assert(!temporal.can_independent_shading({3,1},0));
    assert(!temporal.can_independent_shading({3,1},100));
    assert(temporal.can_independent_shading({3,1},200));
    assert(temporal.scene({3,1},1,200,true));
    controls.independent_shading=false;
    assert(temporal.configure(controls));
    assert(temporal.snapshot({3,1})->config.settings.independent_shading);
    assert(temporal.begin({3,2},3000,3000,frozen,read,1011));
    assert(!temporal.can_independent_shading({3,2},200));
    auto bad_projection=frozen; bad_projection[0]=NAN;
    assert(!temporal.begin({3,3},3000,3000,bad_projection,read,1022));
    std::cout << "DuoView frame ring, camera latch and queued-pair gating passed\n";
}
