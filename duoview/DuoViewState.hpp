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
struct ViewFrame {
    FrameConfig config;
    std::array<float, 16> projection{};
    CameraPose camera{};
    std::optional<uint32_t> mono_source_frame{};
    bool camera_valid{}, main_family{}, consumed{}, gaze_valid{}, invalid{};
    std::array<bool, 2> rectangles{}, projections{}, cameras{};
    std::array<uintptr_t,2> scene_states{};
    bool shading_applied{};
};

struct NativeFrameBinding {
    FrameKey key{};
    uint32_t mono_source_frame{};
};

// Bind the Native packet to the exact OpenXR pose/projection frame observed at
// source creation. The Mono token is carried explicitly; it is not derived
// from the later DuoView producer key.
inline std::optional<NativeFrameBinding> native_frame_binding(const ViewFrame& frame) {
    if (!frame.config.key.generation || !frame.config.key.frame || !frame.mono_source_frame ||
        frame.invalid || frame.consumed || !frame.main_family || !frame.camera_valid) return {};
    for (size_t i = 0; i != 2; ++i) {
        if (!frame.rectangles[i] || !frame.projections[i] || !frame.cameras[i]) return {};
    }
    return NativeFrameBinding{frame.config.key, *frame.mono_source_frame};
}

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
        uint64_t now_ms=0, std::optional<uint32_t> mono_source_frame={}) {
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
        slot->mono_source_frame = mono_source_frame;
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

