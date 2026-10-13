#include "joey_plugin/LiveFrameSafety.hpp"
#include "joey_plugin/CopyFlow.hpp"
#include <cassert>
#include <cstdint>
using namespace duoview_joey;

// These are the same constexpr decisions invoked from the real plugin's
// viewport callback and xrEndFrame hook, not an unused mock activation class.
int main() {
    for (unsigned mask=0; mask<32; ++mask) {
        const bool compatible=bool(mask&1),armed=bool(mask&2),faulted=bool(mask&4);
        const bool optics=bool(mask&8),slot=bool(mask&16);
        const bool expected=compatible && armed && !faulted && optics && slot;
        assert(LiveFrameSafety::may_crop(compatible,armed,faulted,optics,slot)==expected);
    }
    for(unsigned mask=0; mask<16; ++mask) {
        const bool scene=bool(mask&1),verified=bool(mask&2),xr=bool(mask&4),same=bool(mask&8);
        const bool accepted=scene&&verified&&xr&&same;
        assert(LiveFrameSafety::accept_image(scene,verified,xr,same)==accepted);
        assert(!LiveFrameSafety::arm_next(accepted,true));
        assert(LiveFrameSafety::arm_next(accepted,false)==accepted);
    }
    for(unsigned mask=0; mask<8; ++mask) {
        bool matched=mask&1,failed=mask&2,verified=mask&4;
        assert(LiveFrameSafety::suppress_scene(matched,failed,verified)==(matched&&failed&&!verified));
    }
    // Baseline is not armed merely because a compositor exists. Both a
    // queued copy and a successfully accepted scene are mandatory.
    bool armed=false,faulted=false,have_hold=false;
    const auto baseline=choose_copy({true,false,false,true,false,have_hold,true});
    assert(baseline==CopyAction::Native);
    CopyProof baseline_proof{true,true,true,false,true,40,41};
    assert(baseline_proof.queued());
    const bool accepted=LiveFrameSafety::accept_image(true,baseline_proof.queued(),true,true);
    armed=LiveFrameSafety::arm_next(accepted,faulted);
    have_hold=accepted;
    assert(armed && have_hold);
    assert(LiveFrameSafety::may_crop(true,armed,faulted,true,true));
    assert(choose_copy({false,true,true,true,true,have_hold,true})==CopyAction::Compose);
    // Missing render callback, missing compositor slot, mismatch and a
    // fully failed GPU proof may not authorize a new modified image.
    assert(choose_copy({false,true,false,true,true,have_hold,true})==CopyAction::Hold);
    assert(choose_copy({false,true,true,true,false,have_hold,true})==CopyAction::Hold);
    assert(choose_copy({false,true,true,true,true,have_hold,false})==CopyAction::Reject);
    CopyProof bad=baseline_proof;
    bad.recorded=false;
    assert(!bad.queued());
    assert(!LiveFrameSafety::accept_image(true,bad.queued(),true,true));
    faulted=true;armed=false;
    assert(!LiveFrameSafety::may_crop(true,armed,faulted,true,true));
    assert(LiveFrameSafety::suppress_scene(true,true,false));
    // A scene accepted by XR may be held, but XR success alone is never
    // treated as proof of its GPU copy or generation.
    assert(!LiveFrameSafety::accept_image(true,false,true,true));
    assert(!LiveFrameSafety::accept_image(true,true,true,false));
    assert(!LiveFrameSafety::accept_image(true,true,false,true));
    // Exercise the same decisions over a long deterministic frame sequence.
    for(unsigned i=0;i<100000;++i) {
        bool copy=(i%101)!=0, scene=(i%139)!=0, xr=(i%67)!=0, same=(i%911)!=0;
        const auto accepted_frame=LiveFrameSafety::accept_image(scene,copy,xr,same);
        assert(accepted_frame==bool(scene&&copy&&xr&&same));
        assert(!LiveFrameSafety::arm_next(accepted_frame,true));
        assert(LiveFrameSafety::suppress_scene(scene,!copy,false)==bool(scene&&!copy));
    }
}
