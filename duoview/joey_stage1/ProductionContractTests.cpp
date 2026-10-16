#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "DuoViewState.hpp"
#include "MonoRenderingPolicy.hpp"

using namespace uevr::duoview;
static void require(bool test, const char* what) {
    if (!test) throw std::runtime_error(what);
}
int main() try {
    // Do not downgrade for momentary 1-3 frame gaps during initialization.
    // Exactly 4 consecutive missing compositor/scene observations require
    // a game-thread transition to true Mono mode5; never Native Stereo ID0.
    require(!should_fallback_to_mono(0) &&
            !should_fallback_to_mono(1) &&
            !should_fallback_to_mono(3) &&
            should_fallback_to_mono(4) &&
            should_fallback_to_mono(10),
            "Transient DuoView frames triggered a premature Mono mode-switch");
    require(!should_fallback_to_mono(3,false) &&
            !should_fallback_to_mono(59,false) &&
            should_fallback_to_mono(60,false) &&
            should_fallback_to_mono(100,false),
            "DuoView warmup was prematurely downgraded to Mono or never recovered");
    require(uevr::mono::is_mono_family(uevr::mono::method_id) &&
            uevr::mono::is_mono_family(uevr::mono::duoview_method_id) &&
            !uevr::mono::is_mono_family(0),
            "Joey Mono fallback destination must retain the Mono-family path");
    {
        // Producer fallback uses Joey's existing GPU-retirement transaction,
        // not an instant switch to Native Stereo.
        uevr::mono::Selection transition;
        transition.initialize(uevr::mono::duoview_method_id);
        require(transition.active()==0 && transition.pending(),
                "Boot-time DuoView must defer before GPU lifetime is safe");
        transition.consumers_retired(transition.request_token());
        require(transition.commit_at_game_frame_boundary() &&
                transition.active()==uevr::mono::duoview_method_id,
                "Boot-time DuoView could not start safely");
        transition.request(uevr::mono::method_id);
        require(transition.active()==uevr::mono::duoview_method_id &&
                transition.pending(),"Fallback to Joey Mono switched mid-frame");
        require(!transition.commit_at_game_frame_boundary(),
                "Fallback advanced without GPU consumer retirement");
        transition.consumers_retired(transition.request_token());
        require(transition.commit_at_game_frame_boundary() &&
                transition.active()==uevr::mono::method_id &&
                transition.active()!=0,
                "DuoView fallback did not resolve to real Joey Mono ID5");
    }
    // The OpenVR path must use the same shared binocular, mono-scene optical
    // union as Joey OpenXR: symmetric common frustum and valid eye crop bounds.
    const std::array<uevr::mono::Eye,2> eyes{{
        {{0.f,0.f,0.f,1.f},{-.032f,0.f,0.f},{-1.84f,.95f,1.33f,-1.33f}},
        {{0.f,0.f,0.f,1.f},{ .032f,0.f,0.f},{-.95f,1.84f,1.33f,-1.33f}}
    }};
    const auto shared=uevr::mono::geometry(eyes);
    require(shared && shared->horizontal>1.83f && shared->vertical>1.32f,
            "SteamVR source cameras must use one calibrated binocular Mono frustum");
    for (auto& bounds:shared->bounds)
        require(bounds[0]>=0.f && bounds[1]<=1.f &&
                bounds[2]>=0.f && bounds[3]<=1.f && bounds[0]<bounds[1] &&
                bounds[2]<bounds[3], "Invalid per-eye SteamVR Mono optical crop");

    for (auto wh: {std::array{2000u,2000u},std::array{3000u,3000u},
                   std::array{3400u,3172u},std::array{4096u,2160u}}) {
        const auto l=make_layout(wh[0],wh[1],.30f,.30f,.25f,2.5f,.5f,.5f);
        require(l.has_value(), "Pinned fixed-center geometry not admitted");
        require(layout_valid(*l), "Pinned geometry not valid");
        require(l->fovea.x == 0 && l->fovea.y == 0,
                "Legacy high-resolution fovea must begin at atlas origin");
        require(l->periphery.x == l->fovea.width && l->periphery.y == 0,
                "Peripheral rectangle must not overwrite legacy fovea");
        require(l->fovea.x + l->fovea.width <= l->atlas_width &&
                l->periphery.width <= wh[0] && l->atlas_width == wh[0]*2,
                "Atlas bounds or original double-wide XR allocation changed");
        require(std::abs(l->u0 - .35f) < 1e-5f && std::abs(l->u1 - .65f) < 1e-5f,
                "Off-axis fovea projection no longer center cropped");
        const double ratio=static_cast<double>(rendered_pixels(*l))/(wh[0]*static_cast<double>(wh[1]));
        require(ratio>.622 && ratio<.628,
                "Unexpected rendered-pixel budget; two UE views may overdraw baseline");
        const Tans full{-1.8f, .92f, 1.3f, -1.3f};
        const auto crop=foveal_frustum(full,*l);
        require(crop && crop->left > full.left && crop->right < full.right &&
                crop->top < full.top && crop->bottom > full.bottom,
                "Fovea must have distinct off-axis smaller frustum in shared Mono basis");
    }
    State state;
    Settings settings{};
    settings.crop_width=.30f;
    settings.crop_height=.30f;
    settings.peripheral_scale=.25f;
    settings.foveal_density=2.5f;
    settings.feather_fraction=.08f;
    settings.eye_tracked=false;
    settings.fovea_view=1;
    require(state.configure(settings),"Fixed-center configuration rejected");
    // Fixed center remains vertical-adjustable but never calls the gaze provider.
    State fixed_center;
    Settings static_center{};
    static_center.fixed_center_v=.70f;
    static_center.eye_tracked=false;
    require(fixed_center.configure(static_center),"Vertical-center settings rejected");
    std::array<float,16> fixed_projection{}; fixed_projection[0]=fixed_projection[5]=fixed_projection[10]=fixed_projection[15]=1.f;
    bool gaze_was_called=false;
    auto fixed_snap=fixed_center.begin({99,1},3000,3000,fixed_projection,
        [&]()->std::optional<UV>{gaze_was_called=true;return UV{.01f,.99f};});
    require(fixed_snap && !gaze_was_called,"Fixed center incorrectly sampled headset gaze");
    require(std::abs(fixed_snap->config.gaze.u-.5f)<1e-6f &&
            std::abs(fixed_snap->config.gaze.v-.7f)<1e-6f,
            "Fixed-center vertical setting did not reach the projection and compositor");
    static_center.fixed_center_v=1.01f;
    require(!fixed_center.configure(static_center),"Out-of-range vertical center accepted");

    settings.diagnostic_view=3;
    require(!state.configure(settings),"Invalid diagnostic accepted");
    settings.diagnostic_view=1;
    require(state.configure(settings),"Peripheral-only diagnostic unavailable");
    settings.diagnostic_view=2;
    require(state.configure(settings),"Fovea-only diagnostic unavailable");
    settings.diagnostic_view=0;
    require(state.configure(settings),"Composite diagnostic restore failed");
    settings.crop_width=.95f; settings.foveal_density=4.f;
    require(!state.configure(settings),"Oversized atlas accepted");
    settings.crop_width=.30f; settings.foveal_density=2.5f;
    require(state.configure(settings),"Valid atlas was not restored");
    settings.fovea_view=0;
    require(state.configure(settings),"First-view fovea selection rejected");
    settings.fovea_view=1;
    require(state.configure(settings),"Second-view fovea selection rejected");
    FrameKey key{4,100};
    std::array<float,16> m{};m[0]=m[5]=m[10]=m[15]=1.0f;
    auto snap=state.begin(key,3000,3000,m,[]()->std::optional<UV>{return UV{.5f,.5f};});
    require(snap && !snap->gaze_valid, "Unexpected gaze sampling in fixed-center Stage 2-4");
    const CameraPose camera{{1.,2.,3.},{10.,20.,30.}};
    require(state.rectangle(key,0) && state.projection(key,0) && state.camera(key,0,camera),
            "Peripheral producer observations rejected");
    require(!state.consume(key),"Single view must not masquerade as paired compositor source");
    require(state.family(key,true,2),"Main 2-view family not recognized");
    require(!state.consume(key),"Missing foveal view must prohibit composition");
    require(state.rectangle(key,1) && state.projection(key,1) && state.camera(key,1,camera),
            "Second same-pose view observations rejected");
    require(!state.consume({4,101}),"Wrong engine frame must not compose");
    require(!state.consume({3,100}),"Wrong renderer generation must not compose");
    require(!state.consume(key),"View pair with no UE source states must not compose");
    require(state.scene(key,0,101) && state.scene(key,1,101,true),
            "Could not publish intentionally aliased source states");
    require(!state.consume(key),"Aliased scene histories must not be presented as distinct UE views");
    require(state.scene(key,1,202,false),
            "Could not publish untreated secondary source for negative test");
    require(!state.consume(key),"Untreated secondary Lumen/shadow source must not compose");
    require(state.scene(key,1,202,true),
            "Guarded secondary Native Fix constructor transaction not published");
    require(state.consume(key).has_value(),"Distinct Native Fix-treated current UE source pair rejected");
    require(!state.consume(key),"Double submission of a frame must be rejected");
    settings.diagnostic_view=1; settings.gpu_timing=true;
    require(state.configure(settings),"Quality settings change rejected");
    require(state.snapshot(key)->config.settings.diagnostic_view==0 &&
            !state.snapshot(key)->config.settings.gpu_timing,
            "In-flight diagnostic/timing changed when UI settings updated");
    auto new_frame=state.begin({4,101},3000,3000,m,
        []()->std::optional<UV>{return UV{.5f,.5f};});
    require(new_frame && new_frame->config.settings.diagnostic_view==1 && new_frame->config.settings.gpu_timing,
            "Updated preview diagnostic not applied on NEXT UE frame");
    require(state.snapshot(key)->config.settings.diagnostic_view==0,
            "Late settings invalidated prior view pair");
    state.retire();
    require(!state.consume(key),"Invalidated pair must not survive reset");
    require(state.begin({5,1},3000,3000,m,[]()->std::optional<UV>{return UV{.5f,.5f};}).has_value(),
            "New generation after reset must be supported");
    State temporal;
    Settings stable; stable.crop_width=stable.crop_height=.30f; stable.eye_tracked=true;
    stable.independent_shading=true;
    require(temporal.configure(stable),"Temporal settings rejected");
    std::array<float,16> p{}; p[0]=p[5]=2; p[11]=1; p[14]=.1f;
    auto previous=temporal.begin({7,1},3000,3000,p,[]()->std::optional<UV>{return UV{.5f,.5f};},1000);
    auto current=temporal.begin({7,2},3000,3000,p,[]()->std::optional<UV>{return UV{.6f,.5f};},1011);
    require(previous && current,"Moving-crop projection packets missing");
    std::array<std::array<double,4>,4> previous_matrix{},current_matrix{};
    for(auto& column:current_matrix) for(auto& value:column) value=99.;
    apply_frame_projection(previous_matrix,*previous,0);
    apply_frame_projection(current_matrix,*current,0);
    const auto project=[](const auto& matrix,double x) {
        const double clip=matrix[0][0]*x+matrix[2][0];
        const double w=matrix[0][3]*x+matrix[2][3];
        return .5*(clip/w+1.);
    };
    const double world_x=.05, full_u=.55;
    const auto previous_u=project(previous_matrix,world_x),current_u=project(current_matrix,world_x);
    require(std::abs(current->config.layout.u0+current_u*stable.crop_width-full_u)<1e-6,
            "Moving crop must reconstruct the SAME stationary world point in compositor coordinates");
    require(std::abs(previous_u-current_u-
            (current->config.layout.u0-previous->config.layout.u0)/stable.crop_width)<1e-6,
            "Previous/current cropped projections must encode the correct temporal reprojection displacement");
    require(previous->config.layout.fovea.width==current->config.layout.fovea.width &&
            previous->config.layout.fovea.height==current->config.layout.fovea.height,
            "Compatible gaze translation must not resize the render target/history");
    apply_frame_projection(current_matrix,*current,1);
    for(int col=0;col<4;++col) for(int row=0;row<4;++row)
        require(current_matrix[col][row]==p[col*4+row],"Peripheral projection reread live runtime data");
    require(temporal.rectangle({7,2},0) && temporal.rectangle({7,2},1) &&
            temporal.projection({7,2},0) && temporal.projection({7,2},1) &&
            temporal.camera({7,2},0,camera) && temporal.scene({7,2},0,100),"Shading source contract rejected");
    require(!temporal.can_independent_shading({7,2},100),"Shared ViewState must block primary adaptation");
    // The Native Fix source transaction runs IN the secondary constructor:
    // it must be possible after the first view completes, BEFORE second
    // rectangle/projection/camera observations can be published.
    State pre_secondary;
    Settings source_test{};
    require(pre_secondary.configure(source_test),"Pre-constructor setup rejected");
    const FrameKey source_key{41,1};
    auto source_frame=pre_secondary.begin(source_key,3000,3000,p,
        []()->std::optional<UV>{return UV{.5f,.5f};});
    require(source_frame.has_value(),"Missing stable primary source snapshot");
    require(!pre_secondary.can_native_fix_secondary_source(source_key,202),
        "Secondary constructor adapted before primary source existed");
    require(pre_secondary.rectangle(source_key,0) && pre_secondary.projection(source_key,0) &&
            pre_secondary.camera(source_key,0,camera) &&
            pre_secondary.scene(source_key,0,101),
            "Could not publish first constructor source");
    require(pre_secondary.can_native_fix_secondary_source(source_key,202),
        "Native Fix source unnecessarily demanded already-constructed secondary view");
    require(!pre_secondary.can_native_fix_secondary_source(source_key,101) &&
            !pre_secondary.can_native_fix_secondary_source({41,2},202),
        "Native Fix accepted aliased ViewState or incorrect frame");

    // DuoView's actual Native Fix source protocol must NOT inherit the
    // experimental independent-shading toggle. Guard by frame+ViewState pair.
    require(!temporal.can_native_fix_secondary_source({7,2},100),
            "Native source transaction must reject aliased source ViewState");
    require(temporal.can_native_fix_secondary_source({7,2},200),
            "Coherent distinct UE secondary ViewState should admit source parity");
    require(!temporal.can_native_fix_secondary_source({7,1},200),
            "Native source transaction accepted a stale render frame");

    require(temporal.can_independent_shading({7,2},200),"Distinct ViewStates should permit guarded adaptation");
    stable.independent_shading=false; require(temporal.configure(stable),"Shading off rejected");
    require(temporal.snapshot({7,2})->config.settings.independent_shading,"Mid-frame toggle split the source pair");
    require(temporal.begin({7,3},3000,3000,p,[]()->std::optional<UV>{return UV{.6f,.5f};},1022).has_value(),"Next-frame toggle packet missing");
    require(!temporal.can_independent_shading({7,3},200),"Shading off must apply to the next producer frame");
    // Time-domain stability contract: continuous deadzone, no gaze teleport,
    // and bounded frame-to-frame movement even across an eye saccade.
    CropStability smoother;
    Settings follow{};
    follow.eye_tracked=true;
    follow.stabilize_crop=true;
    follow.crop_width=follow.crop_height=.5f;
    follow.guard_fraction=.10f;
    follow.smoothing_ms=85.f;
    auto centre=smoother.update({31,1},3400,3172,follow,UV{.5f,.5f},1000);
    auto noise=smoother.update({31,2},3400,3172,follow,UV{.51f,.49f},1011);
    require(centre.u==noise.u && centre.v==noise.v,"Fixation noise moved stable crop");
    auto slow=smoother.update({31,3},3400,3172,follow,UV{.9f,.8f},1022);
    require(slow.u>centre.u && slow.u<.52f && slow.v>centre.v && slow.v<.52f,
            "Large gaze saccade must move gradually, not jump");
    auto last=slow;
    for (uint64_t f=4;f<30;++f) {
        auto next=smoother.update({31,f},3400,3172,follow,UV{.9f,.8f},1000+(f-1)*11);
        require(next.u>=last.u && next.v>=last.v,"Smoothing must be monotonic toward a fixed target");
        require(next.u-last.u<=.019f && next.v-last.v<=.019f,
                "Frame-to-frame crop jump exceeds bounded tracking speed");
        last=next;
    }
    auto held=smoother.update({31,30},3400,3172,follow,{},1360);
    require(held.u==last.u && held.v==last.v,"Short CAPI gap changed crop");
    auto back=smoother.update({31,31},3400,3172,follow,{},1420);
    require(back.u<held.u && back.u>.5f,"Expired gaze must return gently rather than teleport");
    follow.smoothing_ms=251.f;
    State bad_controls; require(!bad_controls.configure(follow),"Invalid smoothing must be rejected");
    follow.smoothing_ms=85.f; follow.guard_fraction=.251f;
    require(!bad_controls.configure(follow),"Invalid wide guard must be rejected");
    std::cout<<"Pinned Joey DuoView geometry, view pairing, gradual gaze, primary fallback contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}
