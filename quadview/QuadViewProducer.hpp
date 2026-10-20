#pragma once

#include "QuadViewGeometry.hpp"
#include "QuadViewSettings.hpp"
#include <array>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <unordered_map>

namespace uevr::quadview {

struct Key {
    uint64_t generation{}, draw_serial{};
    friend bool operator==(const Key&, const Key&) = default;
};

struct KeyHash {
    size_t operator()(Key key) const noexcept {
        const auto mixed = key.generation ^ (key.draw_serial + 0x9e3779b97f4a7c15ull +
            (key.generation << 6) + (key.generation >> 2));
        return static_cast<size_t>(mixed);
    }
};

struct ViewRecord {
    uintptr_t view{}, state{};
    Rect rect{};
    // Exact matrix fingerprint captured from FSceneViewInitOptions.
    uint64_t projection_hash{};
    bool valid{};
};

struct CameraPose {
    std::array<double, 3> rotation{};
    std::array<double, 3> position{};
    bool valid{};
};

struct GazeEvidence {
    uint64_t sample_tick{};
    uint64_t fresh{},reused{},invalid{},expired{},unavailable{};
    uint32_t age_ms{};
    bool sampled{},ray_valid{},reader_available{},reader_active{};
};

struct Snapshot {
    Key key{};
    uint64_t engine_frame{};
    uintptr_t family{}, scene{}, target{};
    Layout layout{};
    Settings settings{};
    uint64_t settings_revision{};
    GazeEvidence gaze{};
    std::array<ViewRecord, 4> views{};
    std::array<uint64_t, 4> expected_projection_hashes{};
    std::array<std::array<double, 16>, 4> projections{};
    std::array<CameraPose, 2> context_cameras{};
    uint8_t constructor_mask{};
    uint8_t expected_projection_mask{};
    uint8_t projection_matrix_mask{};
    uint8_t camera_mask{};
    bool family_valid{};
    uint64_t hook_rect_calls{}, hook_projection_calls{};

    bool histories_complete() const {
        if (!family_valid || constructor_mask != 0x0f || expected_projection_mask != 0x0f ||
            projection_matrix_mask != 0x0f || camera_mask != 0x03) return false;
        for (uint32_t i = 0; i != 4; ++i) {
            if (!views[i].valid || views[i].state == 0 || views[i].projection_hash == 0 ||
                views[i].projection_hash != expected_projection_hashes[i]) return false;
            bool nonzero = false;
            for (double value : projections[i]) {
                if (!std::isfinite(value)) return false;
                nonzero = nonzero || std::abs(value) > 1.0e-12;
            }
            if (!nonzero) return false;
            for (uint32_t j = i + 1; j != 4; ++j) {
                if (views[i].state == views[j].state) return false;
            }
        }
        return true;
    }

    bool camera_complete() const {
        if (camera_mask != 0x03) return false;
        for (const auto& camera : context_cameras) {
            if (!camera.valid) return false;
            for (double v : camera.rotation) if (!std::isfinite(v)) return false;
            for (double v : camera.position) if (!std::isfinite(v)) return false;
        }
        return true;
    }
};

// A per-draw producer ledger. Hook calls and four distinct same-family states
// are captured independently of compositor command-record diagnostics.
class Producer {
public:
    bool begin(Key key, uint64_t engine_frame, uintptr_t target, uintptr_t scene, Layout layout,
               Settings settings = {}, uint64_t settings_revision = 1, GazeEvidence gaze = {}) {
        if (key.generation == 0 || key.draw_serial == 0 ||
            !layout.eye_width || !layout.eye_height || layout.atlas_width != layout.eye_width * 2) return false;
        std::scoped_lock lock{mutex_};
        // View constructors run synchronously with viewport drawing. A failed,
        // incomplete prior draw is safe to discard when the next draw starts.
        // Completed records remain until their render-slot owner retires them.
        for (auto it = pending_.begin(); it != pending_.end();) {
            if (it->first.generation != key.generation || it->first.draw_serial != key.draw_serial) {
                it = pending_.erase(it);
            } else {
                ++it;
            }
        }
        // A Delivery source owns its immutable Snapshot independently. Keep
        // the producer lookup bounded even if a runtime never accepts a copy.
        // This does not invalidate any queued/executed packet's shared owner.
        for (auto it = completed_.begin(); it != completed_.end();) {
            if (!(it->first == key)) {
                compositor_records_.erase(it->first);
                it = completed_.erase(it);
            } else {
                ++it;
            }
        }
        if (pending_.contains(key) || completed_.contains(key) ||
            pending_.size() + completed_.size() >= max_live_packets) return false;
        Snapshot snapshot{};
        snapshot.key = key;
        snapshot.engine_frame = engine_frame;
        snapshot.target = target;
        snapshot.scene = scene;
        snapshot.layout = layout;
        snapshot.settings = settings;
        snapshot.settings_revision = settings_revision;
        snapshot.gaze = gaze;
        pending_.emplace(key, std::move(snapshot));
        return true;
    }

    bool rectangle_call(Key key, int32_t index) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr) return false;
        if (!valid_view_index(index)) return false;
        ++snapshot->hook_rect_calls;
        return true;
    }

    bool projection_call(Key key, int32_t index, uint64_t expected_projection_hash,
                         const std::array<double, 16>& projection) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || !valid_view_index(index) || expected_projection_hash == 0) return false;
        bool nonzero = false;
        for (double value : projection) {
            if (!std::isfinite(value)) return false;
            nonzero = nonzero || std::abs(value) > 1.0e-12;
        }
        if (!nonzero) return false;
        ++snapshot->hook_projection_calls;
        snapshot->expected_projection_hashes[static_cast<size_t>(index)] = expected_projection_hash;
        snapshot->expected_projection_mask |= static_cast<uint8_t>(1u << index);
        snapshot->projections[static_cast<size_t>(index)] = projection;
        snapshot->projection_matrix_mask |= static_cast<uint8_t>(1u << index);
        return true;
    }

    std::optional<std::array<double, 16>> projection_matrix(Key key, uint32_t index) const {
        std::scoped_lock lock{mutex_};
        const auto found = pending_.find(key);
        if (found == pending_.end() || index >= 4 ||
            (found->second.expected_projection_mask & static_cast<uint8_t>(1u << index)) == 0) return {};
        return found->second.projections[index];
    }

    // Only the two context callbacks own view-offset side effects. Focus
    // indices copy these completed, post-mod cameras and must not call the
    // full offset path a second time.
    bool camera(Key key, uint32_t view_index, CameraPose pose) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || view_index > 1 || !pose.valid) return false;
        for (double v : pose.rotation) if (!std::isfinite(v)) return false;
        for (double v : pose.position) if (!std::isfinite(v)) return false;
        snapshot->context_cameras[view_index] = pose;
        snapshot->camera_mask |= static_cast<uint8_t>(1u << view_index);
        return true;
    }

    std::optional<CameraPose> context_camera(Key key, uint32_t view_index) const {
        std::scoped_lock lock{mutex_};
        const auto found = pending_.find(key);
        if (found == pending_.end() || view_index > 1 ||
            (found->second.camera_mask & static_cast<uint8_t>(1u << view_index)) == 0) return {};
        return found->second.context_cameras[view_index];
    }

    bool constructed(Key key, uintptr_t family, uintptr_t scene, uintptr_t target,
                     uintptr_t view, uintptr_t state, Rect rect, uint64_t projection_hash) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || !family || !scene || !target || !view || !state || !projection_hash ||
            (snapshot->scene != 0 && scene != snapshot->scene) ||
            (snapshot->target != 0 && target != snapshot->target)) return false;
        const auto index = view_index_for_rect(snapshot->layout, rect);
        if (!index) return false;
        if ((snapshot->expected_projection_mask & static_cast<uint8_t>(1u << *index)) == 0 ||
            snapshot->expected_projection_hashes[*index] != projection_hash) return false;
        if (snapshot->family != 0 && snapshot->family != family) return false;
        if ((snapshot->constructor_mask & static_cast<uint8_t>(1u << *index)) != 0) return false;
        for (uint32_t i = 0; i != 4; ++i) {
            if (i == *index) continue;
            if (snapshot->views[i].state == state || snapshot->views[i].view == view) return false;
        }
        snapshot->family = family;
        snapshot->scene = scene;
        snapshot->target = target;
        snapshot->views[*index] = {view, state, rect, projection_hash, true};
        snapshot->constructor_mask |= static_cast<uint8_t>(1u << *index);
        return true;
    }

    bool main_family(Key key, uint64_t engine_frame, uintptr_t family, uintptr_t scene, uintptr_t target,
                     const std::array<uintptr_t, 4>& views) {
        std::scoped_lock lock{mutex_};
        auto* snapshot = find_pending(key);
        if (snapshot == nullptr || family == 0 || family != snapshot->family || scene != snapshot->scene || target != snapshot->target ||
            (snapshot->engine_frame != 0 && engine_frame != 0 && snapshot->engine_frame != engine_frame)) return false;
        std::array<bool, 4> matched{};
        for (const auto view : views) {
            if (!view) return false;
            bool found = false;
            for (uint32_t i = 0; i != 4; ++i) {
                if (snapshot->views[i].valid && snapshot->views[i].view == view && !matched[i]) {
                    matched[i] = true;
                    found = true;
                    break;
                }
            }
            if (!found) return false;
        }
        for (bool found : matched) if (!found) return false;
        snapshot->engine_frame = engine_frame;
        snapshot->family_valid = true;
        if (!snapshot->camera_complete() || !snapshot->histories_complete()) return false;
        completed_.emplace(key, std::make_shared<const Snapshot>(*snapshot));
        pending_.erase(key);
        return true;
    }

    // Records only the app-side compositor command submission. It does not
    // claim that the four scene views rasterized or that the GPU completed.
    bool note_compositor_record(Key key, uintptr_t source, uintptr_t command_list) {
        std::scoped_lock lock{mutex_};
        const auto frozen = completed_.find(key);
        if (frozen == completed_.end() || !source || !command_list) return false;
        auto& evidence = compositor_records_[key];
        ++evidence.submits;
        evidence.last_source_resource = source;
        evidence.last_command_list = command_list;
        return true;
    }

    std::optional<Snapshot> snapshot(Key key) const {
        std::scoped_lock lock{mutex_};
        if (const auto frozen = completed_.find(key); frozen != completed_.end()) return *frozen->second;
        if (const auto pending = pending_.find(key); pending != pending_.end()) return pending->second;
        return {};
    }

    std::shared_ptr<const Snapshot> frozen(Key key) const {
        std::scoped_lock lock{mutex_};
        const auto found = completed_.find(key);
        return found == completed_.end() ? nullptr : found->second;
    }

    bool retire(Key key) {
        std::scoped_lock lock{mutex_};
        compositor_records_.erase(key);
        const auto pending_removed = pending_.erase(key);
        const auto completed_removed = completed_.erase(key);
        return pending_removed != 0 || completed_removed != 0;
    }

    void retire_generation(uint64_t generation) {
        std::scoped_lock lock{mutex_};
        for (auto it = pending_.begin(); it != pending_.end();) {
            if (it->first.generation == generation) it = pending_.erase(it);
            else ++it;
        }
        for (auto it = completed_.begin(); it != completed_.end();) {
            if (it->first.generation == generation) {
                compositor_records_.erase(it->first);
                it = completed_.erase(it);
            } else {
                ++it;
            }
        }
    }

    void retire_all() {
        std::scoped_lock lock{mutex_};
        pending_.clear();
        completed_.clear();
        compositor_records_.clear();
    }

    struct CompositorEvidence { uint64_t submits{}; uintptr_t last_source_resource{}, last_command_list{}; };
    std::optional<CompositorEvidence> compositor_evidence(Key key) const {
        std::scoped_lock lock{mutex_};
        if (const auto found = compositor_records_.find(key); found != compositor_records_.end()) return found->second;
        return {};
    }

private:
    static constexpr size_t max_live_packets = 8;
    Snapshot* find_pending(Key key) {
        const auto found = pending_.find(key);
        return found == pending_.end() ? nullptr : &found->second;
    }
    static std::optional<uint32_t> view_index_for_rect(const Layout& layout, Rect rect) {
        for (uint32_t i = 0; i != 4; ++i) if (layout.views[i] == rect) return i;
        return {};
    }
    mutable std::mutex mutex_;
    std::unordered_map<Key, Snapshot, KeyHash> pending_;
    std::unordered_map<Key, std::shared_ptr<const Snapshot>, KeyHash> completed_;
    std::unordered_map<Key, CompositorEvidence, KeyHash> compositor_records_;
};

} // namespace uevr::quadview
