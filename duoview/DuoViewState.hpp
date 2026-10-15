#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewCropStability.hpp"
#include "DuoViewCropMotion.hpp"
#include <array>
#include <functional>

namespace uevr::duoview {
struct CameraPose {
    std::array<double, 3> rotation{}, position{};
    bool operator==(const CameraPose&) const = default;
};
struct ViewTransform {
    std::array<double, 3> origin{};
    std::array<double, 16> rotation{}; // Physical UE FMatrix bytes.
    bool valid{};
};
inline bool same_view_transform(const ViewTransform& left, const ViewTransform& right) {
    if (!left.valid || !right.valid) return false;
    for (size_t i=0; i<left.origin.size(); ++i)
        if (std::abs(left.origin[i]-right.origin[i])>1.0e-9) return false;
    for (size_t i=0; i<left.rotation.size(); ++i)
        if (std::abs(left.rotation[i]-right.rotation[i])>1.0e-9) return false;
    return true;
}
struct TemporalAudit {
    FrameKey key{};
    bool enabled{}, previous_frame{}, same_pose{}, distinct_view_states{};
    bool stable_view_states{}, stable_projection_history{}, history_gap{};
    bool history_gate_pass{}, moving_fovea{};
    std::array<bool, 2> temporal_override_attempted{}, temporal_override_applied{};
    // Expected current->previous crop contribution for a static world point.
    // Unreal's per-view previous projection must supply this in its own vectors.
    double expected_crop_motion_px_x{}, expected_crop_motion_px_y{};
    std::array<uintptr_t,2> current_states{}, previous_states{};
};
struct ViewFrame {
    FrameConfig config;
    std::array<float, 16> projection{};
    CameraPose camera{};
    bool camera_valid{}, main_family{}, consumed{}, composition_ready{}, gaze_valid{}, invalid{};
    std::array<bool, 2> rectangles{}, projections{}, cameras{};
    std::array<uintptr_t,2> scene_states{};
    std::array<ViewTransform,2> view_transforms{};
    std::array<bool,2> temporal_override_attempted{}, temporal_override_applied{};
    bool history_gate_pass{};
    bool shading_applied{};
};

struct TemporalContract {
    ViewFrame current{};
    ViewFrame previous{};
    unsigned view{};
};

template<typename Matrix>
void apply_frame_projection(Matrix& matrix, const ViewFrame& frame, unsigned view) {
    for (int col=0;col<4;++col) for (int row=0;row<4;++row)
        matrix[col][row]=frame.projection[col*4+row];
    if (view==frame.config.settings.fovea_view)
        apply_foveal_crop(matrix,frame.config.layout);
}
class State {
public:
    bool configure(Settings settings) { std::scoped_lock lock{mutex_}; return config_.set_settings(settings); }
    Settings settings() const { return config_.current_settings(); }
    std::optional<ViewFrame> begin(FrameKey key, uint32_t w, uint32_t h,
        const std::array<float, 16>& projection, const std::function<GazeSample()>& read_gaze,
        uint64_t now_ms=0) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (slot && slot->config.key == key) return slot;
        if (key.generation<last_begin_.generation ||
            (key.generation==last_begin_.generation && key.frame<=last_begin_.frame)) return {};
        for (float x:projection) if (!std::isfinite(x)) return {};
        const auto s = config_.current_settings();
        const auto gaze = s.eye_tracked ? read_gaze() : GazeSample{UV{}};
        auto stability=stability_;
        const auto center=stability.update(key,w,h,s,gaze,now_ms);
        const auto frozen = config_.for_frame(key, w, h, center);
        if (!frozen) return {};
        stability_=stability; last_begin_=key;
        slot = ViewFrame{*frozen, projection};
        slot->gaze_valid = s.eye_tracked && gaze.uv.has_value() && !gaze.invalidated;
        return slot;
    }
    std::optional<ViewFrame> snapshot(FrameKey key) const {
        std::scoped_lock lock{mutex_};
        const auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key) return {};
        return slot;
    }
    bool rectangle(FrameKey key, unsigned view) { return observe(key, view, 0); }
    bool projection(FrameKey key, unsigned view) { return observe(key, view, 1); }
    bool scene(FrameKey key, unsigned view, uintptr_t state, bool shading_applied=false) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || view>1 || slot->invalid || slot->consumed) return false;
        slot->scene_states[view]=state;
        if (view==1) slot->shading_applied=shading_applied;
        return true;
    }
    bool view_transform(FrameKey key, unsigned view,
                        const std::array<double, 3>& origin,
                        const std::array<double, 16>& rotation) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || view>1 || slot->invalid || slot->consumed) return false;
        for (const double value : origin) if (!std::isfinite(value)) return false;
        for (const double value : rotation) if (!std::isfinite(value)) return false;
        slot->view_transforms[view] = ViewTransform{origin,rotation,true};
        return true;
    }
    std::optional<TemporalContract> temporal_contract(FrameKey key, unsigned view) const {
        std::scoped_lock lock{mutex_};
        if (view>1) return {};
        const auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || slot->invalid || slot->consumed ||
            !slot->view_transforms[view].valid || !slot->scene_states[view] ||
            !slot->projections[view] || !last_completed_ ||
            !last_completed_->consumed ||
            last_completed_->config.key.generation!=key.generation ||
            last_completed_->config.key.frame+1!=key.frame ||
            !last_completed_->view_transforms[view].valid ||
            !last_completed_->scene_states[view] ||
            slot->scene_states[view]!=last_completed_->scene_states[view] ||
            !last_completed_->projections[view]) return {};
        const auto& old_layout=last_completed_->config.layout;
        const auto& new_layout=slot->config.layout;
        const bool stable_layout=
            last_completed_->config.settings.fovea_view==slot->config.settings.fovea_view &&
            old_layout.atlas_width==new_layout.atlas_width &&
            old_layout.atlas_height==new_layout.atlas_height &&
            old_layout.fovea.width==new_layout.fovea.width &&
            old_layout.fovea.height==new_layout.fovea.height &&
            old_layout.periphery.width==new_layout.periphery.width &&
            old_layout.periphery.height==new_layout.periphery.height &&
            old_layout.crop_width==new_layout.crop_width &&
            old_layout.crop_height==new_layout.crop_height;
        if (!stable_layout) return {};
        return TemporalContract{*slot,*last_completed_,view};
    }
    bool note_temporal_override(FrameKey key, unsigned view, bool applied) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || view>1 || slot->invalid || slot->consumed) return false;
        // A UE frame may construct more than one transient wrapper for a
        // source view. Never let a later duplicate constructor downgrade a
        // successful write for the real view that will be rendered.
        if (slot->temporal_override_attempted[view])
            return slot->temporal_override_applied[view];
        slot->temporal_override_attempted[view]=true;
        slot->temporal_override_applied[view]=applied;
        return true;
    }
    bool can_independent_shading(FrameKey key, uintptr_t secondary_state) const {
        std::scoped_lock lock{mutex_};
        const auto& slot=frames_[key.frame%frames_.size()];
        return slot && slot->config.key==key && !slot->invalid && !slot->consumed &&
            slot->config.settings.independent_shading && slot->camera_valid &&
            slot->rectangles[0] && slot->rectangles[1] && slot->projections[0] && slot->projections[1] &&
            slot->scene_states[0] && secondary_state && slot->scene_states[0]!=secondary_state;
    }
    std::optional<CameraPose> camera(FrameKey key, unsigned view) const {
        std::scoped_lock lock{mutex_};
        const auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid || !slot->camera_valid) return {};
        return slot->camera;
    }
    bool camera(FrameKey key, unsigned view, const CameraPose& pose) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid) return false;
        for (auto x : pose.rotation) if (!std::isfinite(x)) return false;
        for (auto x : pose.position) if (!std::isfinite(x)) return false;
        if (!slot->camera_valid) {
            if(view!=0) return false;
            slot->camera = pose; slot->camera_valid = true;
        } else {
            if(slot->camera!=pose) { slot->invalid=true; return false; }
        }
        slot->cameras[view] = true;
        return true;
    }
    bool family(FrameKey key, bool main, unsigned count) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || !main || count != 2) return false;
        slot->main_family = true;
        return true;
    }
    std::optional<ViewFrame> consume(FrameKey key) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || slot->consumed || slot->invalid || !slot->main_family ||
            !slot->camera_valid || !slot->rectangles[0] || !slot->rectangles[1] ||
            !slot->projections[0] || !slot->projections[1] || !slot->cameras[0] || !slot->cameras[1]) return {};
        slot->consumed = true;
        TemporalAudit result{};
        result.key=key;
        result.enabled=slot->config.settings.temporal_audit;
        result.current_states=slot->scene_states;
        result.temporal_override_attempted=slot->temporal_override_attempted;
        result.temporal_override_applied=slot->temporal_override_applied;
        result.distinct_view_states=slot->scene_states[0] && slot->scene_states[1] &&
                                    slot->scene_states[0]!=slot->scene_states[1];
        const bool has_previous_generation=last_completed_ &&
            last_completed_->config.key.generation==key.generation;
        if (has_previous_generation) {
            result.previous_frame=last_completed_->config.key.frame+1==key.frame;
            result.history_gap=!result.previous_frame;
            result.previous_states=last_completed_->scene_states;
            result.same_pose=last_completed_->camera==slot->camera;
            result.stable_view_states=result.distinct_view_states &&
                result.current_states==result.previous_states;
            const auto& old_layout=last_completed_->config.layout;
            const auto& new_layout=slot->config.layout;
            result.stable_projection_history=
                last_completed_->config.settings.fovea_view==slot->config.settings.fovea_view &&
                old_layout.atlas_width==new_layout.atlas_width &&
                old_layout.atlas_height==new_layout.atlas_height &&
                old_layout.fovea.width==new_layout.fovea.width &&
                old_layout.fovea.height==new_layout.fovea.height &&
                old_layout.crop_width==new_layout.crop_width &&
                old_layout.crop_height==new_layout.crop_height;
            if (result.previous_frame) if (const auto motion=expected_crop_motion(last_completed_->config,slot->config)) {
                result.expected_crop_motion_px_x=motion->current_to_previous_pixels_x;
                result.expected_crop_motion_px_y=motion->current_to_previous_pixels_y;
            }
            result.moving_fovea=std::abs(result.expected_crop_motion_px_x)>.1 ||
                                  std::abs(result.expected_crop_motion_px_y)>.1;
        }
        const bool same_current_source_transform=same_view_transform(
            slot->view_transforms[0],slot->view_transforms[1]);
        const bool temporal_bridge_ready=!slot->config.settings.eye_tracked ||
            !result.previous_frame ||
            (slot->temporal_override_attempted[0] && slot->temporal_override_applied[0] &&
             slot->temporal_override_attempted[1] && slot->temporal_override_applied[1]);
        result.history_gate_pass=result.distinct_view_states && !result.history_gap &&
            (!result.previous_frame ||
                (result.stable_view_states && result.stable_projection_history)) &&
            (!slot->config.settings.eye_tracked || same_current_source_transform) &&
            temporal_bridge_ready;
        last_audit_=result;
        slot->history_gate_pass=result.history_gate_pass;
        last_completed_=slot; // continuity baseline; not proof of successful XR copy
        if (slot->config.settings.eye_tracked && !result.history_gate_pass) return {};
        slot->composition_ready=true;
        ViewFrame packet=*slot;
        return packet;
    }
    // Compositor was recorded and accepted by XR copy. This is not a
    // GPU-fence proof and MUST NOT be used as Unreal's prev-matrix source.
    bool accept_composite(FrameKey key) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key!=key || !slot->consumed || !slot->composition_ready || slot->invalid) return false;
        if (last_accepted_ &&
            (last_accepted_->config.key.generation > key.generation ||
             (last_accepted_->config.key.generation == key.generation &&
              last_accepted_->config.key.frame >= key.frame)))
            return false; // never undo a more recent accepted XR copy
        last_accepted_=slot;
        return true;
    }
    std::optional<TemporalAudit> temporal_audit() const {
        std::scoped_lock lock{mutex_}; return last_audit_;
    }
    void retire() {
        std::scoped_lock lock{mutex_};
        frames_ = {}; config_.retire(); stability_.reset(); last_begin_={};
        last_completed_.reset(); last_audit_.reset(); last_accepted_.reset();
    }
private:
    bool observe(FrameKey key, unsigned view, int kind) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key || view > 1 || slot->invalid || slot->consumed) return false;
        (kind == 0 ? slot->rectangles : slot->projections)[view] = true;
        return true;
    }
    mutable std::mutex mutex_;
    ConfigLatch config_;
    CropStability stability_;
    FrameKey last_begin_{};
    std::array<std::optional<ViewFrame>, 16> frames_{};
    std::optional<ViewFrame> last_completed_{};
    std::optional<ViewFrame> last_accepted_{}; // XR copy accepted, not UE history consumer
    std::optional<TemporalAudit> last_audit_{};
};
}
