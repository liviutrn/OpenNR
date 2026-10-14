#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewCropStability.hpp"
#include <array>
#include <functional>

namespace uevr::duoview {
struct CameraPose {
    std::array<double, 3> rotation{}, position{};
    bool operator==(const CameraPose&) const = default;
};
struct TemporalAudit {
    FrameKey key{};
    bool previous_frame{}, same_pose{}, distinct_view_states{}, stable_view_states{}, moving_fovea{};
    double expected_crop_motion_px_x{}, expected_crop_motion_px_y{};
    std::array<uintptr_t,2> current_states{}, previous_states{};
};
struct ViewFrame {
    FrameConfig config;
    std::array<float, 16> projection{};
    CameraPose camera{};
    bool camera_valid{}, main_family{}, consumed{}, gaze_valid{}, invalid{};
    std::array<bool, 2> rectangles{}, projections{}, cameras{};
    std::array<uintptr_t,2> scene_states{};
    bool shading_applied{};
    bool foveal_rotation_applied{};
};

template<typename Matrix>
void apply_frame_projection(Matrix& matrix, const ViewFrame& frame, unsigned view) {
    for (int col=0;col<4;++col) for (int row=0;row<4;++row)
        matrix[col][row]=frame.projection[col*4+row];
    if (view==frame.config.settings.fovea_view) {
        if (frame.config.foveal_camera.enabled) {
            matrix[0][0]=frame.config.foveal_camera.scale_x;
            matrix[1][1]=frame.config.foveal_camera.scale_y;
            matrix[2][0]=matrix[2][1]=0;
        } else apply_foveal_crop(matrix,frame.config.layout);
    }
}
class State {
public:
    bool configure(Settings settings) { std::scoped_lock lock{mutex_}; return config_.set_settings(settings); }
    Settings settings() const { return config_.current_settings(); }
    std::optional<ViewFrame> begin(FrameKey key, uint32_t w, uint32_t h,
        const std::array<float, 16>& projection, const std::function<std::optional<UV>()>& read_gaze,
        uint64_t now_ms=0) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (slot && slot->config.key == key) return slot;
        if (key.generation<last_begin_.generation ||
            (key.generation==last_begin_.generation && key.frame<=last_begin_.frame)) return {};
        for (float x:projection) if (!std::isfinite(x)) return {};
        const auto s = config_.current_settings();
        const auto gaze = s.eye_tracked ? read_gaze() : std::optional<UV>{UV{}};
        auto stability=stability_;
        const auto center=stability.update(key,w,h,s,gaze,now_ms,input_scale_x_,input_scale_y_);
        const auto frozen = config_.for_frame(key, w, h, center);
        if (!frozen) return {};
        stability_=stability; last_begin_=key;
        slot = ViewFrame{*frozen, projection};
        if (s.gaze_camera && s.eye_tracked) {
            const auto camera=make_foveal_camera(projection,slot->config.layout);
            if (!camera) { slot.reset(); return {}; }
            slot->config.foveal_camera=*camera;
        }
        slot->gaze_valid = s.eye_tracked && gaze.has_value();
        const bool changed=!last_produced_ || last_produced_->config.key.generation!=key.generation ||
            last_produced_->config.key.frame+1!=key.frame ||
            last_produced_->config.layout.u0!=slot->config.layout.u0 ||
            last_produced_->config.layout.v0!=slot->config.layout.v0 ||
            last_produced_->config.layout.crop_width!=slot->config.layout.crop_width ||
            last_produced_->config.layout.crop_height!=slot->config.layout.crop_height ||
            last_produced_->config.settings.eye_tracked!=s.eye_tracked ||
            last_produced_->config.settings.fovea_view!=s.fovea_view ||
            last_produced_->config.foveal_camera.scale_x!=slot->config.foveal_camera.scale_x ||
            last_produced_->config.foveal_camera.scale_y!=slot->config.foveal_camera.scale_y;
        slot->config.foveal_history_reset=s.dlss_history_protection &&
            (s.eye_tracked || (last_produced_ && last_produced_->config.settings.eye_tracked)) &&
            (changed || previous_crop_changed_);
        previous_crop_changed_=changed && s.eye_tracked;
        last_produced_=slot;
        return slot;
    }
    void note_dlss_input_scale(float x,float y) {
        if (!std::isfinite(x) || !std::isfinite(y) || x<.1f || x>1.f || y<.1f || y>1.f) return;
        std::scoped_lock lock{mutex_}; input_scale_x_=x; input_scale_y_=y;
    }
    std::optional<ViewFrame> snapshot(FrameKey key) const {
        std::scoped_lock lock{mutex_};
        const auto& slot = frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key != key) return {};
        return slot;
    }
    bool rectangle(FrameKey key, unsigned view) { return observe(key, view, 0); }
    bool projection(FrameKey key, unsigned view) { return observe(key, view, 1); }
    bool foveal_rotation(FrameKey key) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || slot->invalid || slot->consumed) return false;
        slot->foveal_rotation_applied=true;
        return true;
    }
    bool scene(FrameKey key, unsigned view, uintptr_t state, bool shading_applied=false) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame%frames_.size()];
        if (!slot || slot->config.key!=key || view>1 || slot->invalid || slot->consumed) return false;
        slot->scene_states[view]=state;
        if (view==1) slot->shading_applied=shading_applied;
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
        if (!slot->camera_valid) { slot->camera = pose; slot->camera_valid = true; }
        else if (slot->camera != pose) { slot->invalid = true; return false; }
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
        if (slot->config.foveal_camera.enabled && (!slot->foveal_rotation_applied ||
            !slot->scene_states[0] || !slot->scene_states[1] ||
            slot->scene_states[0]==slot->scene_states[1])) return {};
        slot->consumed = true;
        TemporalAudit result{};
        result.key=key;
        result.current_states=slot->scene_states;
        result.distinct_view_states=slot->scene_states[0] && slot->scene_states[1] &&
                                    slot->scene_states[0]!=slot->scene_states[1];
        if (last_completed_ && last_completed_->config.key.generation==key.generation &&
            last_completed_->config.key.frame+1==key.frame) {
            result.previous_frame=true;
            result.previous_states=last_completed_->scene_states;
            result.same_pose=last_completed_->camera==slot->camera;
            result.stable_view_states=result.distinct_view_states &&
                result.current_states==result.previous_states;
            const auto& old=last_completed_->config.layout;
            const auto& now=slot->config.layout;
            result.expected_crop_motion_px_x=
                (static_cast<double>(old.u0)-now.u0)/now.crop_width*now.fovea.width;
            result.expected_crop_motion_px_y=
                (static_cast<double>(old.v0)-now.v0)/now.crop_height*now.fovea.height;
            result.moving_fovea=std::abs(result.expected_crop_motion_px_x)>.1 ||
                                  std::abs(result.expected_crop_motion_px_y)>.1;
        }
        last_audit_=result;
        last_completed_=slot;
        return slot;
    }
    std::optional<TemporalAudit> temporal_audit() const {
        std::scoped_lock lock{mutex_}; return last_audit_;
    }
    void retire() {
        std::scoped_lock lock{mutex_};
        frames_ = {}; config_.retire(); stability_.reset(); last_begin_={};
        last_completed_.reset(); last_audit_.reset();
        last_produced_.reset(); previous_crop_changed_=false; input_scale_x_=input_scale_y_=1.f;
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
    std::optional<ViewFrame> last_produced_{};
    bool previous_crop_changed_{};
    float input_scale_x_{1.f},input_scale_y_{1.f};
    std::optional<TemporalAudit> last_audit_{};
};
}
