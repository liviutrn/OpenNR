#pragma once

#include "QuadViewProducer.hpp"
#include <array>
#include <cmath>
#include <memory>
#include <utility>

namespace uevr::quadview {

struct RuntimeEye {
    uint64_t frame_token{};
    std::array<float, 4> orientation{};
    std::array<float, 3> position{};
    std::array<float, 4> fov{};
    std::array<float, 16> projection{};
    bool valid{};
};

struct RhiExecutionEvidence {
    uint64_t engine_frame{};
    uintptr_t family{}, target{}, scene{}, command{};
    uint32_t thread{};
    bool family_observed{}, tail_hooked{}, command_executed{};

    bool valid_for(const Snapshot& snapshot) const {
        return family_observed && tail_hooked && command_executed &&
            engine_frame == snapshot.engine_frame && family == snapshot.family &&
            target == snapshot.target && scene == snapshot.scene && command != 0 && thread != 0;
    }
};

// Immutable source/pose ownership boundary consumed by the D3D12 submit path.
// source_owner is expected to retain the actual RHI resource wrapper (for
// example, an object containing a ComPtr<ID3D12Resource>) until command-slot
// fence retirement. The portable contract cannot claim GPU completion.
struct FramePacket {
    std::shared_ptr<const Snapshot> producer;
    std::shared_ptr<const void> source_owner;
    uintptr_t source_resource{};
    uint64_t runtime_frame{};
    RhiExecutionEvidence execution{};
    uint64_t serial{};
    std::array<RuntimeEye, 2> eyes{};

    bool valid() const {
        if (!producer || !producer->histories_complete() || !source_owner ||
            source_resource == 0 || serial == 0 || serial != producer->key.draw_serial ||
            !execution.valid_for(*producer)) return false;
        for (const auto& eye : eyes) {
            if (!eye.valid || eye.frame_token != runtime_frame) return false;
            double norm = 0.0;
            for (float v : eye.orientation) {
                if (!std::isfinite(v)) return false;
                norm += static_cast<double>(v) * v;
            }
            if (std::abs(norm - 1.0) > 0.01) return false;
            for (float v : eye.position) if (!std::isfinite(v)) return false;
            const auto& f = eye.fov;
            if (!(std::isfinite(f[0]) && std::isfinite(f[1]) &&
                  std::isfinite(f[2]) && std::isfinite(f[3]) &&
                  f[0] < -0.001f && f[1] > 0.001f &&
                  f[2] > 0.001f && f[3] < -0.001f)) return false;
            bool projection_nonzero = false;
            for (float v : eye.projection) {
                if (!std::isfinite(v)) return false;
                projection_nonzero = projection_nonzero || std::abs(v) > 1.0e-8f;
            }
            if (!projection_nonzero) return false;
        }
        return true;
    }
};

inline std::shared_ptr<const FramePacket> bind_frame_packet(
    std::shared_ptr<const Snapshot> producer,
    uintptr_t source_resource,
    std::shared_ptr<const void> source_owner,
    uint64_t runtime_frame,
    RhiExecutionEvidence execution,
    std::array<RuntimeEye, 2> eyes)
{
    const auto serial = producer ? producer->key.draw_serial : 0;
    auto packet = std::make_shared<FramePacket>(FramePacket{
        std::move(producer), std::move(source_owner), source_resource,
        runtime_frame, execution, serial, std::move(eyes)});
    if (!packet->valid()) return {};
    return packet;
}

} // namespace uevr::quadview
