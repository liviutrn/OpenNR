#include "QuadViewGeometry.hpp"
#include "QuadViewFramePacket.hpp"
#include "QuadViewDelivery.hpp"
#include "QuadViewProducer.hpp"
#include <array>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <iostream>

static bool near(double a, double b) { return std::abs(a - b) < 1e-6; }

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

    // Off-axis perspective with nonzero x/y translation terms. Cropping both
    // rows must preserve the full w row, depth row, and the requested UV map.
    std::array<std::array<double, 4>, 4> projection{{
        {{1.7, 0.0, 0.0, 0.0}},
        {{0.0, 2.1, 0.0, 0.0}},
        {{0.19, -0.11, 1.0, 1.0}},
        {{0.0, 0.0, -0.1, 0.0}},
    }};
    const auto original = projection;
    apply_focus_crop(projection, layout->focus_crop);
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
    for (const auto uv : {std::array<double,2>{layout->focus_crop.u0, layout->focus_crop.v0},
                          std::array<double,2>{layout->focus_crop.u1, layout->focus_crop.v1},
                          std::array<double,2>{.41, .63}}) {
        // Project an off-axis point through the complete matrix, then verify
        // the crop applies the exact affine map to its existing clip position.
        const auto full = project(original, uv[0] * 2.0 - 1.0, 1.0 - uv[1] * 2.0, -1.0);
        const auto cropped = project(projection, uv[0] * 2.0 - 1.0, 1.0 - uv[1] * 2.0, -1.0);
        const auto expected_x = (full[0] + 1.0 - layout->focus_crop.u0 - layout->focus_crop.u1) /
            (layout->focus_crop.u1 - layout->focus_crop.u0);
        const auto expected_y = (full[1] + layout->focus_crop.v0 + layout->focus_crop.v1 - 1.0) /
            (layout->focus_crop.v1 - layout->focus_crop.v0);
        assert(near(cropped[0], expected_x));
        assert(near(cropped[1], expected_y));
    }

    Producer producer;
    const Key key{7, 12};
    const Key abandoned{7, 11};
    assert(producer.begin(abandoned, 90, 0x100, 0x200, *layout));
    assert(producer.begin(key, 91, 0x100, 0x200, *layout));
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

    struct SourceToken { uint64_t serial{}, pose_frame_token{}; };
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

    // A staged GT observation must precede source registration, which is
    // itself in the outer renderer hook. The old Build 9 ordering attempted
    // bind_engine_frame before any source existed and always failed closed.
    {
        Delivery<SourceToken> staged;
        const std::array<uintptr_t,4> ids{0x11,0x22,0x33,0x44};
        assert(!staged.observe_gt_frame(12,0x100,0x200,0x300,ids,0xffffffffu));
        assert(staged.observe_gt_frame(12,0x100,0x200,0x300,ids,433));
        assert(!staged.take_observed_gt_frame(12,0x100,0x200,0x300,{0x11,0x22,0x33,0x55}));
        const auto assigned = staged.take_observed_gt_frame(12,0x100,0x200,0x300,ids);
        assert(assigned && *assigned == 433);
        assert(!staged.take_observed_gt_frame(12,0x100,0x200,0x300,ids));
        const auto packet=std::make_shared<const SourceToken>(SourceToken{56,3});
        const Delivery<SourceToken>::Source src{packet,12,56,0xffffffffu,3,0x100,0x200,0x300,ids};
        assert(staged.family(src));
        const auto bound=staged.bind_engine_frame(12,56,0x100,0x200,0x300,ids,*assigned);
        assert(bound && bound->engine_frame_bound && bound->engine_frame==433);
        assert(staged.render(12,433,0x170,0x200,0x300));
        // Reused family storage must not inherit the previous consumed ticket.
        assert(!staged.take_observed_gt_frame(12,0x100,0x200,0x300,ids));
        assert(staged.observe_gt_frame(12,0x100,0x200,0x300,ids,434));
        assert(staged.observe_gt_frame(12,0x100,0x200,0x300,{0x11,0x22,0x33,0x66},435));
        assert(!staged.take_observed_gt_frame(12,0x100,0x200,0x300,ids));
        assert(staged.take_observed_gt_frame(12,0x100,0x200,0x300,{0x11,0x22,0x33,0x66}) == 435);
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
