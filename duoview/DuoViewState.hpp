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
    // Current->previous *crop-local* source-pixel motion from ROI alone.
    // This does NOT establish what UE velocity/TSR actually consumes.
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
};

template<typename Matrix>
void apply_frame_projection(Matrix& matrix, const ViewFrame& frame, unsigned view) {
    for (int col=0;col<4;++col) for (int row=0;row<4;++row)
        matrix[col][row]=frame.projection[col*4+row];
    if (view==frame.config.settings.fovea_view) apply_foveal_crop(matrix,frame.config.layout);
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
        const auto center=stability.update(key,w,h,s,gaze,now_ms);
        const auto frozen = config_.for_frame(key, w, h, center);
        if (!frozen) return {};
        stability_=stability; last_begin_=key;
        slot = ViewFrame{*frozen, projection};
        slot->gaze_valid = s.eye_tracked && gaze.has_value();
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
                (static_cast<double>(now.u0)-old.u0)/now.crop_width*now.fovea.width;
            result.expected_crop_motion_px_y=
                (static_cast<double>(now.v0)-old.v0)/now.crop_height*now.fovea.height;
            result.moving_fovea=std::abs(result.expected_crop_motion_px_x)>.1 ||
                                  std::abs(result.expected_crop_motion_px_y)>.1;
        }
        last_audit_=result;
        last_completed_=slot; // diagnostic only; not proof of successful XR copy
        ViewFrame packet=*slot;
        return packet;
    }
    // Compositor was recorded and accepted by XR copy. This is not a
    // GPU-fence proof and MUST NOT be used as Unreal's prev-matrix source.
    bool accept_composite(FrameKey key) {
        std::scoped_lock lock{mutex_};
        auto& slot=frames_[key.frame % frames_.size()];
        if (!slot || slot->config.key!=key || !slot->consumed || slot->invalid) return false;
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
