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
    // The Native packet carries the exact Mono pose token observed when its
    // immutable DuoView snapshot was published. It is independent of the
    // engine frame/key arithmetic and remains safe across duplicate Presents.
    State packet_state;
    Settings packet_settings{}; packet_settings.eye_tracked=false;
    require(packet_state.configure(packet_settings),"Native packet settings rejected");
    const FrameKey packet_key{12,200};
    constexpr uint32_t packet_mono_source=37;
    auto packet_source=packet_state.begin(packet_key,3000,3000,m,
        []()->std::optional<UV>{return UV{.5f,.5f};},0,packet_mono_source);
    require(packet_source && !native_frame_binding(*packet_source),
            "Incomplete Native packet must not establish an XR source binding");
    require(packet_state.family(packet_key,true,2) &&
            packet_state.rectangle(packet_key,0) && packet_state.rectangle(packet_key,1) &&
            packet_state.projection(packet_key,0) && packet_state.projection(packet_key,1) &&
            packet_state.camera(packet_key,0,camera) && packet_state.camera(packet_key,1,camera),
            "Native source-pair observations rejected");
    auto immutable_packet=packet_state.snapshot(packet_key);
    const auto binding=immutable_packet ? native_frame_binding(*immutable_packet) : std::nullopt;
    require(binding && binding->key==packet_key && binding->mono_source_frame==packet_mono_source &&
            binding->mono_source_frame!=packet_key.frame-1,
            "Native packet must carry the explicitly observed Mono pose token");
    require(packet_state.consume(packet_key).has_value() &&
            !native_frame_binding(*packet_state.snapshot(packet_key)) &&
            native_frame_binding(*immutable_packet).has_value(),
            "Immutable packet binding must survive live-state consumption for duplicate Presents");
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
    State repeated_pose_draws;
    Settings repeat_settings{}; repeat_settings.eye_tracked=false;
    require(repeated_pose_draws.configure(repeat_settings),"Repeated-pose settings rejected");
    CameraPose moved_camera=camera; moved_camera.position[0]+=1.;
    for (uint64_t draw : {1u,2u}) {
        const FrameKey draw_key{20,draw};
        require(repeated_pose_draws.begin(draw_key,3000,3000,m,
            []()->std::optional<UV>{return UV{.5f,.5f};},0,37).has_value(),
            "Distinct draws sharing one XR pose need independent source transactions");
        const auto& draw_camera=draw==1 ? camera : moved_camera;
        require(repeated_pose_draws.family(draw_key,true,2) &&
            repeated_pose_draws.rectangle(draw_key,0) && repeated_pose_draws.rectangle(draw_key,1) &&
            repeated_pose_draws.projection(draw_key,0) && repeated_pose_draws.projection(draw_key,1) &&
            repeated_pose_draws.camera(draw_key,0,draw_camera) && repeated_pose_draws.camera(draw_key,1,draw_camera),
            "Distinct draw camera should not invalidate a previous draw sharing its pose token");
        const auto transaction=repeated_pose_draws.snapshot(draw_key);
        require(transaction && native_frame_binding(*transaction) && transaction->mono_source_frame==37,
            "Independent draw identity must preserve the exact XR source pose token");
    }
    SubmitContinuity continuity;
    require(!continuity.can_hold(7,123,1000),"Startup must not invent a last-good scene");
    continuity.submitted(7,123,1000);
    require(continuity.can_hold(7,123,1025) && continuity.can_hold(7,123,1100),
            "A short missing-pair gap should retain the last submitted scene");
    require(!continuity.can_hold(7,123,1101) && !continuity.can_hold(7,123,999),
            "Held frames must expire without refreshing their original age");
    require(!continuity.can_hold(8,123,1025) && !continuity.can_hold(7,124,1025) &&
            !continuity.can_hold(7,0,1025),"Held scenes cannot cross mode or swapchain changes");
    continuity.reset();
    require(!continuity.can_hold(7,123,1025),"Acquiring another scene must invalidate the held image");
    continuity.submitted(7,123,1200);
    require(continuity.can_hold(7,123,1250),"A fresh successful submit should recover continuity");
    std::cout<<"Pinned Joey DuoView geometry, view pairing, generation, primary fallback contract PASS\n";
    return 0;
} catch(const std::exception& e) {
    std::cerr<<"DuoView contract test failure: "<<e.what()<<"\n";
    return 1;
}

