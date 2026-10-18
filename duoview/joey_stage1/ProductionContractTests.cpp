#include <array>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include "DuoViewState.hpp"

using namespace uevr::duoview;
static void require(bool test, const char* what) {
    if (!test) throw std::runtime_error(what);
}
int main() try {
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
    // Time-domain stability contract (v24c saccadic): the ROI holds static
    // for crop_hold_ms after each move so temporal systems converge, then
    // snaps (single-frame jump) to the new gaze. No perpetual glide.
    CropStability smoother;
    Settings follow{};
    follow.stabilize_crop=true;
    follow.crop_width=follow.crop_height=.5f;
    follow.guard_fraction=.10f;
    follow.smoothing_ms=85.f;
    auto centre=smoother.update({31,1},3400,3172,follow,UV{.5f,.5f},1000);
    auto noise=smoother.update({31,2},3400,3172,follow,UV{.51f,.49f},1011);
    require(centre.u==noise.u && centre.v==noise.v,"Fixation noise moved stable crop");
    // Large saccade inside the hold window must NOT move the ROI.
    auto held_saccade=smoother.update({31,3},3400,3172,follow,UV{.9f,.8f},1022);
    require(held_saccade.u==centre.u && held_saccade.v==centre.v,
            "Saccade inside hold window moved the crop; projection must stay static");
    // After the hold expires the ROI snaps directly to the gaze.
    auto snapped=smoother.update({31,4},3400,3172,follow,UV{.9f,.8f},1090);
    require(snapped.u>centre.u && snapped.v>centre.v,
            "Expired hold must snap the crop to the gaze");
    // While the hold is active the ROI is frozen even under continuous gaze motion.
    auto last=snapped;
    for (uint64_t f=5;f<11;++f) {
        auto next=smoother.update({31,f},3400,3172,follow,UV{.9f,.8f},1090+(f-4)*11);
        require(next.u==last.u && next.v==last.v,"Crop moved inside the hold window");
        last=next;
    }
    // Glide fallback (crop_snap=false, no hold) still moves gradually.
    CropStability glider;
    Settings glide{};
    glide.stabilize_crop=true;
    glide.crop_width=glide.crop_height=.5f;
    glide.guard_fraction=.10f;
    glide.smoothing_ms=85.f;
    glide.crop_hold_ms=0;
    glide.crop_snap=false;
    auto gcentre=glider.update({32,1},3400,3172,glide,UV{.5f,.5f},2000);
    auto gslow=glider.update({32,2},3400,3172,glide,UV{.9f,.8f},2011);
    require(gslow.u>gcentre.u && gslow.u<.55f && gslow.v>gcentre.v && gslow.v<.55f,
            "Glide fallback must move gradually, not jump");
    auto glast=gslow;
    for (uint64_t f=3;f<12;++f) {
        auto gnext=glider.update({32,f},3400,3172,glide,UV{.9f,.8f},2000+(f-1)*11);
        require(gnext.u>=glast.u && gnext.v>=glast.v,"Glide must be monotonic toward a fixed target");
        require(gnext.u-glast.u<=.035f && gnext.v-glast.v<=.035f,
                "Glide frame-to-frame jump exceeds bounded tracking speed");
        glast=gnext;
    }
    auto held=smoother.update({31,30},3400,3172,follow,{},1360);
    require(held.u==last.u && held.v==last.v,"Short CAPI gap changed crop");
    auto back=smoother.update({31,31},3400,3172,follow,{},1620);
    require(back.u<held.u && back.u>.5f,"Expired gaze must return gently rather than teleport");
    follow.smoothing_ms=251.f;
    State bad_controls; require(!bad_controls.configure(follow),"Invalid smoothing must be rejected");
    follow.smoothing_ms=85.f; follow.guard_fraction=.251f;
    require(!bad_controls.configure(follow),"Invalid wide guard must be rejected");
    follow.guard_fraction=.10f; follow.crop_hold_ms=501;
    require(!bad_controls.configure(follow),"Invalid crop hold must be rejected");
    follow.crop_hold_ms=80;
    std::cout<<"Pinned Joey DuoView geometry, view pairing, gradual gaze, primary fallback contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}
