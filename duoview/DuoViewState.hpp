#pragma once
#include "DuoViewConfig.hpp"
#include "DuoViewCropStability.hpp"
#include <array>
#include <functional>

namespace uevr::duoview {
// Four consecutive bad frame/compositor observations initiate a *real*
// GPU-retired mode-6 to mode-5 transaction on the main/game thread.
// Transient loss (including one frame during runtime resize) retries DuoView.
// Never produce Native Stereo mode ID0 as an automatic failure destination.
constexpr uint32_t mono_fallback_failure_threshold = 4u;
constexpr uint32_t mono_fallback_startup_grace_frames = 60u;
constexpr bool should_fallback_to_mono(uint32_t consecutive_failures, bool previously_presented=true) {
    return consecutive_failures >= (previously_presented
        ? mono_fallback_failure_threshold : mono_fallback_startup_grace_frames);
}
struct CameraPose {
    std::array<double, 3> rotation{}, position{};
    bool operator==(const CameraPose&) const = default;
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
        const auto gaze = s.eye_tracked ? read_gaze() : std::optional<UV>{UV{.5f, s.fixed_center_v}};
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
    // Independent of the old experimental primary-shading toggle.
    // Called DURING secondary view construction, before the second view has
    // necessarily published its rectangle or projection. Waiting for those
    // secondary observations would deadlock this source-stage Native Fix.
    // Require a coherent current PRIMARY snapshot, immutable frame geometry,
    // main-view camera, and distinct non-null source ViewStates. The caller
    // separately checks exact family/RT identity, secondary constructor pass,
    // and restores the temporary UE constructor inputs on every return.
    bool can_native_fix_secondary_source(FrameKey key, uintptr_t secondary_state) const {
        std::scoped_lock lock{mutex_};
        const auto& slot=frames_[key.frame % frames_.size()];
        return slot && slot->config.key==key && !slot->invalid && !slot->consumed &&
            slot->camera_valid && slot->cameras[0] &&
            slot->rectangles[0] && slot->projections[0] &&
            layout_valid(slot->config.layout) &&
            slot->scene_states[0] && secondary_state &&
            slot->scene_states[0]!=secondary_state;
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
        // An observed pair is not sufficient: independent current-frame UE
        // source states and the guarded Native Fix secondary-constructor
        // transaction are mandatory before we may present the periphery.
        // Otherwise the image could be fully populated but retain the known
        // incorrect Lumen/shadow history of the untreated secondary source.
        if (!slot || slot->config.key != key || slot->consumed || slot->invalid || !slot->main_family ||
            !slot->camera_valid || !slot->rectangles[0] || !slot->rectangles[1] ||
            !slot->projections[0] || !slot->projections[1] || !slot->cameras[0] || !slot->cameras[1] ||
            !slot->scene_states[0] || !slot->scene_states[1] ||
            slot->scene_states[0] == slot->scene_states[1] || !slot->shading_applied) return {};
        slot->consumed = true;
        return slot;
    }
    void retire() {
        std::scoped_lock lock{mutex_};
        frames_ = {}; config_.retire(); stability_.reset(); last_begin_={};
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
};
}
