#pragma once

#include <cstdint>
#include <mutex>
#include <optional>

namespace uevr::quadview {

constexpr bool source_admission_open(bool quadview_selected, bool transition_pending) {
    return quadview_selected && !transition_pending;
}

constexpr unsigned desired_view_count(bool quadview_selected, bool hooks_ready,
                                      bool inside_post_init, bool transition_pending = false) {
    if (inside_post_init || transition_pending || !quadview_selected || !hooks_ready) return 2;
    return 4;
}

struct DrawDemand {
    uint64_t generation{}, serial{}, request_token{};
    unsigned view_count{2};
    bool quadview_selected{};
    bool source_admission{};
};

// Selection and transition state are sampled once at viewport-draw entry.
// Every view callback in that draw sees this same demand even if UI state
// changes between callbacks; the next draw observes the pending transition.
class DrawDemandLatch {
public:
    DrawDemand begin(uint64_t generation, uint64_t serial, bool selected, bool pending,
                     uint64_t request_token = 0) {
        std::scoped_lock lock{mutex_};
        current_ = DrawDemand{generation, serial, request_token, desired_view_count(selected, true, false, pending),
                              selected, source_admission_open(selected, pending)};
        if (current_->view_count != 4) current_->source_admission = false;
        return *current_;
    }

    std::optional<DrawDemand> get(uint64_t generation, uint64_t serial) const {
        std::scoped_lock lock{mutex_};
        if (!current_ || current_->generation != generation || current_->serial != serial) return {};
        return current_;
    }

    bool transition_closed(uint64_t generation, uint64_t serial, uint64_t request_token,
                          bool selected, bool pending) const {
        if (!selected) return true;
        const auto demand = get(generation, serial);
        return pending && demand && demand->request_token == request_token &&
            demand->view_count == 2 && !demand->source_admission;
    }

    void reset() {
        std::scoped_lock lock{mutex_};
        current_.reset();
    }

private:
    mutable std::mutex mutex_{};
    std::optional<DrawDemand> current_{};
};

} // namespace uevr::quadview
