#include "DuoViewActivation.hpp"
#include <cassert>
using namespace uevr::duoview;
int main() {
  ActivationGate gate;
  gate.configure(true,5);
  CopyContractEvidence e{.backend_generation=5,.producer_frame=100,
    .exact_binary=true,.source_identity=true,.source_state_known=true,
    .producer_queue_ordered=true,.destination_swapchain_known=true,
    .copy_success_observable=true,.submit_time_known=true,
    .optical_basis_synchronized=true,.gpu_pipeline_prepared=true};
  assert(!gate.start_frame(5,100)); // no speculative rendering
  assert(!gate.observe({})); // no packet = no activation
  auto missing=e;missing.source_state_known=false;
  assert(!gate.observe(missing)); // RT flag alone is insufficient
  missing=e;missing.copy_success_observable=false;
  assert(!gate.observe(missing)); // queued GPU work != completed copy
  missing=e;missing.submit_time_known=false;
  assert(!gate.observe(missing)); // locate time != predicted display time
  missing=e;missing.destination_swapchain_known=false;
  assert(!gate.observe(missing)); // cannot just overwrite UE owned atlas
  assert(gate.observe(e));
  assert(gate.start_frame(5,100));
  assert(!gate.start_frame(5,101)); // never overlap two partial generations
  assert(!gate.complete_copy(5,100,false,true)); // wrong XR destination
  assert(gate.phase()==ActivationPhase::Blocked);
  assert(!gate.start_frame(5,102));
  gate.reset(6);
  assert(!gate.observe(e)); // stale evidence
  e.backend_generation=6;
  assert(gate.observe(e));
  assert(gate.start_frame(6,200));
  assert(!gate.complete_copy(6,200,true,false)); // failed Joey copy
  assert(gate.phase()==ActivationPhase::Blocked);
  gate.reset(7);e.backend_generation=7;
  assert(gate.observe(e));assert(gate.start_frame(7,300));
  assert(gate.complete_copy(7,300,true,true));
  assert(gate.phase()==ActivationPhase::Ready);
  assert(gate.start_frame(7,301));
  gate.configure(false,7);
  assert(gate.phase()==ActivationPhase::Disabled);
  assert(!gate.start_frame(7,302));
}
