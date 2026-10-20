#include "QuadViewGeometry.hpp"
#include "QuadViewGaze.hpp"
#include "DuoViewCropStability.hpp"
#include "QuadViewFramePacket.hpp"
#include "QuadViewDelivery.hpp"
#include "QuadViewProducer.hpp"
#include "QuadViewViewDemand.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>

static bool near(double a, double b) { return std::abs(a - b) < 1e-6; }

struct SourceToken { uint64_t serial{}, pose_frame_token{}; };

static std::array<double, 16> projection_for_test(uint32_t index) {
    // A finite, non-degenerate projection payload. Hashes stand in for the
    // exact constructor fingerprint in this portable producer contract test.
    std::array<double, 16> projection{};
    projection[0] = 1.0 + index * 0.01;
    projection[5] = 1.0;
    projection[10] = 1.0;
    projection[15] = 1.0;
    return projection;
}

static uevr::quadview::gaze::Projection eye_projection(float left, float right, float top, float bottom) {
    uevr::quadview::gaze::Projection p{};
    p[0]=2.f/(right-left); p[5]=2.f/(top-bottom);
    p[8]=-(right+left)/(right-left); p[9]=-(top+bottom)/(top-bottom);
    p[11]=1.f; p[14]=.01f;
    return p;
}

static std::array<std::array<double,4>,4> matrix_columns(const uevr::quadview::gaze::Projection& p) {
    std::array<std::array<double,4>,4> result{};
    for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) result[col][row]=p[col*4+row];
    return result;
}

static uevr::quadview::gaze::Projection flat_matrix(const std::array<std::array<double,4>,4>& m) {
    uevr::quadview::gaze::Projection result{};
    for (int col=0; col!=4; ++col) for (int row=0; row!=4; ++row) result[col*4+row]=static_cast<float>(m[col][row]);
    return result;
}

int main() {
    using namespace uevr::quadview;
    // The supported STALKER 2 game must install the BeginRenderViewFamily
    // callback at injection, even if the active/requested mode is still 0.
    // Rendering-mode ID7 is usually enabled later through the UI.
    constexpr auto family_hook_required = [](bool supported_game, bool selected,
                                              bool requested, bool legacy_need) {
        return supported_game || selected || requested || legacy_need;
    };
    static_assert(family_hook_required(true, false, false, false));
    static_assert(!family_hook_required(false, false, false, false));
    static_assert(family_hook_required(false, true, false, false));
    static_assert(family_hook_required(false, false, true, false));
    const auto layout = make_layout(1800, 1920);
    assert(layout);
    assert(layout->atlas_width == 3600 && layout->atlas_height == 1920);
    assert((layout->views[0] == Rect{0, 0, 360, 384}));
    assert((layout->views[2] == Rect{360, 0, 900, 960}));
    assert((layout->views[1] == Rect{1800, 0, 360, 384}));
    assert((layout->views[3] == Rect{2160, 0, 900, 960}));
    assert(valid_view_index(0) && valid_view_index(3));
    assert(!valid_view_index(-1) && !valid_view_index(4));
    assert(eye_for_view(0) == 0 && eye_for_view(2) == 0);
    assert(eye_for_view(1) == 1 && eye_for_view(3) == 1);
    assert(!is_focus_view(0) && !is_focus_view(1) && is_focus_view(2) && is_focus_view(3));
    assert(!make_layout(10, 10, .9f, .9f, .3f, 1.f)); // Rectangles cannot fit the eye columns.
    Settings initial_settings{};
    assert(initial_settings.sharpen_strength==1.f && !initial_settings.gpu_timing);
    const auto unchanged_settings=reconcile_settings(initial_settings,initial_settings,1800,1920);
    assert(unchanged_settings.rejected==0 && same_settings(unchanged_settings.settings,initial_settings));
    Settings quality_settings{};
    quality_settings.crop_width=.30f; quality_settings.crop_height=.30f;
    quality_settings.context_scale=.20f; quality_settings.foveal_density=2.f;
    const auto accepted_quality=reconcile_settings(quality_settings,initial_settings,1800,1920);
    assert(!(accepted_quality.rejected&(reject_width|reject_height|reject_context|reject_density)) &&
           accepted_quality.settings.crop_width==.30f && accepted_quality.settings.foveal_density==2.f);
    Settings invalid_settings=quality_settings;
    invalid_settings.crop_width=.99f;
    invalid_settings.sharpen_strength=std::numeric_limits<float>::quiet_NaN();
    invalid_settings.diagnostic_view=4;
    invalid_settings.eye_tracked=false;
    const auto retained_settings=reconcile_settings(invalid_settings,accepted_quality.settings,1800,1920);
    assert(retained_settings.rejected&(reject_width|reject_sharpen|reject_diagnostic));
    assert(retained_settings.settings.crop_width==accepted_quality.settings.crop_width &&
           retained_settings.settings.eye_tracked==false && same_settings(retained_settings.settings,
               reconcile_settings(retained_settings.settings,retained_settings.settings,1800,1920).settings));
    Settings rounding_edge{};
    rounding_edge.crop_width=.50f; rounding_edge.crop_height=.50f;
    rounding_edge.context_scale=.50f; rounding_edge.foveal_density=1.f;
    const auto width_101=reconcile_settings(rounding_edge,initial_settings,101,100);
    assert(width_101.rejected&reject_context);
    assert(!width_101.dimension_fallback && width_101.settings.context_scale==.20f);
    const auto width_101_layout=make_layout(101,100,width_101.settings.crop_width,
        width_101.settings.crop_height,width_101.settings.context_scale,
        width_101.settings.foveal_density);
    assert(width_101_layout && width_101_layout->views[0].width+
        width_101_layout->views[2].width<=101);
    const auto resized=reconcile_settings(rounding_edge,rounding_edge,101,100);
    assert(resized.dimension_fallback && resized.rejected==reject_context && resized.settings.crop_width==.50f &&
        resized.settings.context_scale==.20f && make_layout(101,100,
        resized.settings.crop_width,resized.settings.crop_height,resized.settings.context_scale,
        resized.settings.foveal_density));
    LayoutLatch layout_latch;
    const auto frozen_layout=layout_latch.freeze(1,1,*layout);
    const auto changed_controls=make_layout(1800,1920,.30f,.40f,.25f);
    assert(frozen_layout && changed_controls);
    const auto still_frozen=layout_latch.freeze(1,1,*changed_controls);
    assert(still_frozen && still_frozen->views==frozen_layout->views);
    assert(layout_latch.freeze(1,2,*changed_controls)->views==changed_controls->views);

    // One calibrated head-space ray is rotated and projected independently
    // for canted eyes with asymmetric full-eye frusta. The signed yaw check
    // catches a row/column-major transpose mistake in the OpenXR rotation.
    using namespace uevr::quadview::gaze;
    const float yaw=.2f;
    const uevr::duoview::Ray forward_ray{0.f,0.f,1.f};
    const auto signed_rotation=eye_rotation_in_head({0,0,0,1},{0,std::sin(yaw*.5f),0,std::cos(yaw*.5f)});
    assert(signed_rotation);
    const auto signed_eye_ray=uevr::duoview::optical_ray(forward_ray,*signed_rotation);
    assert(signed_eye_ray && near(signed_eye_ray->right,std::sin(yaw)) &&
           near(signed_eye_ray->forward,std::cos(yaw)));
    const std::array<Quaternion,2> eye_orientations{{
        {0.f,std::sin(.07f*.5f),0.f,std::cos(.07f*.5f)},
        {0.f,std::sin(-.04f*.5f),0.f,std::cos(-.04f*.5f)}}};
    const std::array<Projection,2> full_projections{{
        eye_projection(-1.25f,.90f,1.05f,-.72f),
        eye_projection(-.82f,1.38f,.83f,-1.14f)}};
    assert(valid_perspective_projection(full_projections[0]) &&
           valid_perspective_projection(full_projections[1]));
    Projection identity_projection{};
    identity_projection[0]=identity_projection[5]=identity_projection[10]=identity_projection[15]=1.f;
    assert(!valid_perspective_projection(identity_projection));
    const auto fov_left=projection_from_fov(std::atan(-1.25f),std::atan(.90f),
                                             std::atan(1.05f),std::atan(-.72f));
    const auto fov_right=projection_from_fov(std::atan(-.82f),std::atan(1.38f),
                                              std::atan(.83f),std::atan(-1.14f));
    assert(fov_left && fov_right);
    assert(near((*fov_left)[0],full_projections[0][0]) && near((*fov_left)[8],full_projections[0][8]) &&
           near((*fov_left)[5],full_projections[0][5]) && near((*fov_left)[9],full_projections[0][9]));
    assert(near((*fov_right)[0],full_projections[1][0]) && near((*fov_right)[8],full_projections[1][8]) &&
           near((*fov_right)[5],full_projections[1][5]) && near((*fov_right)[9],full_projections[1][9]));
    const std::array<Tangents,2> raw_fovs{{
        *tangents_from_fov(std::atan(-1.25f),std::atan(.90f),std::atan(1.05f),std::atan(-.72f)),
        *tangents_from_fov(std::atan(-.82f),std::atan(1.38f),std::atan(.83f),std::atan(-1.14f))}};
    const auto symmetric=projections_from_fovs(raw_fovs,1,1);
    const auto mirrored=projections_from_fovs(raw_fovs,2,2);
    const auto matched_vertical=projections_from_fovs(raw_fovs,0,2);
    assert(symmetric && mirrored && matched_vertical);
    assert(near((*symmetric)[0][0],(*symmetric)[1][0]) && near((*symmetric)[0][5],(*symmetric)[1][5]) &&
           near((*symmetric)[0][8],0) && near((*symmetric)[1][8],0));
    assert(near((*mirrored)[0][8],-(*mirrored)[1][8]) &&
           near((*mirrored)[0][5],(*mirrored)[1][5]) && near((*mirrored)[0][9],(*mirrored)[1][9]));
    assert(near((*matched_vertical)[0][5],(*matched_vertical)[1][5]) &&
           near((*matched_vertical)[0][9],(*matched_vertical)[1][9]));
    assert(!projection_from_fov(-1.f,1.f,-1.f,1.f)); // Up must exceed down.
    const uevr::duoview::Ray head_ray{.21f,.08f,.974f};
    const auto eye_uv=project_stereo_head_ray(head_ray,{0,0,0,1},eye_orientations,full_projections);
    assert(eye_uv && std::abs((*eye_uv)[0].u-(*eye_uv)[1].u)>.05f &&
           std::abs((*eye_uv)[0].v-(*eye_uv)[1].v)>.02f);
    const auto stereo_layout=make_layout(1800,1920,.36f,.42f,.20f,1.f,
        std::array<FocusPoint,2>{{{(*eye_uv)[0].u,(*eye_uv)[0].v},{(*eye_uv)[1].u,(*eye_uv)[1].v}}});
    assert(stereo_layout);
    for (size_t eye=0; eye!=2; ++eye) {
        const auto& crop=stereo_layout->focus_crops[eye];
        assert(crop.u0>=0 && crop.v0>=0 && crop.u1<=1 && crop.v1<=1);
        assert(near(crop.u1-crop.u0,.36) && near(crop.v1-crop.v0,.42));
        auto cropped=matrix_columns(full_projections[eye]);
        apply_focus_crop(cropped,crop);
        const auto eye_rotation=eye_rotation_in_head({0,0,0,1},eye_orientations[eye]);
        assert(eye_rotation);
        const auto transformed=uevr::duoview::optical_ray(head_ray,*eye_rotation);
        assert(transformed);
        const auto cropped_uv=projection_uv(*transformed,flat_matrix(cropped));
        assert(cropped_uv && near(cropped_uv->u,.5) && near(cropped_uv->v,.5));
    }

    // Independent production CropStability objects consume both eye samples
    // under the same frame key. Each origin snaps on the same two-source-pixel
    // grid and remains frozen after a same-draw settings/gaze change.
    uevr::duoview::Settings stability_settings{};
    stability_settings.crop_width=.36f; stability_settings.crop_height=.42f;
    stability_settings.peripheral_scale=.20f; stability_settings.foveal_density=1.f;
    stability_settings.eye_tracked=true; stability_settings.stabilize_crop=true;
    stability_settings.gaze_quant_pixels=2; stability_settings.gaze_offset_u=0; stability_settings.gaze_offset_v=0;
    uevr::duoview::CropStability left_stability, right_stability;
    const uevr::duoview::FrameKey crop_key{3,19};
    const auto left_center=left_stability.update(crop_key,1800,1920,stability_settings,(*eye_uv)[0],1000);
    const auto right_center=right_stability.update(crop_key,1800,1920,stability_settings,(*eye_uv)[1],1000);
    const auto stable_layout=make_layout(1800,1920,.36f,.42f,.20f,1.f,
        std::array<FocusPoint,2>{{{left_center.u,left_center.v},{right_center.u,right_center.v}}});
    assert(stable_layout);
    const double quant_x=2.0*.36/std::round(1800*.36);
    const double quant_y=2.0*.42/std::round(1920*.42);
    for (const auto& crop : stable_layout->focus_crops) {
        assert(near(std::round(crop.u0/quant_x)*quant_x,crop.u0) || near(crop.u0,1.f-.36f));
        assert(near(std::round(crop.v0/quant_y)*quant_y,crop.v0) || near(crop.v0,1.f-.42f));
    }
    LayoutLatch stereo_latch;
    assert(stereo_latch.freeze(3,19,*stable_layout));
    const auto altered_stereo=make_layout(1800,1920,.36f,.42f,.20f,1.f,
        std::array<FocusPoint,2>{{{.25f,.3f},{.7f,.65f}}});
    assert(altered_stereo);
    const auto still_same_draw=stereo_latch.freeze(3,19,*altered_stereo);
    assert(still_same_draw && still_same_draw->focus_crops==stable_layout->focus_crops);

    DrawDemandLatch draw_demand;
    const auto first_draw=draw_demand.begin(1,10,true,false,20);
    assert(first_draw.view_count==4 && first_draw.source_admission);
    // Simulate a UI transition arriving between view 0 and view 2. Re-reading
    // the current draw still yields its original four-view demand.
    const auto between_callbacks=draw_demand.get(1,10);
    assert(between_callbacks && between_callbacks->view_count==4 && between_callbacks->source_admission);
    assert(!draw_demand.transition_closed(1,10,21,true,true)); // Present cannot ack the new request yet.
    Delivery<SourceToken, 4> late_owner_drain;
    assert(late_owner_drain.engine_commands_retired(1)); // Empty before final GT family publication.
    Delivery<SourceToken, 4>::EngineTicket late_ticket{1, 21, 700, 0x701, 0x801, 0x901};
    assert(late_owner_drain.register_engine_family(late_ticket)); // Current four-view draw publishes after the empty check.
    const auto next_draw=draw_demand.begin(1,11,true,true,21);
    assert(next_draw.view_count==2 && !next_draw.source_admission);
    assert(!draw_demand.get(1,10)); // The next boundary invalidates stale draw keys.
    assert(draw_demand.get(1,11)->view_count==2);
    assert(draw_demand.transition_closed(1,11,21,true,true));
    assert(!draw_demand.transition_closed(1,11,22,true,true)); // Reopened/cancelled request cannot reuse stale ack.
    assert(!late_owner_drain.engine_commands_retired(1));
    const auto late_rt=late_owner_drain.render_engine_family(1,700,late_ticket.target,late_ticket.scene);
    assert(late_rt && late_owner_drain.tail_hooked_engine_family(*late_rt,{},0x902));
    assert(late_owner_drain.executed_engine_family(*late_rt,{},0x902,45));
    assert(late_owner_drain.engine_commands_retired(1));

    // Off-axis perspective with nonzero x/y translation terms. Cropping both
    // rows must preserve the full w row, depth row, and the requested UV map.
    std::array<std::array<double, 4>, 4> projection{{
        {{1.7, 0.0, 0.0, 0.0}},
        {{0.0, 2.1, 0.0, 0.0}},
        {{0.19, -0.11, 1.0, 1.0}},
        {{0.0, 0.0, -0.1, 0.0}},
    }};
    const auto original = projection;
    apply_focus_crop(projection, layout->focus_crops[0]);
    for (int col = 0; col != 4; ++col) {
        assert(near(projection[col][2], original[col][2]));
        assert(near(projection[col][3], original[col][3]));
    }
    const auto project = [](const auto& p, double x, double y, double z) {
        std::array<double, 4> out{};
        const std::array<double, 4> v{x, y, z, 1.0};
        for (int c = 0; c != 4; ++c) for (int r = 0; r != 4; ++r) out[r] += p[c][r] * v[c];
        return std::array<double, 2>{out[0] / out[3], out[1] / out[3]};
    };
    for (const auto uv : {std::array<double,2>{layout->focus_crops[0].u0, layout->focus_crops[0].v0},
                          std::array<double,2>{layout->focus_crops[0].u1, layout->focus_crops[0].v1},
                          std::array<double,2>{.41, .63}}) {
        // Project an off-axis point through the complete matrix, then verify
        // the crop applies the exact affine map to its existing clip position.
        const auto full = project(original, uv[0] * 2.0 - 1.0, 1.0 - uv[1] * 2.0, -1.0);
        const auto cropped = project(projection, uv[0] * 2.0 - 1.0, 1.0 - uv[1] * 2.0, -1.0);
        const auto expected_x = (full[0] + 1.0 - layout->focus_crops[0].u0 - layout->focus_crops[0].u1) /
            (layout->focus_crops[0].u1 - layout->focus_crops[0].u0);
        const auto expected_y = (full[1] + layout->focus_crops[0].v0 + layout->focus_crops[0].v1 - 1.0) /
            (layout->focus_crops[0].v1 - layout->focus_crops[0].v0);
        assert(near(cropped[0], expected_x));
        assert(near(cropped[1], expected_y));
    }

    Producer producer;
    const Key key{7, 12};
    const Key abandoned{7, 11};
    assert(producer.begin(abandoned, 90, 0x100, 0x200, *layout));
    Settings source_settings{};
    source_settings.crop_width=.42f; source_settings.sharpen_strength=1.5f; source_settings.gpu_timing=true;
    GazeEvidence source_gaze{};
    source_gaze.sampled=true; source_gaze.ray_valid=true; source_gaze.reader_available=true;
    source_gaze.reader_active=true; source_gaze.sample_tick=123456; source_gaze.age_ms=3; source_gaze.fresh=21;
    assert(producer.begin(key, 91, 0x100, 0x200, *layout, source_settings, 17,source_gaze));
    const auto frozen_source_settings=producer.snapshot(key);
    assert(frozen_source_settings && frozen_source_settings->settings_revision==17 &&
           frozen_source_settings->settings.crop_width==.42f && frozen_source_settings->settings.sharpen_strength==1.5f &&
           frozen_source_settings->settings.gpu_timing && frozen_source_settings->gaze.sampled &&
           frozen_source_settings->gaze.ray_valid && frozen_source_settings->gaze.sample_tick==123456 &&
           frozen_source_settings->gaze.age_ms==3 && frozen_source_settings->gaze.fresh==21);
    source_settings.crop_width=.25f;
    const auto same_transaction_settings=producer.snapshot(key);
    assert(same_transaction_settings && same_transaction_settings->settings.crop_width==.42f);
    assert(!producer.snapshot(abandoned)); // Incomplete draw is retired by the next Draw.
    std::array<uintptr_t, 4> views{0x1000, 0x2000, 0x3000, 0x4000};
    std::array<uintptr_t, 4> states{0x11, 0x22, 0x33, 0x44};
    for (uint32_t i = 0; i != 4; ++i)
        assert(producer.projection_call(key, static_cast<int32_t>(i), 0xabc0 + i, projection_for_test(i)));
    assert(producer.camera(key, 0, CameraPose{{1.0, 2.0, 3.0}, {-0.032, 0.0, 0.0}, true}));
    assert(producer.camera(key, 1, CameraPose{{1.0, 2.0, 3.0}, {0.032, 0.0, 0.0}, true}));
    for (uint32_t i = 0; i != 4; ++i) {
        assert(producer.rectangle_call(key, static_cast<int32_t>(i)));
        assert(producer.constructed(key, 0x300, 0x200, 0x100,
            views[i], states[i], layout->views[i], 0xabc0 + i));
    }
    assert(producer.main_family(key, 91, 0x300, 0x200, 0x100, views));
    auto snapshot = producer.snapshot(key);
    assert(snapshot && snapshot->histories_complete());
    assert(snapshot->hook_rect_calls == 4 && snapshot->hook_projection_calls == 4);
    const auto frozen = producer.frozen(key);
    assert(frozen && frozen->engine_frame == 91);
    auto source_hold = std::make_shared<uint64_t>(0x500);
    std::weak_ptr<uint64_t> source_weak = source_hold;
    const auto make_eye = [](uint64_t frame, float x) {
        return RuntimeEye{frame, {0.f, 0.f, 0.f, 1.f}, {x, 0.f, 0.f},
            {-1.f, 1.f, 1.f, -1.f},
            {1.f, 0.f, 0.f, 0.f, 0.f, 1.f, 0.f, 0.f,
             0.f, 0.f, 1.f, 1.f, 0.f, 0.f, -0.1f, 0.f}, true};
    };
    const auto eyes = std::array{make_eye(0, -0.032f), make_eye(0, 0.032f)};
    const RhiExecutionEvidence execution{91, 0x300, 0x100, 0x200, 0x600, 123, true, true, true};
    const auto packet = bind_frame_packet(frozen, 0x500, source_hold, 0, execution, eyes);
    assert(packet && packet->valid() && packet->eyes[0].frame_token == packet->eyes[1].frame_token);
    source_hold.reset();
    assert(!source_weak.expired()); // The packet retains the resource owner.
    auto unexecuted = execution;
    unexecuted.command_executed = false;
    assert(!bind_frame_packet(frozen, 0x500, source_hold, 0, unexecuted, eyes));
    auto stale_eyes = eyes;
    stale_eyes[1].frame_token = 1;
    assert(!bind_frame_packet(frozen, 0x500, source_hold, 0, execution, stale_eyes));
    assert(!producer.note_compositor_record(key, 0, 0x600));
    assert(producer.note_compositor_record(key, 0x500, 0x600));
    const auto evidence = producer.compositor_evidence(key);
    assert(evidence && evidence->submits == 1 && evidence->last_source_resource == 0x500);
    assert(frozen->engine_frame == 91); // A separate draw cannot mutate frozen evidence.

    assert(producer.begin(Key{7, 13}, 92, 0x100, 0x200, *layout));
    assert(!producer.frozen(key)); // The producer ledger retires stale keys at the next draw.
    assert(frozen->engine_frame == 91); // Packets keep their immutable snapshot independently.
    assert(!producer.retire(key));
    assert(!producer.snapshot(key));
    assert(packet->valid()); // A render-slot reference survives producer-ledger retirement.
    const Key duplicate_key{7, 14};
    assert(producer.begin(duplicate_key, 93, 0x100, 0x200, *layout));
    for (uint32_t i = 0; i != 4; ++i)
        assert(producer.projection_call(duplicate_key, static_cast<int32_t>(i), 0xabc0 + i, projection_for_test(i)));
    states[3] = states[2];
    for (uint32_t i = 0; i != 4; ++i) {
        const auto accepted = producer.constructed(duplicate_key, 0x300, 0x200, 0x100,
            views[i], states[i], layout->views[i], 0xabc0 + i);
        assert(accepted == (i < 3));
    }
    assert(!producer.main_family(duplicate_key, 93, 0x300, 0x200, 0x100, views));

    const Key mixed_family{7, 15};
    assert(producer.begin(mixed_family, 94, 0x100, 0x200, *layout));
    for (uint32_t i = 0; i != 4; ++i)
        assert(producer.projection_call(mixed_family, static_cast<int32_t>(i), 0xabc0 + i, projection_for_test(i)));
    for (uint32_t i = 0; i != 4; ++i) {
        const auto accepted = producer.constructed(mixed_family, i == 3 ? 0x301 : 0x300, 0x200, 0x100,
            views[i], static_cast<uintptr_t>(0x50 + i), layout->views[i], 0xabc0 + i);
        assert(accepted == (i < 3));
    }
    assert(!producer.main_family(mixed_family, 94, 0x300, 0x200, 0x100, views));
    producer.retire_generation(7);
    assert(!producer.snapshot(Key{7, 13}) && !producer.snapshot(duplicate_key));
    assert(producer.begin(Key{8, 1}, 95, 0x100, 0x200, *layout));

    Delivery<SourceToken> delivery;
    const auto token = std::make_shared<const SourceToken>(SourceToken{21, 0});
    const Delivery<SourceToken>::Source source_registration{token, 8, 21, 0xffffffffu, 0, 0x300, 0x100, 0x200,
        {0x110, 0x120, 0x130, 0x140}};
    assert(delivery.family(source_registration));
    const auto source_bound = delivery.bind_engine_frame(8, 21, 0x300, 0x100, 0x200,
        source_registration.view_ids, 95);
    assert(source_bound && source_bound->engine_frame_bound && source_bound->engine_frame == 95);
    const auto& source = *source_bound;
    const auto rendered = delivery.render(8, 95, 0x3ff, 0x100, 0x200); // Render-thread family may be a copy.
    assert(rendered && rendered->same_owner(source));
    assert(!delivery.select(8, 123)); // A source is ineligible before its RHI command executes.
    assert(delivery.tail_hooked(source, 0x700));
    assert(delivery.executed(source, 0x700, 123));
    uintptr_t executed_command{};
    uint32_t executed_thread{};
    assert(delivery.execution_evidence(source, executed_command, executed_thread));
    assert(executed_command == 0x700 && executed_thread == 123);
    assert(!delivery.select(8, 456)); // The RHI execution thread must own submission.
    const auto selected = delivery.select(8, 123);
    assert(selected && selected->same_owner(source));
    const auto retry_after_temporary_slot_miss = delivery.select(8, 123);
    assert(retry_after_temporary_slot_miss && retry_after_temporary_slot_miss->same_owner(source));
    assert(!delivery.submitted(source, 0)); // A missing destination does not consume the source.
    assert(delivery.select(8, 123));
    assert(delivery.submitted(source, 0x800));
    assert(!delivery.select(8, 123)); // Duplicate Present cannot resubmit an accepted source.

    // The direct GT producer must publish already frame-bound atomically.
    {
        Delivery<SourceToken> immediate;
        const std::array<uintptr_t,4> views{0x101,0x102,0x103,0x104};
        auto packet=std::make_shared<const SourceToken>(SourceToken{70,5});
        Delivery<SourceToken>::Source owner{packet,19,70,975,5,0x100,0x200,0x300,views};
        assert(immediate.register_bound(owner));
        const auto chosen=immediate.render(19,975,0x500,0x200,0x300);
        assert(chosen && chosen->serial==70 && chosen->engine_frame_bound);
        assert(!immediate.register_bound(owner));
        Delivery<SourceToken>::Source sentinel{packet,19,71,0xffffffffu,5,0x101,0x200,0x300,views};
        assert(!immediate.register_bound(sentinel));
    }

    // A staged GT observation must precede source registration, which is
    // itself in the outer renderer hook. The old Build 9 ordering attempted
    // bind_engine_frame before any source existed and always failed closed.
    {
        Delivery<SourceToken> staged;
        const std::array<uintptr_t,4> ids{0x11,0x22,0x33,0x44};
        assert(!staged.observe_gt_frame(12,56,0x100,0x200,0x300,ids,0xffffffffu));
        assert(staged.observe_gt_frame(12,56,0x100,0x200,0x300,ids,433));
        assert(!staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,{0x11,0x22,0x33,0x55}));
        const auto assigned = staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,ids);
        assert(assigned && *assigned == 433);
        assert(!staged.take_observed_gt_frame(12,57,0x100,0x200,0x300,ids));
        assert(!staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,ids));
        const auto packet=std::make_shared<const SourceToken>(SourceToken{56,3});
        const Delivery<SourceToken>::Source src{packet,12,56,0xffffffffu,3,0x100,0x200,0x300,ids};
        assert(staged.family(src));
        const auto bound=staged.bind_engine_frame(12,56,0x100,0x200,0x300,ids,*assigned);
        assert(bound && bound->engine_frame_bound && bound->engine_frame==433);
        assert(staged.render(12,433,0x170,0x200,0x300));
        // Reused family storage must not inherit the previous consumed ticket.
        assert(!staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,ids));
        assert(staged.observe_gt_frame(12,56,0x100,0x200,0x300,ids,434));
        assert(staged.observe_gt_frame(12,56,0x100,0x200,0x300,{0x11,0x22,0x33,0x66},435));
        assert(!staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,ids));
        assert(staged.take_observed_gt_frame(12,56,0x100,0x200,0x300,{0x11,0x22,0x33,0x66}) == 435);
    }

    // A newer draw can reuse the same atlas target. Its own pose token and RHI
    // command keep it distinct from the source still being presented.
    const auto token2 = std::make_shared<const SourceToken>(SourceToken{22, 1});
    const Delivery<SourceToken>::Source source2_registration{token2, 8, 22, 0xffffffffu, 1, 0x301, 0x100, 0x200,
        {0x210, 0x220, 0x230, 0x240}};
    assert(delivery.family(source2_registration));
    const auto source2_bound = delivery.bind_engine_frame(8, 22, 0x301, 0x100, 0x200,
        source2_registration.view_ids, 96);
    assert(source2_bound);
    const auto& source2 = *source2_bound;
    const auto rendered2 = delivery.render(8, 96, 0x901, 0x100, 0x200);
    assert(rendered2 && rendered2->same_owner(source2));
    assert(delivery.tail_hooked(source2, 0x701));
    assert(delivery.executed(source2, 0x701, 123));
    const auto selected2 = delivery.select(8, 123);
    assert(selected2 && selected2->same_owner(source2));
    assert(selected2->packet->pose_frame_token == 1); // Render-ahead picks the newer packet and its own pose.
    assert(delivery.submitted(source2, 0x801));
    assert(!delivery.select(8, 123));
    assert(delivery.retire(8, 21));
    assert(delivery.retire(8, 22));

    Delivery<SourceToken> ambiguous_delivery;
    const auto ambiguous_a = std::make_shared<const SourceToken>(SourceToken{41, 4});
    const auto ambiguous_b = std::make_shared<const SourceToken>(SourceToken{42, 5});
    const Delivery<SourceToken>::Source ambiguous_source_a{ambiguous_a, 9, 41, 0xffffffffu, 4, 0x301, 0x100, 0x200,
        {0x310, 0x320, 0x330, 0x340}};
    const Delivery<SourceToken>::Source ambiguous_source_b{ambiguous_b, 9, 42, 0xffffffffu, 5, 0x302, 0x100, 0x200,
        {0x410, 0x420, 0x430, 0x440}};
    assert(ambiguous_delivery.family(ambiguous_source_a));
    assert(ambiguous_delivery.family(ambiguous_source_b));
    const auto ambiguous_bound = ambiguous_delivery.bind_engine_frame(9, 41, 0x301, 0x100, 0x200,
        ambiguous_source_a.view_ids, 100);
    assert(ambiguous_bound);
    assert(!ambiguous_delivery.bind_engine_frame(9, 42, 0x302, 0x100, 0x200,
        ambiguous_source_b.view_ids, 100)); // A reused target/scene/frame tuple cannot acquire a second owner.
    const auto non_ambiguous_render = ambiguous_delivery.render(9, 100, 0x3ff, 0x100, 0x200);
    assert(non_ambiguous_render && non_ambiguous_render->same_owner(*ambiguous_bound));

    Delivery<SourceToken, 2> startup_recovery;
    const auto startup_a = std::make_shared<const SourceToken>(SourceToken{51, 6});
    const auto startup_b = std::make_shared<const SourceToken>(SourceToken{52, 7});
    const auto startup_c = std::make_shared<const SourceToken>(SourceToken{53, 8});
    const Delivery<SourceToken, 2>::Source startup_source_a{startup_a, 10, 51, 0xffffffffu, 6, 0x311, 0x100, 0x200,
        {0x510, 0x520, 0x530, 0x540}};
    const Delivery<SourceToken, 2>::Source startup_source_b{startup_b, 10, 52, 0xffffffffu, 7, 0x312, 0x100, 0x200,
        {0x610, 0x620, 0x630, 0x640}};
    const Delivery<SourceToken, 2>::Source startup_source_c{startup_c, 10, 53, 0xffffffffu, 8, 0x313, 0x100, 0x200,
        {0x710, 0x720, 0x730, 0x740}};
    assert(startup_recovery.family(startup_source_a));
    assert(startup_recovery.family(startup_source_b));
    assert(startup_recovery.family(startup_source_c)); // Oldest never-hooked registration is recycled.
    assert(!startup_recovery.bind_engine_frame(10, 51, 0x311, 0x100, 0x200, startup_source_a.view_ids, 201));
    assert(startup_recovery.bind_engine_frame(10, 52, 0x312, 0x100, 0x200, startup_source_b.view_ids, 202));
    const auto startup_source_c_bound = startup_recovery.bind_engine_frame(10, 53, 0x313, 0x100, 0x200,
        startup_source_c.view_ids, 203);
    assert(startup_source_c_bound);
    assert(!startup_recovery.render(10, 201, 0x911, 0x100, 0x200));
    const auto newest_render = startup_recovery.render(10, 203, 0x913, 0x100, 0x200);
    assert(newest_render && newest_render->same_owner(*startup_source_c_bound));
    assert(startup_recovery.tail_hooked(*startup_source_c_bound, 0x753));
    assert(startup_recovery.executed(*startup_source_c_bound, 0x753, 123));
    const auto newest_selected = startup_recovery.select(10, 123);
    assert(newest_selected && newest_selected->same_owner(*startup_source_c_bound));

    // A committed ID7 transition closes new admission at the next viewport
    // boundary, while already queued render/RHI owners remain drainable.
    assert(desired_view_count(true, true, false) == 4);
    assert(desired_view_count(true, true, false, true) == 2);
    assert(source_admission_open(true, false));
    assert(!source_admission_open(true, true));
    Delivery<SourceToken, 4> lead_drain;
    Delivery<SourceToken, 4>::EngineTicket lead1{11, 60, 401, 0x601, 0x701, 0x801};
    Delivery<SourceToken, 4>::EngineTicket lead2{11, 61, 402, 0x602, 0x702, 0x802};
    assert(lead_drain.register_engine_family(lead1));
    assert(lead_drain.register_engine_family(lead2)); // Two GT families can lead the RT.
    assert(!source_admission_open(true, true)); // Pending draw boundary admits no third family.
    assert(!lead_drain.engine_commands_retired(11));
    const auto lead2_rt=lead_drain.render_engine_family(11,402,lead2.target,lead2.scene);
    assert(lead2_rt && lead_drain.tail_hooked_engine_family(*lead2_rt,{},0x902));
    assert(lead_drain.executed_engine_family(*lead2_rt,{},0x902,43));
    assert(!lead_drain.engine_commands_retired(11)); // The earlier RT owner still blocks.
    const auto lead1_rt=lead_drain.render_engine_family(11,401,lead1.target,lead1.scene);
    assert(lead1_rt && lead_drain.tail_hooked_engine_family(*lead1_rt,{},0x901));
    assert(lead_drain.executed_engine_family(*lead1_rt,{},0x901,44));
    assert(lead_drain.engine_commands_retired(11));
    Delivery<SourceToken, 4> transition_drain;
    Delivery<SourceToken, 4>::EngineTicket queued{11, 60, 401, 0x601, 0x701, 0x801};
    assert(transition_drain.register_engine_family(queued));
    assert(transition_drain.register_engine_family(queued)); // Duplicate callback is idempotent.
    assert(transition_drain.pending_engine_commands(11) == 1);
    assert(!transition_drain.engine_commands_retired(11));
    assert(!transition_drain.render_engine_family(11, 400, queued.target, queued.scene));
    const auto delayed_rt = transition_drain.render_engine_family(11, 401, queued.target, queued.scene);
    assert(delayed_rt && delayed_rt->same_owner(queued));
    assert(!transition_drain.render_engine_family(11, 401, queued.target, queued.scene));
    assert(transition_drain.tail_hooked_engine_family(*delayed_rt, {}, 0x901));
    assert(!transition_drain.tail_hooked_engine_family(*delayed_rt, {}, 0x902));
    assert(!transition_drain.executed_engine_family(*delayed_rt, {}, 0x902, 42));
    assert(!transition_drain.engine_commands_retired(11)); // Missing or delayed tail cannot pass drain.
    assert(transition_drain.executed_engine_family(*delayed_rt, {}, 0x901, 42));
    assert(transition_drain.engine_commands_retired(11));

    Delivery<SourceToken, 2> saturated_drain;
    assert(saturated_drain.register_engine_family({12, 1, 1, 0x101, 0x201, 0x301}));
    assert(saturated_drain.register_engine_family({12, 2, 2, 0x102, 0x202, 0x302}));
    assert(!saturated_drain.register_engine_family({12, 3, 3, 0x103, 0x203, 0x303}));
    assert(saturated_drain.engine_tracking_overflowed(12));
    assert(!saturated_drain.engine_commands_retired(12));

    Delivery<SourceToken, 4> paired_drain;
    const auto paired_packet=std::make_shared<const SourceToken>(SourceToken{61,9});
    Delivery<SourceToken,4>::Source paired_source{paired_packet,13,61,0,9,0xa01,0xb01,0xc01,
        {0x110,0x120,0x130,0x140}};
    Delivery<SourceToken,4>::EngineTicket paired_engine{13,61,0,0xa01,0xb01,0xc01};
    assert(paired_drain.register_engine_family(paired_engine));
    assert(paired_drain.register_bound(paired_source)); // Assigned Unreal frame zero remains valid.
    const auto paired_render=paired_drain.render_engine_family(13,0,0xb01,0xc01);
    const auto paired_owner=paired_drain.render(13,0,0xa11,0xb01,0xc01);
    assert(paired_render && paired_owner);
    assert(paired_drain.tail_hooked_engine_family(*paired_render,*paired_owner,0xd01));
    assert(!paired_drain.engine_commands_retired(13));
    assert(paired_drain.executed_engine_family(*paired_render,*paired_owner,0xd01,42));
    assert(paired_drain.engine_commands_retired(13));

    // Render-ahead may queue a newer family before its RHI command executes.
    // Keep the older completed image eligible until actual atlas overwrite.
    const auto token3 = std::make_shared<const SourceToken>(SourceToken{31, 2});
    const Delivery<SourceToken>::Source source3_registration{token3, 8, 31, 0xffffffffu, 2, 0x302, 0x100, 0x200,
        {0x810, 0x820, 0x830, 0x840}};
    assert(delivery.family(source3_registration));
    const auto source3_bound = delivery.bind_engine_frame(8, 31, 0x302, 0x100, 0x200, source3_registration.view_ids, 97);
    assert(source3_bound);
    const auto& source3 = *source3_bound;
    assert(delivery.render(8, 97, 0x302, 0x100, 0x200));
    assert(delivery.tail_hooked(source3, 0x702));
    assert(delivery.executed(source3, 0x702, 123));
    const auto token4 = std::make_shared<const SourceToken>(SourceToken{32, 3});
    const Delivery<SourceToken>::Source source4_registration{token4, 8, 32, 0xffffffffu, 3, 0x303, 0x100, 0x200,
        {0x910, 0x920, 0x930, 0x940}};
    assert(delivery.family(source4_registration));
    const auto held_while_render_ahead = delivery.select(8, 123);
    assert(held_while_render_ahead && held_while_render_ahead->same_owner(source3));
    const auto source4_bound = delivery.bind_engine_frame(8, 32, 0x303, 0x100, 0x200, source4_registration.view_ids, 98);
    assert(source4_bound);
    const auto& source4 = *source4_bound;
    assert(delivery.render(8, 98, 0x303, 0x100, 0x200));
    assert(delivery.tail_hooked(source4, 0x703));
    assert(delivery.executed(source4, 0x703, 123));
    const auto selected_after_new_execution = delivery.select(8, 123);
    assert(selected_after_new_execution && selected_after_new_execution->same_owner(source4));
    assert(!delivery.select(8, 456));
    delivery.retire(8, 32);

    std::cout << "QuadView geometry, crop, eye mapping, histories, frame ownership, RHI execution, and pose-token contracts passed.\n";
}
