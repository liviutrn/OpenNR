#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>

namespace uevr::quadview {

// Independent family -> render-thread -> RHI tail -> executed-owner ledger.
// It carries exactly one four-view family; it does not reuse DuoView's
// primary/secondary two-source pairing or Mono pose path.
template <class Packet, size_t Capacity = 16>
class Delivery {
public:
    struct Source {
        std::shared_ptr<const Packet> packet{};
        uint64_t generation{}, serial{};
        uint32_t engine_frame{}; // BeginRenderViewFamily-assigned frame after binding; pre-engine value is diagnostic only.
        uint64_t pose_frame_token{}; // Frozen OpenXR frame token carried by this source.
        uintptr_t family{}, target{}, scene{};
        // The GT BeginRenderViewFamily callback binds the pre-engine producer
        // registration to Unreal's current frame number while the original
        // FSceneViewFamily and its four FSceneView pointers are still present.
        // The RT callback may receive renderer-owned FViewInfo copies, so it
        // matches the bound frame/target/scene tuple rather than view addresses.
        std::array<uintptr_t, 4> view_ids{};
        bool engine_frame_bound{};
        explicit operator bool() const { return packet && generation && serial && family && target && scene; }
        bool same_owner(const Source& other) const {
            return packet == other.packet && generation == other.generation && serial == other.serial &&
                engine_frame == other.engine_frame && pose_frame_token == other.pose_frame_token && family == other.family &&
                target == other.target && scene == other.scene && view_ids == other.view_ids &&
                engine_frame_bound == other.engine_frame_bound;
        }
    };

    struct EngineTicket {
        uint64_t generation{}, serial{};
        uint32_t engine_frame{};
        uintptr_t family{}, target{}, scene{}, command{};
        bool render_seen{}, tail_hooked{};
        explicit operator bool() const {
            return generation && serial && engine_frame != 0xffffffffu && family && target && scene;
        }
        bool same_owner(const EngineTicket& other) const {
            return generation == other.generation && serial == other.serial &&
                engine_frame == other.engine_frame && family == other.family &&
                target == other.target && scene == other.scene;
        }
    };

    bool register_engine_family(EngineTicket ticket) {
        if (!ticket) return false;
        std::scoped_lock lock{mutex_};
        if (!advance(ticket.generation)) return false;
        for (const auto& slot : engine_slots_) {
            if (slot.ticket && slot.ticket.same_owner(ticket)) return true;
        }
        for (auto& slot : engine_slots_) {
            if (!slot.ticket) {
                slot.ticket = ticket;
                return true;
            }
        }
        engine_overflow_generation_ = ticket.generation;
        return false;
    }

    std::optional<EngineTicket> render_engine_family(
        uint64_t generation, uint32_t frame, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !target || !scene) return {};
        EngineSlot* match{};
        for (auto& slot : engine_slots_) {
            auto& ticket = slot.ticket;
            if (!ticket || ticket.generation != generation || ticket.engine_frame != frame ||
                ticket.target != target || ticket.scene != scene || ticket.render_seen) continue;
            if (match) return {};
            match = &slot;
        }
        if (!match) return {};
        match->ticket.render_seen = true;
        return match->ticket;
    }

    bool tail_hooked_engine_family(const EngineTicket& ticket, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find_engine(ticket);
        if (!slot || !slot->ticket.render_seen || slot->ticket.tail_hooked || !command) return false;
        slot->ticket.command = command;
        slot->ticket.tail_hooked = true;
        return true;
    }

    bool tail_hooked_engine_family(const EngineTicket& ticket, const Source& source, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* engine = find_engine(ticket);
        if (!engine || !engine->ticket.render_seen || engine->ticket.tail_hooked || !command) return false;
        Slot* producer{};
        if (source) {
            producer = find(source);
            if (!producer || !producer->render_seen || producer->tail_hooked ||
                source.generation != ticket.generation || source.serial != ticket.serial ||
                source.engine_frame != ticket.engine_frame || source.family != ticket.family ||
                source.target != ticket.target || source.scene != ticket.scene) return false;
        }
        engine->ticket.command = command;
        engine->ticket.tail_hooked = true;
        if (producer) { producer->command = command; producer->tail_hooked = true; }
        return true;
    }

    bool executed_engine_family(const EngineTicket& ticket, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find_engine(ticket);
        if (!slot || !slot->ticket.tail_hooked || slot->ticket.command != command) return false;
        *slot = {};
        return true;
    }

    bool executed_engine_family(const EngineTicket& ticket, const Source& source,
                                uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* engine = find_engine(ticket);
        if (!engine || !engine->ticket.tail_hooked || engine->ticket.command != command || !thread) return false;
        Slot* producer{};
        if (source) {
            producer = find(source);
            if (!producer || !producer->tail_hooked || producer->command != command || producer->executed ||
                source.generation != ticket.generation || source.serial != ticket.serial ||
                source.engine_frame != ticket.engine_frame || source.family != ticket.family ||
                source.target != ticket.target || source.scene != ticket.scene) return false;
        }
        if (producer) {
            producer->thread = thread;
            producer->executed = true;
            for (auto& older : slots_) {
                if (&older != producer && older.source && older.executed &&
                    older.source.generation == source.generation && older.source.serial < source.serial &&
                    older.source.target == source.target && !older.submitted) older = {};
            }
        }
        *engine = {};
        return true;
    }

    bool engine_commands_retired(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        if (engine_overflow_generation_ == generation) return false;
        for (const auto& slot : engine_slots_) {
            if (slot.ticket && slot.ticket.generation == generation) return false;
        }
        for (const auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && !slot.executed) return false;
        }
        return true;
    }

    size_t pending_engine_commands(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        size_t count{};
        for (const auto& slot : engine_slots_)
            if (slot.ticket && slot.ticket.generation == generation) ++count;
        return count;
    }

    bool engine_tracking_overflowed(uint64_t generation) const {
        std::scoped_lock lock{mutex_};
        return engine_overflow_generation_ == generation;
    }

    // Publish the validated assigned frame and source in one ledger insertion.
    // Separate family() + bind_engine_frame() calls allow a render-thread race.
    bool register_bound(Source source) {
        if (!source || source.engine_frame == 0xffffffffu) return false;
        for (size_t i = 0; i < source.view_ids.size(); ++i) {
            if (!source.view_ids[i]) return false;
            for (size_t j = 0; j < i; ++j) if (source.view_ids[i] == source.view_ids[j]) return false;
        }
        source.engine_frame_bound = true;
        return family(std::move(source));
    }

    bool family(Source source) {
        std::scoped_lock lock{mutex_};
        if (!source || !advance(source.generation)) return false;
        // A newer family can be queued while an older RHI command still owns
        // the atlas. Preserve the old executed candidate until the newer draw
        // actually executes; execution below is the point at which reuse can
        // invalidate the earlier contents.
        for (auto& slot : slots_) {
            if (slot.source && slot.source.same_owner(source)) return false;
        }
        for (auto& slot : slots_) {
            if (!slot.source) {
                slot.source = std::move(source);
                return true;
            }
        }
        Slot* recoverable{};
        for (auto& slot : slots_) {
            if (slot.source && !slot.tail_hooked && !slot.executed && !slot.submitted &&
                (recoverable == nullptr || slot.source.serial < recoverable->source.serial)) {
                recoverable = &slot;
            }
        }
        if (recoverable != nullptr) {
            *recoverable = {};
            recoverable->source = std::move(source);
            return true;
        }
        return false;
    }


    // Game thread observes a fully constructed UE family before the outer
    // BeginRenderingViewFamilies hook registers its immutable source packet.
    // Stage the engine-assigned frame now, and consume it only against the
    // same original family/scene/target and all four original view pointers.
    bool observe_gt_frame(uint64_t generation, uint64_t draw_serial, uintptr_t family,
                          uintptr_t target, uintptr_t scene,
                          const std::array<uintptr_t, 4>& views,
                          uint32_t engine_frame) {
        if (!generation || !draw_serial || !family || !target || !scene || engine_frame == 0xffffffffu)
            return false;
        for (size_t i = 0; i < views.size(); ++i) {
            if (!views[i]) return false;
            for (size_t j = 0; j < i; ++j) if (views[i] == views[j]) return false;
        }
        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return false;
        FrameTicket* slot{};
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation == generation && ticket.family == family) {
                // A Family pointer can be recycled. Invalidate the older GT
                // observation rather than allowing it to identify a new draw.
                slot = &ticket;
                break;
            }
        }
        if (!slot) {
            for (auto& ticket : frame_tickets_) {
                if (!ticket.generation) { slot = &ticket; break; }
            }
        }
        if (!slot) {
            // These are GT-only observations, not GPU packet owners. Expire
            // the oldest unclaimed observation when the bounded ring fills.
            for (auto& ticket : frame_tickets_) {
                if (!slot || ticket.ordinal < slot->ordinal) slot = &ticket;
            }
        }
        if (!slot) return false;
        *slot = FrameTicket{generation, draw_serial, family, target, scene, views, engine_frame, ++ticket_clock_};
        return true;
    }

    std::optional<uint32_t> take_observed_gt_frame(
        uint64_t generation, uint64_t draw_serial, uintptr_t family, uintptr_t target,
        uintptr_t scene, const std::array<uintptr_t, 4>& views) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !draw_serial || !family || !target || !scene) return {};
        FrameTicket* matched{};
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation != generation || ticket.draw_serial != draw_serial || ticket.family != family ||
                ticket.target != target || ticket.scene != scene ||
                ticket.views != views) continue;
            if (matched) return {}; // Never choose between ambiguous owners.
            matched = &ticket;
        }
        if (!matched) return {};
        const auto frame = matched->engine_frame;
        *matched = {};
        return frame;
    }

    // Called from the game-thread ISceneViewExtension callback after Unreal
    // has assigned FSceneViewFamily::FrameNumber and before FSceneRenderer
    // copies the family/views. The serial plus original-family/view identities
    // make this a one-to-one binding even when UE reuses object addresses.
    // A conflicting already-bound tuple is rejected instead of leaving the RT
    // callback to guess between two owners.
    std::optional<Source> bind_engine_frame(uint64_t generation, uint64_t serial,
                                            uintptr_t family, uintptr_t target, uintptr_t scene,
                                            const std::array<uintptr_t, 4>& views,
                                            uint32_t engine_frame) {
        if (!generation || !serial || !family || !target || !scene || engine_frame == 0xffffffffu) return {};
        for (size_t i = 0; i < views.size(); ++i) {
            if (!views[i]) return {};
            for (size_t j = 0; j < i; ++j) if (views[i] == views[j]) return {};
        }

        std::scoped_lock lock{mutex_};
        if (!advance(generation)) return {};

        Slot* match{};
        for (auto& slot : slots_) {
            const auto& source = slot.source;
            if (!source || source.generation != generation || source.serial != serial ||
                source.family != family || source.target != target || source.scene != scene ||
                source.view_ids != views) continue;
            if (match != nullptr) return {};
            match = &slot;
        }
        if (match == nullptr || match->render_seen || match->source.engine_frame_bound) return {};

        for (const auto& slot : slots_) {
            const auto& source = slot.source;
            if (&slot != match && source && source.generation == generation && source.engine_frame_bound &&
                source.engine_frame == engine_frame && source.target == target && source.scene == scene) {
                return {};
            }
        }

        match->source.engine_frame = engine_frame;
        match->source.engine_frame_bound = true;
        return match->source;
    }

    std::optional<Source> render(uint64_t generation, uint32_t frame,
                                 uintptr_t family, uintptr_t target, uintptr_t scene) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !family || !target || !scene) return {};
        Slot* match{};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && slot.source.engine_frame_bound &&
                // Unreal may pass a renderer-owned copy of FSceneViewFamily to
                // the render thread. Resolve it by the exact frame bound on the
                // original GT family, target and scene; keep source.family as
                // provenance only.
                slot.source.engine_frame == frame &&
                slot.source.target == target && slot.source.scene == scene) {
                if (match != nullptr) return {}; // Multiple matching owners are ambiguous.
                match = &slot;
            }
        }
        if (match == nullptr || match->render_seen) return {};
        match->render_seen = true;
        return match->source;
    }

    bool tail_hooked(const Source& source, uintptr_t command) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->render_seen || !command || slot->tail_hooked) return false;
        slot->command = command;
        slot->tail_hooked = true;
        return true;
    }

    bool executed(const Source& source, uintptr_t command, uint32_t thread) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->tail_hooked || slot->command != command || !thread || slot->executed) return false;
        slot->thread = thread;
        slot->executed = true;
        // A later execution to the same source target proves that its contents
        // have replaced every older unsubmitted image in that atlas. Retire
        // those candidates only now, not when the game thread merely queues a
        // newer family. Submitted sources retain their command-slot owner until
        // explicit retirement.
        for (auto& older : slots_) {
            if (&older != slot && older.source && older.executed &&
                older.source.generation == source.generation &&
                older.source.serial < source.serial &&
                older.source.target == source.target && !older.submitted) {
                older = {};
            }
        }
        return true;
    }

    // Select the newest exact source owner whose RHI command executed on the
    // submission thread. Never match against an independently sampled UE or XR
    // frame counter: the selected packet carries the two frozen eye poses that
    // must accompany its atlas. Selection is a peek until XR accepts the copy.
    std::optional<Source> select(uint64_t generation, uint32_t submit_thread) {
        std::scoped_lock lock{mutex_};
        if (!advance(generation) || !submit_thread) return {};
        Slot* match{};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation &&
                slot.executed && slot.thread == submit_thread && !slot.submitted) {
                if (match == nullptr || slot.source.serial > match->source.serial) {
                    match = &slot;
                } else if (slot.source.serial == match->source.serial) {
                    return {}; // Do not guess between duplicate producers for one draw.
                }
            }
        }
        if (!match) return {};
        return match->source;
    }

    // Call only after the OpenXR copy callback recorded commands and the copy
    // was accepted. A temporary slot miss leaves the exact source retryable.
    bool submitted(const Source& source, uintptr_t destination) {
        std::scoped_lock lock{mutex_};
        auto* slot = find(source);
        if (!slot || !slot->executed || slot->submitted || !destination) return false;
        slot->submitted = true;
        slot->destination = destination;
        return true;
    }

    bool execution_evidence(const Source& source, uintptr_t& command, uint32_t& thread) const {
        std::scoped_lock lock{mutex_};
        const auto* slot = find(source);
        if (!slot || !slot->tail_hooked || !slot->executed) return false;
        command = slot->command;
        thread = slot->thread;
        return command != 0 && thread != 0;
    }

    bool retire(uint64_t generation, uint64_t serial) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation && slot.source.serial == serial) {
                slot = {};
                return true;
            }
        }
        return false;
    }

    void retire_generation(uint64_t generation) {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) {
            if (slot.source && slot.source.generation == generation) slot = {};
        }
        for (auto& ticket : frame_tickets_) {
            if (ticket.generation == generation) ticket = {};
        }
        for (auto& slot : engine_slots_) {
            if (slot.ticket.generation == generation) slot = {};
        }
        if (engine_overflow_generation_ == generation) engine_overflow_generation_ = 0;
        if (generation >= generation_) generation_ = generation;
    }

    void retire_all() {
        std::scoped_lock lock{mutex_};
        for (auto& slot : slots_) slot = {};
        for (auto& ticket : frame_tickets_) ticket = {};
        for (auto& slot : engine_slots_) slot = {};
        ticket_clock_ = 0;
        engine_overflow_generation_ = 0;
        generation_ = 0;
    }

private:
    struct EngineSlot { EngineTicket ticket{}; };
    struct FrameTicket {
        uint64_t generation{}, draw_serial{};
        uintptr_t family{}, target{}, scene{};
        std::array<uintptr_t, 4> views{};
        uint32_t engine_frame{};
        uint64_t ordinal{};
    };
    struct Slot {
        Source source{};
        uintptr_t command{}, destination{};
        uint32_t thread{};
        bool render_seen{}, tail_hooked{}, executed{}, submitted{};
    };
    Slot* find(const Source& source) {
        for (auto& slot : slots_) if (slot.source && slot.source.same_owner(source)) return &slot;
        return nullptr;
    }
    const Slot* find(const Source& source) const {
        for (const auto& slot : slots_) if (slot.source && slot.source.same_owner(source)) return &slot;
        return nullptr;
    }
    EngineSlot* find_engine(const EngineTicket& ticket) {
        for (auto& slot : engine_slots_) if (slot.ticket && slot.ticket.same_owner(ticket)) return &slot;
        return nullptr;
    }
    bool advance(uint64_t generation) {
        if (!generation || generation < generation_) return false;
        if (generation != generation_) {
            for (auto& slot : slots_) slot = {};
            for (auto& ticket : frame_tickets_) ticket = {};
            for (auto& slot : engine_slots_) slot = {};
            ticket_clock_ = 0;
            engine_overflow_generation_ = 0;
            generation_ = generation;
        }
        return true;
    }
    mutable std::mutex mutex_;
    uint64_t generation_{};
    uint64_t ticket_clock_{};
    std::array<FrameTicket, Capacity> frame_tickets_{};
    std::array<EngineSlot, Capacity> engine_slots_{};
    std::array<Slot, Capacity> slots_{};
    uint64_t engine_overflow_generation_{};
};

} // namespace uevr::quadview
