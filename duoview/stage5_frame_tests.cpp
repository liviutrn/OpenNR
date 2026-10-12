#include "DuoViewFrame.hpp"
#include <cassert>
#include <iostream>
using namespace uevr::duoview;
int main() {
    auto l=make_layout(3000,3000);
    assert(l && layout_valid(*l));
    FrameCoordinator c;
    const FrameKey k{10,100}, future{10,101}, old{9,100};
    const RenderFrame f{k,*l,5000,340};
    assert(!c.begin({{0,0},*l,5000,340}));
    assert(c.begin(f));
    assert(!c.begin(f)); // reused render frame must not be accepted
    assert(c.snapshot(k));
    assert(c.begin({future,*l,5001,355}));
    assert(!c.note_view(k,0,5000));
    assert(!c.note_view(future,0,5000)); // stale pose
    assert(c.note_view(future,0,5001));
    assert(!c.note_view(future,0,5001)); // duplicate
    assert(!c.queue_composite(future,200,123)); // one view missing
    assert(c.note_view(future,1,5001));
    assert(!c.queue_composite(old,200,123));
    assert(c.queue_composite(future,200,123));
    assert(!c.queue_composite(future,200,124));
    assert(!c.note_gpu_complete(future,122));
    assert(!c.consume_for_submit(future).has_value());
    assert(c.note_gpu_complete(future,123));
    assert(!c.consume_for_submit(k));
    auto out=c.consume_for_submit(future);
    assert(out && out->output_resource_id==200 && out->gpu_fence_value==123);
    assert(!c.consume_for_submit(future));
    // Cross-generation transitions cannot consume a pending DX12 output.
    c.retire();
    assert(!c.consume_for_submit(future));
    assert(c.begin({{11,1},*l,5002,400}));
    // Once generation 11 begins, late generation-10 callbacks must never
    // displace generation 11 (even with arbitrarily high frame counters).
    assert(!c.begin({{10,9999},*l,5000,9999}));
    assert(c.snapshot({11,1}));
    assert(c.begin({{11,2},*l,5002,410}));
    assert(!c.note_view(future,1,5001));
    assert(c.snapshot({11,2}));
    assert(!c.snapshot(future));
    auto invalid=*l; invalid.periphery.x=0;
    assert(!layout_valid(invalid));
    assert(!c.begin({{11,3},invalid,5002,440}));
    assert(c.snapshot({11,2}));
    assert(!c.snapshot({11,1}));
    std::cout<<"DuoView immutable frame/fence policy tests passed\n";
}
