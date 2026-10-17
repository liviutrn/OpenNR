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
