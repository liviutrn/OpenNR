#include "mods/vr/MonoRenderingPolicy.hpp"
#include <cassert>
#include <cstdint>

int main() {
    namespace m = uevr::mono;
    static_assert(m::method_id == 5);
    static_assert(m::duoview_method_id == 6);
    static_assert(m::is_mono_method(5) && m::is_mono_method(6));
    static_assert(!m::is_mono_method(0) && !m::is_mono_method(7));
    static_assert(m::available(6) && m::available(6, m::non_dibr_choices));
    static_assert(!m::available(7));
    static_assert(m::needs_frame_gate(6, 1, 1));

    m::Selection s;
    s.initialize(6);
    assert(s.active() == 0 && s.requested() == 6 && s.pending());
    assert(!s.commit_at_game_frame_boundary());
    s.consumers_retired(s.request_token());
    assert(s.commit_at_game_frame_boundary() && s.active() == 6);
    s.request(5);
    assert(s.active() == 6 && s.pending());
    assert(!s.commit_at_game_frame_boundary());
    s.consumers_retired(s.request_token());
    assert(s.commit_at_game_frame_boundary() && s.active() == 5);
    s.request(0);
    assert(s.active() == 5 && s.pending());
    s.consumers_retired(s.request_token());
    assert(s.commit_at_game_frame_boundary() && s.active() == 0);
}
