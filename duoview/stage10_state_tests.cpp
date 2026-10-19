#include "DuoViewState.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    // All menu fields must update independently. One invalid/contradictory
    // quality or gaze control may not freeze every other button or slider.
    Settings live;
    assert(!live.direct_xr_output);
    Settings simultaneous=live;
    simultaneous.crop_width=.80f;
    simultaneous.crop_height=.75f;
    simultaneous.foveal_density=2.f; // too large for Native per-eye source
    simultaneous.peripheral_scale=.35f;
    simultaneous.eye_tracked=false;
    simultaneous.native_fix_same_pass=false;
    simultaneous.gaze_offset_v=.15f;
    simultaneous.debug_border=true;
    simultaneous.diagnostic_view=2;
    auto a1=reconcile_ui_settings(simultaneous,live);
    assert(a1.rejected & reject_density);
    assert(!(a1.rejected & reject_width));
    assert(a1.settings.crop_width==.80f && a1.settings.crop_height==.75f);
    assert(a1.settings.foveal_density==live.foveal_density);
    assert(a1.settings.peripheral_scale==.35f);
    assert(!a1.settings.eye_tracked && !a1.settings.native_fix_same_pass);
    assert(a1.settings.debug_border && a1.settings.diagnostic_view==2);
    assert(a1.settings.gaze_offset_v==.15f);
    State live_state;
    assert(live_state.configure(a1.settings));
    live=live_state.settings();
    simultaneous=live;
    simultaneous.crop_width=4.f; // invalid persisted input, outside UI range
    simultaneous.feather_fraction=.30f;
    simultaneous.eye_tracked=true;
    simultaneous.native_fix_same_pass=true;
    simultaneous.gaze_offset_u=-.15f;
    simultaneous.gaze_still_radius=.05f;
    simultaneous.gaze_breakout_radius=.01f; // conflicting gaze thresholds
    auto a2=reconcile_ui_settings(simultaneous,live);
    assert(a2.rejected & reject_width);
    assert((a2.rejected & (reject_still|reject_breakout))!=0);
    assert(a2.settings.crop_width==live.crop_width);
    assert(a2.settings.feather_fraction==.30f);
    assert(a2.settings.eye_tracked && a2.settings.native_fix_same_pass);
    assert(a2.settings.gaze_offset_u==-.15f);
    assert(live_state.configure(a2.settings));
    // A valid simultaneous width increase + density decrease must apply
    // together, not be blocked by the transient state of one slider.
    live=live_state.settings();
    simultaneous=live;
    simultaneous.crop_width=.90f;
    simultaneous.crop_height=.90f;
    simultaneous.foveal_density=1.f;
    simultaneous.peripheral_scale=.49f;
    auto a3=reconcile_ui_settings(simultaneous,live);
    assert(!a3.rejected && a3.settings.crop_width==.90f);
    assert(live_state.configure(a3.settings));
    // A nonsense scalar cannot stop a valid mode/gaze change.
    live=live_state.settings();
    simultaneous=live;
    simultaneous.feather_fraction=NAN;
    simultaneous.eye_tracked=false;
    simultaneous.stabilize_crop=true;
    simultaneous.gpu_timing=true;
    simultaneous.direct_xr_output=true;
    simultaneous.gaze_hold_ms=450;
    simultaneous.gaze_offset_u=.05f;
    auto a4=reconcile_ui_settings(simultaneous,live);
    assert(a4.rejected==reject_feather);
    assert(!a4.settings.eye_tracked && a4.settings.stabilize_crop);
    assert(a4.settings.gpu_timing && a4.settings.gaze_hold_ms==450);
    assert(a4.settings.direct_xr_output);
    assert(a4.settings.gaze_offset_u==.05f);
    assert(live_state.configure(a4.settings));
    // Direct API remains strict: UI isolation must not weaken renderer guard.
    Settings invalid_direct=live_state.settings();
    invalid_direct.crop_width=1.f;
    invalid_direct.foveal_density=4.f;
    assert(!live_state.configure(invalid_direct));
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
    // Eye tracking OFF means no PSVR2 gaze reads. Manual positioning must work
    // without enabling the gaze pipeline or changing Native shading.
    State manual;
    Settings fixed; fixed.eye_tracked=false;
    fixed.gaze_offset_u=.08f; fixed.gaze_offset_v=-.12f;
    assert(manual.configure(fixed));
    int forbidden_gaze_reads=0;
    auto p0=manual.begin({41,1},3000,3000,matrix,[&]()->std::optional<UV>{
        ++forbidden_gaze_reads; return UV{.99f,.01f};
    },1000);
    assert(p0 && !p0->gaze_valid && forbidden_gaze_reads==0);
    assert(std::abs(p0->config.gaze.u-.58f)<1e-6f);
    assert(std::abs(p0->config.gaze.v-.38f)<1e-6f);
    fixed.gaze_offset_v=.20f;
    assert(manual.configure(fixed));
    auto p1=manual.begin({41,2},3000,3000,matrix,[&]()->std::optional<UV>{
        ++forbidden_gaze_reads; return UV{.11f,.21f};
    },1011);
    assert(p1 && forbidden_gaze_reads==0);
    assert(std::abs(p1->config.gaze.v-.70f)<1e-6f);
    assert(std::abs(p0->config.gaze.v-.38f)<1e-6f);
    fixed.eye_tracked=true;
    assert(manual.configure(fixed));
    auto p2=manual.begin({41,3},3000,3000,matrix,[&]()->std::optional<UV>{
        ++forbidden_gaze_reads; return UV{.5f,.5f};
    },1022);
    assert(p2 && forbidden_gaze_reads==1);
    fixed.eye_tracked=false;
    assert(manual.configure(fixed));
    auto p3=manual.begin({41,4},3000,3000,matrix,[&]()->std::optional<UV>{
        ++forbidden_gaze_reads; return UV{.9f,.9f};
    },1033);
    assert(p3 && forbidden_gaze_reads==1 && !p3->gaze_valid);
    assert(std::abs(p3->config.gaze.v-.70f)<1e-6f);
    CropStability stable;
    Settings controls; controls.stabilize_crop=true;
    controls.crop_width=controls.crop_height=.3f;
    auto centre=stable.update({1,1},3000,3000,controls,UV{.5f,.5f},1000);
    auto noisy=stable.update({1,2},3000,3000,controls,UV{.501f,.499f},1011);
    assert(centre.u==noisy.u && centre.v==noisy.v);
    auto moved=stable.update({1,3},3000,3000,controls,UV{.75f,.6f},1022);
    assert(std::abs(moved.u-.75f)<=2.f/3000+1e-6f && std::abs(moved.v-.6f)<=2.f/3000+1e-6f);
    auto held=stable.update({1,4},3000,3000,controls,{},1100);
    assert(held.u==moved.u && held.v==moved.v);
    auto expired=stable.update({1,5},3000,3000,controls,{},1123);
    assert(expired.u==moved.u && expired.v==moved.v); // no blink recenter even past sensor hold
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
    assert(std::abs(xphase/2.f-std::round(xphase/2.f))<.001f);
    assert(std::abs(yphase/2.f-std::round(yphase/2.f))<.001f);
    // Quantization independently adjustable without altering the deadzone.
    controls.gaze_quant_pixels=8; controls.guard_fraction=0.f;
    stable.reset();
    auto snapped=stable.update({1,8},3400,3172,controls,UV{.71943f,.61327f},1155);
    const auto snapped_layout=make_layout(3400,3172,controls.crop_width,controls.crop_height,
        controls.peripheral_scale,controls.foveal_density,snapped.u,snapped.v);
    assert(snapped_layout);
    const float snapped_pixels=snapped_layout->u0*snapped_layout->fovea.width/controls.crop_width;
    assert(std::abs(snapped_pixels/8.f-std::round(snapped_pixels/8.f))<.001f);
    controls.gaze_offset_u=.1f; controls.gaze_offset_v=-.05f;
    stable.reset();
    auto offset=stable.update({1,9},3400,3172,controls,UV{.5f,.5f},1166);
    assert(std::abs(offset.u-.6f)<.01f && std::abs(offset.v-.45f)<.01f);
    auto blink=stable.update({1,10},3400,3172,controls,{},5000);
    assert(blink.u==offset.u && blink.v==offset.v); // indefinite crop hold on lost tracking
    controls.gaze_quant_pixels=0; controls.guard_fraction=0.f;
    stable.reset();
    auto unsnapped=stable.update({1,11},3400,3172,controls,UV{.514321f,.482134f},5011);
    assert(std::abs(unsnapped.u-(.514321f+.1f))<.0001f);
    controls.gaze_quant_pixels=2; controls.guard_fraction=.05f; controls.gaze_offset_u=0.f; controls.gaze_offset_v=0.f;
    // Nonlinear adaptive response: lock sub-threshold fixation jitter.
    CropStability adaptive;
    Settings response; response.eye_tracked=true; response.stabilize_crop=true;
    response.crop_width=response.crop_height=.3f;
    response.guard_fraction=0.f; response.gaze_quant_pixels=0;
    response.gaze_breakout_radius=.04f; response.gaze_still_radius=.005f;
    response.gaze_relock_samples=3; response.gaze_micro_gain=0.f;
    auto fix=adaptive.update({19,1},3000,3000,response,UV{.5f,.5f},1000);
    assert(std::abs(fix.u-.5f)<1e-5f);
    auto jitter=adaptive.update({19,2},3000,3000,response,UV{.502f,.498f},1011);
    assert(jitter.u==fix.u && jitter.v==fix.v);
    auto near_gaze=adaptive.update({19,3},3000,3000,response,UV{.52f,.5f},1022);
    assert(near_gaze.u==fix.u && near_gaze.v==fix.v);
    // Crossing the breakout radius jumps immediately, without a smoothing tail.
    auto saccade=adaptive.update({19,4},3000,3000,response,UV{.60f,.5f},1033);
    assert(std::abs(saccade.u-.60f)<1e-5f);
    auto continued=adaptive.update({19,5},3000,3000,response,UV{.65f,.5f},1044);
    assert(std::abs(continued.u-.65f)<1e-5f);
    // Full-speed mode stays live through the subsequent small eye step.
    auto fast_small=adaptive.update({19,6},3000,3000,response,UV{.653f,.5f},1055);
    assert(std::abs(fast_small.u-.653f)<1e-5f);
    adaptive.update({19,7},3000,3000,response,UV{.653f,.5f},1066);
    adaptive.update({19,8},3000,3000,response,UV{.653f,.5f},1077);
    auto relocked=adaptive.update({19,9},3000,3000,response,UV{.654f,.5f},1088);
    assert(std::abs(relocked.u-.653f)<1e-5f);
    // Yet the next large saccade still moves the crop in a single new frame.
    auto breakout=adaptive.update({19,10},3000,3000,response,UV{.72f,.5f},1099);
    assert(std::abs(breakout.u-.72f)<1e-5f);
    auto blink_held=adaptive.update({19,11},3000,3000,response,{},2000);
    assert(blink_held.u==breakout.u && blink_held.v==breakout.v);
    // Optional gain permits slow micro-motion without slowing big saccades.
    adaptive.reset();
    response.gaze_micro_gain=.2f;
    auto start_gain=adaptive.update({20,1},3000,3000,response,UV{.5f,.5f},3000);
    auto slow_gain=adaptive.update({20,2},3000,3000,response,UV{.52f,.5f},3011);
    assert(std::abs(slow_gain.u-(start_gain.u+.02f*.2f))<1e-5f);
    auto fast_gain=adaptive.update({20,3},3000,3000,response,UV{.62f,.5f},3022);
    assert(std::abs(fast_gain.u-.62f)<1e-5f);
    response.gaze_still_radius=.06f;
    assert(!State{}.configure(response)); // stillness must be below breakout

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
