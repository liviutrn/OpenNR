# DuoView / QuadView clean restart

Date: 2026-10-17
Repository: liviutrn/OpenNR
Restart branch: experiments/duoview-quadview-clean-restart-20261017
Source base: v22 Build 29, bd8024c9e83debaaee6890d36c756f186e8421e1

## Decision

Use the earlier v22 Build 29 source as the DuoView anchor and keep its behavior as the control. Do not carry forward the Oct 17 v22 repair branch or the Remleo fixed-sequential prototype. Keep QuadView as a separate experimental mode, so a QuadView failure cannot destabilize the known DuoView path or the original modes.

The user reports the older v22/v23 builds were functional. Earlier engineering notes record gaze tremble in v22 Build 29 and no headset result for v23 Build 32; the user's current report takes precedence for actual headset behavior. The exact tested artifact is still not uniquely identified, so preserve the known build artifacts and hashes rather than relabeling a newer recovery as the known-working baseline.

## Exact references

- v22 Build 29 source: bd8024c9e83debaaee6890d36c756f186e8421e1
- Build 29 Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38557341481
- Build 29 injector artifact: https://github.com/liviutrn/OpenNR/actions/runs/38557341481/artifacts/11891093120
- v23 Build 32 source: 8d13ad8f6cc49bc0ebdb4ea3373c37f1298bac32
- Build 32 Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38565044386
- Build 32 injector artifact: https://github.com/liviutrn/OpenNR/actions/runs/38565044386/artifacts/11896096623
- Protected Joey Build 3 Mono control: run 38453012351; user tested Mono ID5 for 30 minutes without hitches.
- Pinned Joey backend: joeyhodge/UEVR at 5ac7edc207866569334175e4ed8a7517971547f6
- Pinned authorized Joey UESDK: joeyhodge/UESDK at 3cffbc82429b6165ceec2714f0f0d9ae48f55596
- Pinned matching frontend: joeyhodge/uevr-frontend at 60be4b0f9a646109fd9fdf448bacd41477234091

Build 32 adds temporal gaze filtering and camera-dependent gaze UV caching. Keep that as a comparison, not as an implicit prerequisite for the new QuadView path.

The Oct 17 recovery branch is not the anchor: it is 59 commits beyond the v22 Build 29 base and changed 16 files. Its latest repaired v22 artifact crashed in the user's headset. The separate Remleo fixed-sequential experiment also lost head tracking and did not establish foveation.

## Product behavior to preserve

- DuoView remains the existing two-view monoscopic mode: one foveal view plus one peripheral view composed into one image for both eyes.
- QuadView is four real source renders, with two same-eye Native Stereo pairs:
  - Left family: primary LF = left-eye fovea; secondary LP = left-eye periphery.
  - Right family: primary RF = right-eye fovea; secondary RP = right-eye periphery.
- The two views in each pair use the same physical-eye pose and that eye's asymmetric PSVR2 frustum. The left and right families use their own eye pose and frustum.
- Secondary/peripheral shading must follow the established Native Stereo Fix behavior. Constructor relabeling alone is not proof of parity.
- One logical game frame advances simulation once. Both families must use one immutable XR frame snapshot; do not assume the existing sequential redraw has same-frame semantics until instrumented.
- All four histories must be distinct, engine-owned, and persist across frames. Four pointers in one frame are insufficient.
- Do not silently enter Native Stereo ID0 at high render resolution on error. A clean pre-submit failure may route to the existing Mono ID5 control at a frame boundary. Never change mode halfway through rendering or while XR resources are locked.

## Less-invasive implementation boundary

A plugin-only implementation is not sufficient for real QuadView. The public plugin callbacks cover engine ticks, viewport draw, stereo view offsets, and post-render framework work; they do not expose a supported way to create additional FSceneViews, view families, or persistent engine-owned histories. Use a small core adapter at the existing view-scheduling and composition boundaries, with the QuadView policy, frame records, tests, and diagnostics isolated in a dedicated module.

Keep production edits behind one mode gate. Limit the backend patch to mode registration, one render-scheduler seam, per-role view setup, and final per-eye composition/submission. Keep configuration UI and diagnostics separate where the public plugin API supports them. Preserve original Mono ID5, Native Stereo ID0, existing Native Stereo Fix behavior, and DuoView ID6.

Do not modify raw ViewState memory, copy FSceneView/FSceneViewStateReference objects, guess refcounts, reuse the two ordinary eye histories for four roles, add global Lumen/TSR CVars, or add per-frame GPU waits. Do not duplicate gameplay ticks or submit partial/stale eyes.

## Implementation stages and stop conditions

### 1. Freeze the DuoView control

Build from this branch's pinned v22 source and confirm the baseline package and source identity. Make no QuadView production changes in this step. Keep Build 3 and Build 29 available as controls.

### 2. Instrument the pinned engine path without changing output

Add a strictly opt-in read-only probe for STALKER 2 DX12. Record viewport draw phase, logical engine frame, XR frame key, physical eye, family/view/target identities, view-state identity, stereo pass, renderer call, and thread. Do not add a second draw, allocate resources, alter camera/projection, or submit new XR frames.

Run the probe in Native Stereo with Native Stereo Fix and in Synchronized Sequential. Confirm the observed scheduler and history ownership over multiple frames, tracker resets, scene changes, and mode transitions. Treat logs as measurements, not as proof of four-view output.

### 3. Prove a legitimate four-history creation route

Identify a supported, callable engine-owned allocation and destruction path for STALKER 2's pinned UE version. Unreal's renderer allocator is a possible research lead, but the pinned SDK currently exposes no validated callable ABI or factory for four persistent view states.

If the engine-owned route cannot be demonstrated, stop QuadView implementation at this gate. Do not manufacture or alias states to make the contract tests pass.

### 4. Add the QuadView scheduler behind a separate mode gate

Only after stages 2–3 pass, add a scheduler that creates the two real same-eye families under one logical frame snapshot and one game update. Keep four role histories and four capture targets distinct. Validate actual renderer calls and Native Stereo Fix completion for all four roles.

### 5. Compose and submit

Add a per-eye compositor that combines each high-resolution primary with its matching low-resolution secondary. Require all four current-frame captures, producer completion, fence retirement, resource validity, and both final eye images before submitting. On a clean pre-submit failure, use the explicit Mono ID5 policy; never silently select ID0.

### 6. Release gate

Before a headset ZIP is called testable, require exact source/SDK/frontend pins, Windows backend and frontend builds, original compatibility tests, production contract tests, shader compilation, DX12 WARP/debug-layer tests, source-hash checks, archive inspection, and both-eye/frame-lifecycle checks.

A green portable test or successful DLL build is not headset proof. The first QuadView headset package must include runtime diagnostics that distinguish missing activation, missing view roles, shared histories, skipped captures, and rejected XR submission.

## Current status

- The clean branch exists at the v22 Build 29 source commit.
- This document records the restart direction and gates.
- No QuadView production renderer is claimed or included in this branch yet.
- Next source task: implement the read-only probe on this branch and confirm it does not modify the delivered DuoView behavior.
