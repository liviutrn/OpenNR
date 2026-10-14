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
    uevr::mono::Selection startup;
    startup.initialize_duoview();
    require(startup.active()==6 && startup.requested()==6 && startup.generation()==1 && !startup.pending(),
        "DuoView must be active before a native frame or consumer retirement is possible");
    startup.initialize_duoview();
    require(startup.active()==6 && startup.generation()==1,"Reload must not reset startup to native stereo");
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
    require(state.consume(key).has_value(),"Current coherent pair rejected");
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
    Settings stable; stable.crop_width=stable.crop_height=.30f;
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
    require(temporal.can_independent_shading({7,2},200),"Distinct ViewStates should permit guarded adaptation");
    stable.independent_shading=false; require(temporal.configure(stable),"Shading off rejected");
    require(temporal.snapshot({7,2})->config.settings.independent_shading,"Mid-frame toggle split the source pair");
    require(temporal.begin({7,3},3000,3000,p,[]()->std::optional<UV>{return UV{.6f,.5f};},1022).has_value(),"Next-frame toggle packet missing");
    require(!temporal.can_independent_shading({7,3},200),"Shading off must apply to the next producer frame");
    // v24 contract: user-tested Build32 failed because its gaze lag was
    // mistaken for stability. Any valid new sample MUST apply immediately.
    CropStability direct;
    Settings follow{};
    follow.crop_width=follow.crop_height=.5f;
    follow.guard_fraction=.25f; follow.smoothing_ms=250.f;
    follow.stabilize_crop=true; // persisted legacy values must be harmless
    auto centre=direct.update({31,1},3400,3172,follow,UV{.5f,.5f},1000);
    auto tiny=direct.update({31,2},3400,3172,follow,UV{.501f,.499f},1011);
    require(centre.u==.5f && tiny.u==.501f && tiny.v==.499f,
            "New gaze must not be swallowed by the old v23 guard");
    auto instant=direct.update({31,3},3400,3172,follow,UV{.9f,.8f},1022);
    require(instant.u==.9f && instant.v==.8f,
            "Large saccade must reach target in the same render frame");
    auto held=direct.update({31,4},3400,3172,follow,{},1044);
    require(held.u==instant.u && held.v==instant.v,"Brief missing sample should hold last coordinate");
    auto expired=direct.update({31,5},3400,3172,follow,{},1123);
    require(expired.u==.5f && expired.v==.5f,"Expired gaze must restore static center");
    State audit;
    Settings auds{}; auds.temporal_audit=true; auds.eye_tracked=true;
    require(audit.configure(auds),"Audit settings rejected");
    auto mark=[&](FrameKey k, UV gaze, uintptr_t primary, uintptr_t secondary) {
        auto f=audit.begin(k,3400,3172,p,[&]()->std::optional<UV>{return gaze;},1000+k.frame*11);
        require(f.has_value(),"Audit frame missing");
        for (unsigned eye=0;eye<2;++eye) {
            require(audit.rectangle(k,eye) && audit.projection(k,eye) &&
                    audit.camera(k,eye,camera) && audit.scene(k,eye,eye?secondary:primary),
                    "Audit frame view observations failed");
        }
        require(audit.family(k,true,2) && audit.consume(k),"Audit source frame could not be consumed");
    };
    mark({40,1},UV{.5f,.5f},100,200);
    mark({40,2},UV{.7f,.5f},100,200);
    auto d=audit.temporal_audit();
    require(d && d->previous_frame && d->distinct_view_states && d->stable_view_states &&
            d->same_pose && d->moving_fovea && d->expected_crop_motion_px_x < -1.,
            "Temporal moving-crop/previous-state diagnostics inconsistent");
    mark({40,3},UV{.8f,.5f},100,100);
    d=audit.temporal_audit();
    require(d && !d->distinct_view_states && !d->stable_view_states,
            "Shared temporal history must be flagged");
    mark({40,4},UV{.8f,.5f},300,400);
    d=audit.temporal_audit();
    require(d && d->distinct_view_states && !d->stable_view_states,
            "Changed temporal identity across frames must be flagged");
    follow.smoothing_ms=251.f;
    State bad_controls; require(!bad_controls.configure(follow),"Invalid smoothing must be rejected");
    follow.smoothing_ms=85.f; follow.guard_fraction=.251f;
    require(!bad_controls.configure(follow),"Invalid wide guard must be rejected");
    std::cout<<"Pinned Joey DuoView geometry, instant gaze, typed projection, history audit contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}
