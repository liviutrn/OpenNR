#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <stdexcept>
#include "DuoViewState.hpp"
#include "MonoRenderingPolicy.hpp"

using namespace uevr::duoview;
static void require(bool test, const char* what) {
    if (!test) throw std::runtime_error(what);
}
int main() try {
    // Low-res Native0 warms UE view machinery before changing DuoView's
    // render method. Joey's existing GPU consumer retirement must be respected.
    constexpr auto duoview_method = uevr::mono::method_id;
    uevr::mono::Selection bootstrap;
    bootstrap.initialize(0);
    require(bootstrap.active()==0 && !bootstrap.pending(),
            "Bootstrap must start Native Stereo 0 without immediate ID6");
    bootstrap.request(duoview_method);
    require(bootstrap.active()==0 && bootstrap.pending(),
            "DuoView request must defer while native resources remain live");
    require(!bootstrap.commit_at_game_frame_boundary(),
            "Unretired source copies may not activate DuoView");
    bootstrap.consumers_retired(bootstrap.request_token());
    require(bootstrap.commit_at_game_frame_boundary() && bootstrap.active()==duoview_method,
            "Guarded native to DuoView transition failed");
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
    require(previous_matrix!=current_matrix &&
            previous_matrix[2][0]!=current_matrix[2][0],
            "Gaze must move the foveal projection crop");
    require(temporal.camera({7,1},0,camera) && temporal.camera({7,1},1,camera) &&
            temporal.camera({7,2},0,camera) && temporal.camera({7,2},1,camera),
            "Both source views must keep the canonical head pose");
    const auto crop_vector=expected_crop_motion(previous->config,current->config);
    const double expected_crop_pixels_x=
        (double(current->config.layout.u0)-previous->config.layout.u0)/
        current->config.layout.crop_width*current->config.layout.fovea.width;
    require(crop_vector && std::abs(crop_vector->current_to_previous_pixels_x-
                expected_crop_pixels_x)<.001 && crop_vector->current_to_previous_pixels_x>0.,
            "Crop-only source vector has incorrect current-to-previous sign or scale");
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
    follow.guard_fraction=.25f; follow.smoothing_ms=0.f; // v48 instant baseline retained
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
    CropStability freshness;
    const GazeSample real{UV{.7f,.4f},1000,true,false};
    const GazeSample cached{UV{.7f,.4f},1000,false,false};
    require(freshness.update({32,1},3400,3172,follow,real,1000).u==.7f,
            "Fresh mapped gaze was rejected");
    require(freshness.update({32,2},3400,3172,follow,cached,1050).u==.7f,
            "Cached sample must remain valid at 50ms");
    require(freshness.update({32,3},3400,3172,follow,cached,1051).u==.5f,
            "Replayed gaze must not extend its original 50ms expiry");
    freshness.update({32,4},3400,3172,follow,real,2000);
    require(freshness.update({32,5},3400,3172,follow,
                GazeSample{std::nullopt,2001,false,true},2001).u==.5f,
            "Explicit invalidation must discard the held crop immediately");
    State audit;
    // v48 smoothing regression: the UI setting must alter the actual gaze
    // coordinates driving the frozen off-axis projection, not only the UI.
    Settings smooth_settings{};
    smooth_settings.eye_tracked=true;
    smooth_settings.stabilize_crop=false;
    smooth_settings.smoothing_ms=85.f;
    CropStability smoother;
    auto initial=smoother.update({32,1},3000,3000,smooth_settings,UV{.5f,.5f},1000);
    auto halfway=smoother.update({32,2},3000,3000,smooth_settings,UV{.9f,.7f},1016);
    const float alpha=1.f-std::exp(-16.f/85.f);
    require(initial.u==.5f && initial.v==.5f &&
            std::abs(halfway.u-(.5f+.4f*alpha))<.0001f &&
            std::abs(halfway.v-(.5f+.2f*alpha))<.0001f,
            "v48 85ms gaze smoothing not applied before projection");
    auto later=smoother.update({32,3},3000,3000,smooth_settings,UV{.9f,.7f},1032);
    require(later.u>halfway.u && later.u<.9f && later.v>halfway.v,
            "v48 smoothing failed to converge monotonically");
    // Zero ms must restore the exact instant gaze path without filter lag.
    smooth_settings.smoothing_ms=0.f;
    auto zero=smoother.update({32,4},3000,3000,smooth_settings,UV{.2f,.8f},1048);
    require(zero.u==.2f && zero.v==.8f,"v48 zero smoothing did not follow instantly");
    // Heavy smoothing must work at the old slider's maximum.
    smooth_settings.smoothing_ms=250.f;
    auto heavy=smoother.update({32,5},3000,3000,smooth_settings,UV{.8f,.2f},1064);
    require(heavy.u>.2f && heavy.u<.3f && heavy.v<.8f && heavy.v>.7f,
            "v48 250ms smoothing did not attenuate the gaze step");
    const auto same=smoother.update({32,6},3000,3000,smooth_settings,{},1080);
    require(same.u==heavy.u && same.v==heavy.v,
            "v48 missing gaze packet should not advance smoothed crop");
    const auto old_gaze=smoother.update({32,7},3000,3000,smooth_settings,{},1120);
    require(old_gaze.u==.5f && old_gaze.v==.5f,
            "v48 stale gaze must return to center instead of preserving filter history");
    auto reacquire=smoother.update({32,8},3000,3000,smooth_settings,UV{.6f,.4f},1136);
    require(reacquire.u==.6f && reacquire.v==.4f,
            "v48 reacquired gaze must not blend against expired history");
    Settings auds{}; auds.temporal_audit=true; auds.eye_tracked=true;
    require(audit.configure(auds),"Audit settings rejected");
    const std::array<double,16> source_rotation{
        1.,0.,0.,0., 0.,1.,0.,0., 0.,0.,1.,0., 0.,0.,0.,1.};
    auto mark=[&](FrameKey k, UV gaze, uintptr_t primary, uintptr_t secondary, bool expect_gate=true) {
        auto f=audit.begin(k,3400,3172,p,[&]()->std::optional<UV>{return gaze;},1000+k.frame*11);
        require(f.has_value(),"Audit frame missing");
        for (unsigned eye=0;eye<2;++eye) {
            require(audit.rectangle(k,eye) && audit.projection(k,eye) &&
                    audit.camera(k,eye,camera) && audit.scene(k,eye,eye?secondary:primary),
                    "Audit frame view observations failed");
            require(audit.view_transform(k,eye,{0.,0.,0.},source_rotation),
                    "Audit source transform latch failed");
            if (audit.temporal_contract(k,eye))
                require(audit.note_temporal_override(k,eye,true),
                        "Audit temporal bridge result was not recorded");
        }
        require(audit.family(k,true,2),"Audit source family missing");
        const bool consumed=audit.consume(k).has_value();
        require(consumed==expect_gate,"ViewState history gate returned the wrong decision");
    };
    mark({40,1},UV{.5f,.5f},100,200);
    mark({40,2},UV{.7f,.5f},100,200);
    auto d=audit.temporal_audit();
    require(d && d->previous_frame && d->distinct_view_states && d->stable_view_states &&
            d->same_pose && d->moving_fovea && d->expected_crop_motion_px_x > 1.,
            "Temporal moving-crop/previous-state diagnostics inconsistent");
    mark({40,3},UV{.8f,.5f},100,100,false);
    d=audit.temporal_audit();
    require(d && !d->distinct_view_states && !d->stable_view_states && !d->history_gate_pass,
            "Shared temporal history must be blocked");
    mark({40,4},UV{.8f,.5f},300,400,false);
    d=audit.temporal_audit();
    require(d && d->distinct_view_states && !d->stable_view_states && !d->history_gate_pass,
            "Changed temporal identity across frames must be blocked");
    mark({40,5},UV{.8f,.5f},300,400);
    d=audit.temporal_audit();
    require(d && d->history_gate_pass && d->stable_view_states,
            "Stable per-view history must re-enable after one clean pair");
    mark({40,7},UV{.8f,.5f},300,400,false);
    d=audit.temporal_audit();
    require(d && d->history_gap && !d->history_gate_pass,
            "Skipped producer frame must block crop-history continuity");
    mark({40,8},UV{.8f,.5f},300,400);
    auds.fovea_view=1;
    require(audit.configure(auds),"Foveal source switch was rejected");
    mark({40,9},UV{.8f,.5f},300,400,false);
    d=audit.temporal_audit();
    require(d && d->stable_view_states && !d->stable_projection_history &&
            !d->history_gate_pass,
            "Changing which ViewState owns the fovea must block one frame");
    mark({40,10},UV{.8f,.5f},300,400);
    d=audit.temporal_audit();
    require(d && d->stable_projection_history && d->history_gate_pass,
            "Stable foveal source layout should re-enable after one frame");
    // Current rendered color stays world-aligned, including legacy settings.
    State history;
    Settings hs{}; hs.crop_width=hs.crop_height=.30f;
    hs.history_sample_correction=true; hs.history_sample_strength=1.f;
    require(history.configure(hs),"v41 compositor settings rejected");
    auto make_complete=[&](FrameKey k, UV gaze) {
        auto f=history.begin(k,3000,3000,p,[&]()->std::optional<UV>{ return gaze; },1000+k.frame*11);
        require(f.has_value(),"v41 missing frozen frame");
        for(unsigned view=0;view<2;view++) {
            require(history.rectangle(k,view) && history.projection(k,view) &&
                    history.camera(k,view,camera) && history.scene(k,view,100+view),
                    "v41 incomplete pair");
            require(history.view_transform(k,view,{0.,0.,0.},source_rotation),
                    "v41 source transform latch failed");
            if (history.temporal_contract(k,view))
                require(history.note_temporal_override(k,view,true),
                        "v41 temporal bridge result was not recorded");
        }
        require(history.family(k,true,2),"v41 missing main family");
        return history.consume(k);
    };
    auto first=make_complete({61,1},{.5f,.5f});
    require(first && first->config.history_sample_offset.u==0.f &&
            !history.accept_composite({61,0}) &&
            history.accept_composite({61,1}),
            "First copy must be unshifted; only correct copy can seed history");
    auto shifted=make_complete({61,2},{.52f,.49f});
    require(shifted && shifted->config.history_sample_offset.u==0.f &&
            shifted->config.history_sample_offset.v==0.f,
            "Accepted adjacent crop must not displace current color");
    // Deliberately do NOT accept frame 2; next frame must reject frame 1 history.
    auto gap=make_complete({61,3},{.53f,.5f});
    require(gap && gap->config.history_sample_offset.u==0.f &&
            gap->config.history_sample_offset.v==0.f,
            "A failed/skipped composition must not seed a stale crop offset");
    require(history.accept_composite({61,3}),"v41 accepted frame 3 rejected");
    auto jump=make_complete({61,4},{.80f,.5f});
    require(jump && jump->config.history_sample_offset.u==0.f,
            "Large saccade must bypass sampling correction, not delay gaze");
    require(history.accept_composite({61,4}),"v41 accepted frame 4 rejected");
    hs.history_sample_correction=false;
    require(history.configure(hs),"v41 toggle off rejected");
    auto off=make_complete({61,5},{.81f,.5f});
    require(off && off->config.history_sample_offset.u==0.f,
            "A/B disabled must be exactly original compositor sampling");
    hs.history_sample_correction=true;hs.history_sample_strength=.5f;
    require(history.configure(hs),"v41 strength adjustment rejected");
    require(history.accept_composite({61,5}),"v41 accept frame5 rejected");
    auto half=make_complete({61,6},{.82f,.5f});
    require(half && half->config.history_sample_offset.u==0.f && half->config.history_sample_offset.v==0.f,
            "Legacy sampling gain must not move current rendered detail");
    require(history.accept_composite({61,6}),"Frame6 accepted copy missing");
    auto changed=history.begin({61,7},3000,3000,p,
        []()->std::optional<UV>{return UV{.83f,.5f};},1077);
    require(changed.has_value(),"ViewState-change fixture missing");
    for(unsigned v=0;v<2;++v)
        require(history.rectangle({61,7},v) && history.projection({61,7},v) &&
            history.camera({61,7},v,camera) && history.scene({61,7},v,300+v),
            "ViewState-change fixture invalid");
    for(unsigned v=0;v<2;++v)
        require(history.view_transform({61,7},v,{0.,0.,0.},source_rotation),
                "ViewState-change source transform latch failed");
    require(history.family({61,7},true,2),"ViewState-change family missing");
    changed=history.consume({61,7});
    require(!changed && !history.accept_composite({61,7}),
        "Changed Unreal ViewState identity must block eye-tracked composition");
    CameraPose teleport=camera;teleport.position[0]+=2000.0;
    auto cut=history.begin({61,8},3000,3000,p,
        []()->std::optional<UV>{return UV{.84f,.5f};},1088);
    require(cut.has_value(),"Camera-cut fixture missing");
    for(unsigned v=0;v<2;++v)
        require(history.rectangle({61,8},v) && history.projection({61,8},v) &&
            history.camera({61,8},v,teleport) && history.scene({61,8},v,300+v),
            "Camera-cut fixture invalid");
    for(unsigned v=0;v<2;++v) {
        require(history.view_transform({61,8},v,{0.,0.,0.},source_rotation),
                "Camera-cut source transform latch failed");
        if (history.temporal_contract({61,8},v))
            require(history.note_temporal_override({61,8},v,true),
                    "Camera-cut temporal bridge result was not recorded");
    }
    require(history.family({61,8},true,2),"Camera-cut family missing");
    cut=history.consume({61,8});
    require(cut && cut->config.history_sample_offset.u==0.f,
        "Camera teleport must disable stale compositor history correction");
    history.retire();
    require(!history.accept_composite({61,6}),"Retired copy cannot commit history");
    hs.history_sample_strength=1.01f;
    require(!history.configure(hs),"Out-of-range source shift gain accepted");
    hs.history_sample_strength=std::numeric_limits<float>::quiet_NaN();
    require(!history.configure(hs),"NaN source shift gain accepted");
    // Fixed-center remains completely untouched when configured with A/B ON.
    hs.history_sample_strength=1.f;hs.eye_tracked=false;
    require(history.configure(hs),"Fixed-center v41 settings rejected");
    auto fixed=history.begin({62,1},3000,3000,p,[]()->std::optional<UV>{return UV{.87f,.33f};},1400);
    require(fixed && fixed->config.gaze.u==.5f,
            "Fixed-center must not follow sensor when tracking is OFF");
    follow.smoothing_ms=251.f;
    State bad_controls; require(!bad_controls.configure(follow),"Invalid smoothing must be rejected");
    follow.smoothing_ms=85.f; follow.guard_fraction=.251f;
    require(!bad_controls.configure(follow),"Invalid wide guard must be rejected");
    // v48 independent no-history contract: foveal SceneViewState must be
    // withheld on EVERY frame, not only on the first moving-gaze frame.
    State fresh;
    Settings fresh_settings{};
    fresh_settings.crop_width=fresh_settings.crop_height=.30f;
    fresh_settings.eye_tracked=true;
    fresh_settings.fovea_view=0;
    fresh_settings.fresh_fovea_no_history=true;
    require(fresh.configure(fresh_settings),"v48 fresh-fovea configuration rejected");
    auto fresh_frame=[&](FrameKey k,UV uv,bool mark) {
        auto f=fresh.begin(k,3000,3000,m,[&]()->std::optional<UV>{return uv;},2000+k.frame*11);
        require(f.has_value(),"v48 gaze frame missing");
        require(fresh.rectangle(k,0)&&fresh.projection(k,0)&&fresh.camera(k,0,camera)&&fresh.scene(k,0,100),
                "v48 foveal geometry or original source identity failed");
        require(fresh.rectangle(k,1)&&fresh.projection(k,1)&&fresh.camera(k,1,camera)&&fresh.scene(k,1,200),
                "v48 original peripheral view rejected");
        require(fresh.family(k,true,2),"v48 source view pair incomplete");
        std::array<double,16> rot{};rot[0]=rot[5]=rot[10]=rot[15]=1.;
        require(fresh.view_transform(k,0,{0.,0.,0.},rot) &&
                fresh.view_transform(k,1,{0.,0.,0.},rot),"v48 source transforms rejected");
        if (mark) require(fresh.mark_fovea_history_disabled(k,0),"v48 no-history state mark rejected");
        return fresh.consume(k);
    };
    require(!fresh_frame({80,1},UV{.50f,.50f},false),
            "v48 permitted a frame with a persistent foveal history");
    require(fresh_frame({80,2},UV{.50f,.50f},true).has_value(),
            "v48 first fresh foveal frame rejected");
    require(fresh_frame({80,3},UV{.72f,.30f},true).has_value(),
            "v48 moving crop erroneously demanded previous temporal override");
    require(!fresh_frame({80,4},UV{.75f,.32f},false),
            "v48 allowed temporal state to reappear during gaze movement");
    require(fresh_frame({80,5},UV{.78f,.33f},true).has_value(),
            "v48 failed to recover a fresh crop after a missing-history frame");
    // Peripheral source must not be marked as the foveal no-history view.
    require(!fresh.mark_fovea_history_disabled({80,5},1),
            "v48 attempted to invalidate the peripheral temporal history");
    std::cout<<"Pinned Joey DuoView geometry, instant gaze, typed projection, history audit contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}
