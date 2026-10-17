# QuadView same-eye Native Pairs — P0 feasibility
Date: 2026-10-17
Status: BLOCKED FOR UEVR INJECTION. Portable frame contract exists; no UE backend QuadView render / DLL has been made.
Source baseline: liviutrn/OpenNR experiments/duoview-joey-v22-astra-source-audit @ f34788699ff5724fd8ccb95d7ef2b559c1caf645.
Joey backend @ 5ac7edc207866569334175e4ed8a7517971547f6.
Restricted Joey UESDK @ 3cffbc82429b6165ceec2714f0f0d9ae48f55596 (no private source committed).
Matching frontend @ 60be4b0f9a646109fd9fdf448bacd41477234091.

## Verified observations

- Joey NativeFix is gated to NATIVE_STEREO and not AFR in VR.hpp. Activating its existing global path from new mode ID7 would route to ID0 texture lifecycle, so do not do that.
- Native Fix uses scoped secondary-as-primary construction, separate singleton renderer calls and fragile frame-count mutation, not simply metadata labels. STALKER2 Same Stereo Pass logic is game-specific.
- Remleo FFakeStereoRenderingHook.cpp around 2467-2548 issues an additional FViewport::Draw in synchronized mode and skips the next tick/draw. This proves an existing scheduler pattern, NOT independent second UE family histories.
- Pinned restricted SDK FSceneView.hpp supplies accessors to an engine-provided InitOptions view-state pointer, stereo pass and family. FSceneViewFamily.hpp supplies access to existing family views, scene and render target. Neither supplies an authorized constructor/lifetime API for two independent same-eye families or four distinct persistent FSceneViewStates.
- The historical v22 Windows run 38970778329 failed stage10_state_tests.cpp because fixture called consume() without providing the newer mandatory distinct nonzero scene states and verified secondary-shading signal. Test fixture has been fixed in this isolated branch; core production guard is intentionally unchanged.
- Prior v22 transformer applies changes to an exact pinned external Joey checkout during Windows CI; editing OpenNR alone does not patch a playable UEVR backend.

## Decision

**NO GO for a headset candidate until the following are demonstrated through actual target engine and pinned SDK:**
1. A separate UE-owned FSceneViewFamily with two same-eye view constructions on the second viewport Draw, without mutating gameplay/simulation twice.
2. Four persistent and distinct engine-owned FSceneViewStateInterface histories; merely seeing four pointers during a frame is not enough. Capture stable identities across frame N and N+1.
3. Frozen XR frame pose and tick across both draws, without stale projection, DLSS/TAA jitter, Lumen temporal history, frame-count decrement or reentrancy problems.
4. Four singleton Primary-equivalent NativeFix scene render transactions with private targets, proper GPU fencing and no first-pair texture overwrite.
5. Per-eye asymmetric PSVR2 runtime FOV, separate L/R physical eye poses, OpenXR/OpenVR output and GPU resource lifecycle.
6. Proven safe startup high-resolution allocation, no hidden ID0 bootstrap, and real ID5 fault transition.
7. Real Windows full backend build, HLSL/WARP, target DX12 STALKER2 injection and 6DoF/Lumen headset measurements.

## Implemented in this branch

- Portable fail-closed QuadPairLedger: immutable frame identity, exact same-eye role source validation, distinct UE-family IDs, distinct view-state and target IDs, actual per-eye frusta and camera pose checks, four-source readiness, two-eye submission acknowledgments.
- Negative tests for swapped eye pose, duplicate histories, duplicate targets, wrong dimensions, missing native-fix completion, reused family, wrong draw order, stale producer and false XR success.
- Isolated cross-platform CI build for the portable module only.
- Stage10 v22 test fixture repair without weakening DuoView safety check.

## What this does NOT implement

No game mode ID7, no new FViewport::Draw hook, no engine view allocation, no primary-equivalent Lumen renderer, no D3D12 compositor, no OpenVR/OpenXR runtime glue. The ledger flags depend on trusted instrumentation and do NOT establish those engine/runtime facts. The produced Windows EXE, if CI passes, is a standalone **test binary**, not a UEVR/PSVR2 build.

## Path to implementation

First implement a NO-PRESENT read-only P0 probe at the verified game viewport Draw / scene-view constructor / family render hooks in a new isolated Joey transformer. Log per-tick phase, immutable XR key, family/view/viewstate/scene/RT identities and renderer singleton outcomes over several frames (without submitting new XR frames). Do not install a second Draw unless reentrancy and protected source lifecycle can be proved. Only after distinct persistent histories are confirmed should an isolated ID7 compositor be implemented. Do not reuse ID6 Mono camera assumption.

Source review here is static; there is no user headset runtime proof.


## Follow-up source audit and committed coordinator (17 October 2026)

The two existing techniques **should cooperate at an explicit scheduler boundary**, not by enabling NativeStereo ID0 and SyncedSequential ID1 simultaneously. One logical QuadView method should own the two Draw phases, immutable left/right pose snapshot, four source roles, timing and GPU identities. Each UE native-style pair stays independent.

Source proof from pinned Joey \`src/mods/vr/FFakeStereoRenderingHook.cpp\`:
- At lines 20695+ the game-viewport Draw hook runs; at 20929–20950 the runtime frame and HMD state can be updated before original Draw.
- At lines 20957–21054 synchronized sequential mode installs the FViewport::Draw hook and enqueues a second Draw guarded by original viewport, lifecycle generation, method and vtable. It is **not** an immediate safe second Draw; its own comment describes the **start of the next engine tick before the world ticks again**. Frame identity and input/pose updates need instrumented proof before reuse.
- At 22614+ the real FSceneView constructor intercepts engine-created InitOptions. At 23191–23275 NativeStereoFix temporarily adapts a SECONDARY constructor to PRIMARY when a valid capture target exists, restoring original state. That is **not** a four-history allocator.
- At 25233–25309 native singleton rendering validates an actual two-view family, current-frame metadata, distinct views, render target and states. It cannot be reused for a second pair without new producer generations and independent backing textures.
- At 12315–12399 the ghosting owner resolver **reads existing LocalPlayer ViewState reference slots**, rather than manufacturing or owning persistent states. It does not establish four independent LF/LP/RF/RP owners.

Pinned UESDK \`src/sdk/FSceneView.hpp\` supports get/set scene_state, view_family and stereo_pass on existing InitOptions. \`src/sdk/FSceneViewFamily.hpp\` can validate existing views/targets, but exposes no safe documented allocator for additional persistent FSceneViewStates. Therefore this **remains a P0 NO-GO for a playable binary** until a true engine-created 4-role history lifecycle has been demonstrated in STALKER2. A second Draw alone does not close the barrier.

New portable source:
- \`quadview/QuadPairCoordinator.hpp\`: left-then-right game-thread phase tokens; key/world advance/scene coherence; non-reentrancy; same physical-eye pose per pair; correct per-eye projection/target sizes; four distinct views/histories/capture identities; history stability across logical frames; explicit generation reset.
- \`quadview/tests/QuadPairCoordinatorTests.cpp\`: positive and negative cases for wrong-eye pose, second phase before first, duplicate/recursive draw, mismatched simulation tick, shared states, stale XR frame, scene replacement, cross-thread entry, and history drift.
- \`quadview/QuadPairLedger.hpp\`: remains separate; phase proof does not imply GPU producer completion, compositor success or OpenXR/OpenVR ACK. All three must be validated independently at integration time.

Native headset mode ID7, actual UE draw hook changes, scene allocator integration, four real producer captures, D3D12 compositor and XR presentation are **not yet implemented**. Existing Build3 / modes ID0, ID1, ID5, ID6 are preserved. A successful portable C++ CI run does not qualify as a full backend UEVR DLL.
