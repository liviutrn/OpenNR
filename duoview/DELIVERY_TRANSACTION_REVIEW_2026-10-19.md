# DuoView rendering transaction correction

Base: published Build 176, `7d6eaa6c5a0a2d6a458e40f81b46c9a0d06ab487`.
The rejected local `db8299c1` is not an ancestor and is not included.

## Evidence and limits

The original runtime log contains 177 sampled age rejections, all +2/+2.
The screenshot reports 2,568 copied, 295 held, 16 empty/failed. That is
10.8% without a fresh copy, including startup. These establish the failing
age gate, not the temporal correctness of accepting its rejected packets.

Both engine family IDs and the last-Present counter are unsuitable joins
between a game-thread renderer invocation and RHI-thread source contents.
The pending-command path also overwrites its frame before detecting an
existing hook. The log does not show the old/incoming identity, so that
conflict is a source-confirmed hazard, not a proven explanation of every
observed hitch. This implementation addresses ownership rather than
adding +2, accepting a draw-distance window, or renewing timestamps.

## Transaction timeline

1. Before either original Native Fix renderer call, build one immutable
   packet containing the frozen Duo configuration, original XR pose token,
   copied pose, capture generation, main/capture target identities and a
   retained primary native resource. Ordinary Native still makes its packet
   at the original publication point.
2. During each synchronous BeginRenderViewFamily callback, associate the
   actual family number, scene and target with that exact packet and the
   primary/secondary source role. The mapping is bounded metadata, not an
   image queue. Duplicate family identity cannot replace its owner.
3. PreRenderViewFamily_RenderThread looks up that exact family/scene/target,
   independent of the latest GT draw or XR pose-ring slot. Auxiliary targets
   do not replace either source. An unbound known source carries an invalid
   marker, preventing reuse of an older packet for overwritten contents.
4. On the existing recognized new-command path, find the current command
   tail using the SDK Next chain, bounded at 65,536 commands. Pending command
   owners never change. Re-observing the same owner is inert; a conflicting
   owner is diagnosed and cannot be accepted. STALKER's observed deferred
   Slate path drains both source callbacks against the same command tail:
   it attaches both roles only when they share the identical immutable packet,
   generation and scene with distinct targets. The original command frame
   remains unchanged. The existing original-vtable
   restoration and execute-index logic remain in use. Tail traversal caches
   readable memory regions only within the current call; it does not retain
   allocator pointers across calls.
5. After the original tail command executes, record that source's packet
   and execution thread. A direct PreRender checkpoint precedes rendering;
   a deferred Slate checkpoint follows source-command recording. Neither is
   a claim that a GPU image has completed. The two source labels
   must agree on the same immutable packet at Present. RT/GT work ahead of
   the presented transaction cannot select a newer packet prematurely.
6. At DXGI Present on that same RHI thread, source commands preceding Present
   have already been handled by the engine. The compositor uses the owning
   swapchain direct queue. Existing graphics queue ordering places its reads
   after scene writes; engine async work remains subject to engine queue
   dependencies. No CPU GPU wait or source snapshot copy was added. A title
   that executes these source markers on a different parallel RHI worker
   will fail the thread check, not acquire an invented ordering guarantee.
7. Duo selection uses the two executed source owners, retaining main-target,
   capture-generation/resource, primary native-resource, binding, pose and
   device checks. A partially overwritten source pair cannot select the
   previous completed transaction. Native/Mono retain their clock policies.
8. Successful copy accounting requires recorded commands, a newly signalled
   fence, a healthy command context, matching device/owning queue and release
   of the acquired XR image. Existing command-slot fences retain packet and
   resource references. Unique XR delivery is counted only after successful
   xrEndFrame with a projection. A held projection remains held; duplicate
   Presents are separately visible and do not inflate unique delivery.

If marker installation fails, the affected serial and all earlier packets
are blocked. A later completely tracked transaction can recover. This may
miss valid work conservatively on the failure path; it never disguises an
unknown source rewrite as a fresh delivery. No wider hold or acceptance
window was introduced. The existing 100ms hold is unchanged and still counts
as a missed fresh submission.

## Review and verification

- New transaction state serializes all shared access; pending RHI maps remain
  under Joey's existing recursive vtable mutex. Immutable metadata travels
  through delayed Slate callbacks by value.
- Mode changes, quarantine and device reset release cached source/family
  references. Pending RHI commands and GPU slots retain their own packets;
  pre-retirement serials cannot repopulate the cache.
- Old-generation markers cannot advance ownership, relabel pending commands,
  or assign old poses after a mode switch. Capture rejection and compositor
  retirement logic remain unchanged. Shading/render order, crop, gaze, source
  densities, direct-output option and shaders are unchanged.
- Host test: 100,000 asynchronous transactions, producer 0-8 transactions
  ahead; every complete pair selects its own packet/pose. Tests also cover
  mixed/unknown sources, auxiliary callbacks, duplicate Present accounting,
  failed submission accounting, generation changes/delayed callbacks, family
  counter wrap, bounded-registry overflow, command-tail growth/cycles, blocked
  source recovery and packet lifetime. Half the asynchronous transactions
  share a deferred Slate command; the other half use separate source commands.
  Same-command peer attachment, duplicates, cross-transaction conflicts and
  preservation of the first attached frame are explicitly tested.
- Host ASan/UBSan passes with leak scanning disabled because this container
  prevents LeakSanitizer enumerating /proc tasks. Existing five independent
  CPU suites and pinned production contract are also run. The 100,000-
  transaction test also passes under ThreadSanitizer.
- Exact-anchor reconstruction is verified locally; Windows shader compilation,
  GPU WARP tests, original compatibility suite and backend/frontend build run
  in the pinned GitHub Actions recipe, with the added delivery test. Backend
  compilation precedes the long compatibility-target build to catch integration
  errors earlier; every original validation step is retained.

## Hardware acceptance, still outstanding

No headset or STALKER 2 execution is available here. The host simulation
cannot establish real command-list ABI behavior, actual engine scheduling,
GPU cost of tail traversal, visual parity or a <=0.001% runtime miss rate.
Do not call this a headset-proven fluidity fix.

Use a separate test directory. After warmup reset counters, then compare
produced/RHI pairs/matched/enqueued/unique XR, overwritten/unproven/failure,
and the existing held/empty counters over at least 100,000 expected fresh
scenes. Test Direct XR OFF/ON; shading layout ON/OFF; source debug views;
fixed/gaze modes and gaze loss; resize and mode reselection; Native ID0 and
Mono ID5. Zero held/empty/overwritten steady-state events is the target.
New flight-recorder events stay in an 8,192-entry RAM ring; a missing pair
prints only its last 24 entries, at most once per five seconds. Their draw,
pose, family, command, target, generation, serial and thread fields distinguish
unregistered families, pending conflicts, worker-thread mismatch and actual
XR failures if a hardware test still misses delivery.
