#pragma once
#include "DuoViewConfig.hpp"
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
    bool camera_valid{}, main_family{}, consumed{}, gaze_valid{}, invalid{};
    std::array<bool, 2> rectangles{}, projections{}, cameras{};
};
class State {
public:
    bool configure(Settings settings) { std::scoped_lock lock{mutex_}; return config_.set_settings(settings); }
    Settings settings() const { return config_.current_settings(); }
    std::optional<ViewFrame> begin(FrameKey key, uint32_t w, uint32_t h,
        const std::array<float, 16>& projection, const std::function<std::optional<UV>()>& read_gaze) {
        std::scoped_lock lock{mutex_};
        auto& slot = frames_[key.frame % frames_.size()];
        if (slot && slot->config.key == key) return slot;
        const auto s = config_.current_settings();
        const auto gaze = s.eye_tracked ? read_gaze() : std::optional<UV>{UV{}};
        const auto frozen = config_.for_frame(key, w, h, gaze.value_or(UV{}));
        if (!frozen) return {};
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
        frames_ = {}; config_.retire();
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
    std::array<std::optional<ViewFrame>, 16> frames_{};
};
}
