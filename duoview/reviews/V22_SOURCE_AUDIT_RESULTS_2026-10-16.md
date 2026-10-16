# DuoView v22 fixed-center: source audit and corrections

Status: **SOURCE-ONLY PASS. Uncompiled; no shader generated, Actions dispatched,
DLL or headset package produced. Not runtime validated or release-ready.**

The review branch began at `b59e8879a61a46b141a7bdfcc81ad64b3e5c4c75`,
whose parent source baseline is `0bf0e66781fc512142e9a6fe92943ea2bac81544`.
The branch is `experiments/duoview-joey-v22-astra-source-audit`. The latest
GPU-retirement checkpoint is `7c2d9151be63c0cd754dbcaa0b4c47c6fa131825`.
The canonical recovery branch, protected v22 branch and tested Build 3 were
not modified. This report records the requested Luna worker implementation
pass with parent-supervisor review; it is not an independent third-party or
runtime audit.

## Result

The initial audit found source-demonstrable pairing, frame identity,
constructor restoration, presentation-success, OpenVR execution, fault
serialization and startup allocation defects. This update also repairs the
recoverable command-retirement and startup Draw gates described below. The
exact-pinned Joey backend/frontend transform and static source guards pass.
That result says nothing about C++ ABI correctness, GPU execution, Unreal's
earlier allocation order, rendered image quality, or headset behavior.

Scope remains STALKER2 DX12, fixed horizontal center and adjustable vertical
center, no production gaze acquisition. Automatic failure destination remains
real Mono ID5. No automatic ID0 fallback is introduced. Other game modes and
manual rendering-method choices retain their existing policy.

## Sources actually examined

| Source | Exact revision / evidence |
|---|---|
| OpenNR input | `0bf0e66781fc512142e9a6fe92943ea2bac81544` |
| Joey backend | `5ac7edc207866569334175e4ed8a7517971547f6`, clean checkout followed by Stage1 and Stage234 |
| Joey frontend | `60be4b0f9a646109fd9fdf448bacd41477234091`, clean checkout followed by both stages |
| Private UESDK | `3cffbc82429b6165ceec2714f0f0d9ae48f55596`, tree and relevant declarations read through authorized GitHub connection |
| SDK declarations inspected | `src/sdk/FSceneView.hpp`, `FSceneViewFamily.hpp`, `TArray.hpp` |
| Effective rendering source | `VR.hpp/.cpp`, `FFakeStereoRenderingHook.cpp`, `D3D12Component.hpp/.cpp`, `runtimes/OpenVR.cpp`, `runtimes/OpenXR.cpp` |
| Additional reviewed contracts | `DuoViewState`, `DuoViewConfig`, geometry, compositor, copy helper, `CommandContext`, `GpuRetirement`, Mono selection and production tests |

The SDK was not fully checked out or modified. Full baseline/SDK hash
verification is still a later gate; API-read declarations are not that gate.
No SDK source is copied into this report or the public repository.

## Confirmed defects and source corrections

### P0-A01: pair publication could never run on OpenVR

In `FFakeStereoRenderingHook::begin_render_viewfamily`, Stage234 had inserted
`duoview_state().family(...)` inside `mono_frame_gate_required() &&
runtime->is_openxr()`. OpenVR could never set `ViewFrame::main_family`, while
`State::consume` required it. The resulting pair was rejected regardless of
the correctness of its camera and rectangles.

**Corrected:** publish the DuoView family outside the OpenXR-only block.
Use the same validated render-target identity as the source constructor.
OpenXR's separate Mono bookkeeping still runs only on OpenXR. Its DuoView
count check now requires two views, not one or two.

### P0-A02: producer frame was incremented twice on the normal Draw path

The Draw hook calls `update_hmd_state(true, internal_frame_count + 1)` before
constructing views. Both pinned runtimes' `update_poses` assign the supplied
frame number to `internal_frame_count`. The former `duoview_producer_key`
then added another one when creating the pair. The later family/submit keys
use the actual frame number. This is a source-demonstrable off-by-one on
that execution path, not an eye-tracking issue.

**Corrected:** latch the predicted Draw frame before pose update, retain it
in a thread-local optional through source construction, and restore its
previous value with a scope guard. The producer getter no longer rereads
or increments the mutable runtime counter. Its generation comes from the
Mono selection, including a transition committed before view construction.
Calls outside a Draw scope receive an invalid key and cannot synthesize a
valid pair.

**Still unverified:** multiple main Draws, auxiliary families, skipped ticks,
level changes and uint32 frame wrap. This fixes the demonstrated normal-path
double increment; it does not prove every Unreal scheduling path.

### P1-A03: temporary family list lacked exception restoration

The old DuoView path set the family count to zero and relied on normal-return
code near the bottom of Joey's constructor hook to restore it. Only init
options had a scope guard. It also published successful scene/shading
evidence before the original constructor returned.

**Corrected:** a DuoView-specific scope guard restores the exact mutated
array on C++ unwind. On normal return it restores immediately after the
constructor. The existing init-options guard is armed before changing the
pass. The SDK's existing `validate_views` contract is checked before hiding
the singleton. Scene evidence is published only after a nonnull constructor
result. Native Stereo's existing restoration path is unchanged.

This is C++ scope-unwind protection, not a promise to recover safely from an
arbitrary access violation, process termination, or corrupted engine memory.
Constructor treatment alone does not prove Lumen parity.

### P1-A04: OpenXR success was reported before projection submission

The DX12 copy branch called `duoview_frame_success` after swapchain copying,
before `xrEndFrame`. A rejected projection could therefore reset the fault
streak repeatedly.

**Corrected:** success now occurs in `OpenXR::end_frame` only after
`xrEndFrame` returns `XR_SUCCESS` with a nonempty scene projection. Failed
projection submission reports a fault. Intentionally empty frames do not
claim DuoView presentation success. Copy failures retain their existing
fault path. This proves API acceptance, not GPU completion or displayed pixels.

### P1-A05: OpenVR could submit output after failed GPU execution

`CommandContext::execute()` returns void and can poison itself after Close,
queue, Signal or fence-event failure. The old caller unconditionally selected
the DuoView output after calling it. Original per-eye helpers also ignored
retirement failure and provided no enqueue proof to DuoView.

**Corrected:** the DuoView compositor requires a healthy context, a newly
advanced fence, and a pending submission before selecting its output. Any
recorded partial commands are tracked even if the final record result is
false. A DuoView-only pair-copy helper checks retirement and each eye's new
fence, and completes both copy enqueues before either SteamVR Submit. Failed
copies stop submission and report a fault. Both compositor Submit results
must still succeed before presentation success is reported.

The new helper does not alter original ID0/ID5 copy routines. It preserves
the existing waits; no allocator reuse was made nonblocking without a ring
or equivalent ownership design. Severe GPU recovery remains blocked below.

### P1-A06: independent atomics did not make fault updates transactional

After an abort callback checked `last_success_tick`, a concurrent success
could reset the streak before the abort incremented it again. Similarly,
the game-thread fallback recheck could race with a success reset. Atomics
on individual fields did not prevent those interleavings.

**Corrected:** one mutex serializes abort, success, reset, and the game-thread
fallback recheck/request. It is released before servicing the Mono transition
or touching graphics resources. Tick deduplication and 60/4 thresholds remain.
This makes these operations ordered; a future success cannot undo a fallback
decision already committed under the lock. Game-tick attribution remains an
approximation of render-frame attribution and requires instrumentation.

### P2-A07: validation and diagnostic gaps

- Clamp persisted vertical position to `[0,1]`, replacing nonfinite input
  with center. ConfigLatch still rejects invalid low-level settings.
- Prewarm OpenVR with the source's actual sRGB interpretation, avoiding the
  known first-record mismatch for explicitly sRGB sources.
- Pass optional GPU timing through the OpenVR compositor and publish its
  retired sample to the existing UI.
- Limit the prospective full-width DX12 output to 16384, consistent with
  the existing geometry limit, before allocation.
- Report the secondary constructor as waiting/validated instead of showing
  a misleading disabled independent-shading toggle.
- Add `--source-only` to Stage234. It omits shader generation and explicitly
  reports that full verification/compilation was not performed. Normal CI
  still requires shader generation and the full verifier; no build gate
  is bypassed or fabricated.

### P0-A08: poisoned command contexts could wedge mode transitions or free live work

The shared `CommandContext` could become poisoned after `ExecuteCommandLists`
without a usable fence. Ordinary retirement rejected every poisoned context,
while teardown ignored a timed wait result and released command and compositor
resources. An OpenVR one-slot wait could also block indefinitely when GPU work
was simply still pending.

**Corrected in the source transformer:** DuoView submissions opt into exact
queue/device and fence tracking inside `execute()`. After `ExecuteCommandLists`,
retirement is proven only by a successfully signaled submitted fence, a
successfully signaled same-queue recovery fence that has completed, or confirmed
device removal on the captured device. A prior fence value, malformed/default
signal evidence, or a timeout does not prove completion. Known pre-Execute
failures can discard unsubmitted recording state; recorded but unsubmitted work
remains owned until such explicit proof.

DuoView callers use nonblocking fence polling for the single compositor and
eye-copy slots. Ordinary pending GPU work skips that frame without counting as
a bad-pair failure or forcing the four-frame Mono fallback. On teardown, if
retirement remains unproven, the command allocator/list, fence, captured
queue/device and retained COM resources are quarantined until process exit.
The retained graph includes compositor device/output/source, root signature,
PSO, descriptor heaps, timing resources, submitted source/destination textures,
and the OpenVR output and eye-copy resources.

**Limit:** quarantine intentionally may retain VRAM until process exit after an
unrecoverable fault. Confirmed device removal is treated as a terminal boundary;
its exact behavior still needs device-loss tests. The implementation has not
been exercised by WARP, fault injection, or a headset, so this is a source-level
repair with explicit fail-closed ownership, not a claim of runtime recovery.

### P0-A09: high-resolution launch could draw Native ID0 before Mono startup

At launch, a persisted Mono mode starts with active Native ID0 while the mode
request waits for consumers to retire. That allowed an early high-resolution
Native scene to be allocated before the intended ID6 launch transition.

**Corrected in the source transformer:** the supported STALKER2 viewport Draw
path latches launch intent and holds the target scene before calling UE's
original Draw until backend/runtime/config readiness and the normal mode
transaction are ready. Startup config readiness is published only after the
Framework config-finalized callback captures the baseline request token; this
happens before the initialized atomic becomes visible. The Draw gate uses
`mono_consumers_retired()` and acknowledges the exact request token before
calling the existing game-thread transition service. Persisted ID5 does not
suppress eligible launch auto-start to ID6, and a later manual selection wins.
If the ID6 request is unsupported by current Mono compatibility settings while
ID0 is active, the gate remains closed and the reason is shown until the user
chooses another mode. Confirmed DX11 and non-target paths are left alone.

**Limit:** the guard runs at the earliest supported game-thread viewport Draw
boundary observed by this source hook. It does not prove Unreal made no
full-resolution GPU allocation before that hook, nor that a blocked Draw always
allows every engine/runtime initialization path to progress. Those assumptions
need runtime startup measurements on the pinned STALKER2/OpenXR and OpenVR
paths. No unconditional high-resolution guarantee is claimed.

## Verification performed

1. Read all eleven handoff entries and repository agent instructions.
2. Confirmed the remote recovery branch matched the pinned input at retrieval.
3. Reset separate backend/frontend checkouts to the exact pins, applied Stage1
   then Stage234 with `--source-only`, and required every exact replacement
   anchor to match once. The shader header is intentionally absent.
4. Ran the Stage234 exact path/hash allowlist verifier in source-only mode and
   the static source regression verifier against the transformed backend; both
   passed. Their output explicitly records `source_only=true`,
   `full_sdk_checkout_verified=false`, `shader_generated=false`, and
   `compiled=false`.
5. Parsed the Python transformer and verifiers with Python's AST parser and
   ran `git diff --check`; both passed. No C++ or shader compilation occurred.
6. Added behavioral contract source for fence evidence, pre-Execute failure,
   reset failure, normal GPU backpressure, persisted-ID5 launch behavior,
   exact consumer-retirement token handling, and the unsupported-ID6 startup
   Draw gate. These C++ contracts were **not compiled or executed**.
7. Recorded SHA-256 hashes of the transformed pinned source and current
   OpenNR transformer/contracts in `V22_SOURCE_AUDIT_EVIDENCE_2026-10-16.json`.

The SDK submodule gitlink matches the audited pin, and relevant private SDK
API declarations were read through the authorized GitHub connection. The full
SDK checkout and complete SDK/source hash verification were not performed.
No Windows tests, HLSL compilation, WARP tests, game injection, PSVR2 test,
performance measurement or Actions run was performed. Older CI success does
not validate these changes.

## Unresolved blockers and explicit limits

| Priority | Status | Remaining issue and reason |
|---|---|---|
| P0 | SOURCE PATCHED; runtime unverified | Poisoned-context retirement now records the executing queue/device, tries a same-queue recovery fence, preserves ownership through teardown, and quarantines uncertain work. WARP/fault-injection and device-removal tests are still required. Unproven work can retain resources until process exit. |
| P0 | SOURCE PATCHED; startup unverified | The early game-thread Draw gate uses the real consumer-retirement evidence and existing transition transaction. It does not prove there were no earlier high-resolution allocations or prove engine initialization progresses while Draw is deferred. |
| P0 | NOT VERIFIED | Full pinned SDK checkout/hash verification, Windows compiler/ABI validation, shader generation, and production contract execution remain unperformed. |
| P1 | UNVERIFIED: frame identity | Draw-latched producer key fixes the observed counter error. Multiple/auxiliary families and game/render/RHI scheduling still need real frame/generation/source instrumentation. Fault streaks remain game-tick based. |
| P1 | UNVERIFIED: optics and pose | Source path retains primary HMD tracking, copies that processed camera to the secondary, and submits live runtime poses. OpenVR common frustum/bounds and PSVR2 cant still require a mathematical/runtime comparison against OpenXR. No headset-locked-output claim has been tested. |
| P1 | UNVERIFIED: shading and temporal history | Distinct states and constructor treatment are necessary source evidence only. They do not reproduce or certify every downstream Native Stereo Fix renderer transaction. Lumen/shadow/exposure equality is not proven. |
| P1 | UNVERIFIED: format/resizing | Dimension guards reject mismatches. Format changes can rebuild PSOs/output in `Compositor::prepare` on a retired live slot; no claim of zero hitches. Validate DLSS, ScreenPercentage, sRGB/HDR and reset paths. |
| P1 | UNVERIFIED: complete recovery | Source contracts cover startup/manual 6→5→6 and explicit failure cases, but GPU/device behavior and original OpenVR ID5 helper limits still need runtime and compatibility tests. |

These source fixes remove the specific blockers identified in the audit; they
do not establish release readiness. A routine compiler pass alone cannot
close the remaining GPU, startup, optics, shading, or headset validation.

## Checklist disposition

| Handoff area | Result |
|---|---|
| Exact source transformation | PASS-SOURCE; full SDK/build validation pending |
| No gaze and vertical control | PASS-SOURCE; persistence/headset test pending |
| Two same-camera views and frame keys | FAIL/PATCHED for counter error; runtime scheduling pending |
| Independent secondary construction | FAIL/PATCHED for restoration/publication; lighting parity pending |
| OpenVR family and submit | FAIL/PATCHED; optics/GPU/device tests pending |
| OpenXR success accounting | FAIL/PATCHED; acceptance now follows scene submission |
| Fault concurrency | FAIL/PATCHED for atomic interleavings; tick/frame attribution pending |
| Resource retirement and startup | SOURCE PATCHED; runtime/WARP/device-loss and early-allocation behavior unverified |
| Original mode/game isolation | Source fixes gated to DuoView; original compatibility suite unrun |
| Eye-tracking historical regressions | NOT APPLICABLE; not reintroduced or used as current acceptance tests |

## Next work, still without automatic build authorization

1. After separate build authorization: clean pinned source checkout, full
   baseline/SDK verification, normal Stage1/Stage234 application without
   `--source-only`, full verifier, Windows compiler, production contracts,
   WARP and original Joey compatibility tests, final source hashes.
2. Test PSVR2 OpenXR and OpenVR separately: startup from saved ID5, manual
   6→5→6, fixed ROI during eye movement, real head translation/rotation,
   source order 0/1, vertical offset, Lumen/shadow comparison, high resolution,
   DLSS/resizes, rejected submits, GPU error/reset and level changes. Observe
   allocations before the first hooked Draw and confirm deferred Draw lets
   framework/runtime initialization progress.
3. Compare 30-minute frame pacing against the untouched Build 3 Mono control.
   No claim of equal performance or release readiness before these results.

Source-only reproduction:

```text
python duoview/joey_stage1/apply_stage1.py BACKEND FRONTEND EVIDENCE
python duoview/joey_stage1/apply_stage234.py BACKEND FRONTEND duoview --source-only
python duoview/joey_stage1/verify_stage234.py BACKEND FRONTEND EVIDENCE --source-only
python duoview/joey_stage1/verify_source_review.py BACKEND
```

Use pristine exact backend/frontend pins. This produces review source only,
not a complete build input package. Do not reuse its omitted shader header as
evidence of a successful production verification.
