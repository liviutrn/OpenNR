# Joey QuadView Native Pairs — P2 continuation checkpoint
Date: 2026-10-17. Repo: `liviutrn/OpenNR`.
Branch: `experiments/joey-quadview-nativepairs-p0-20261017`.

## Exact status — no false claims
**NOT a working QuadView ID7 renderer or headset build.** The pinned Joey
UEVR+Stage234+P1 read-only probe *does* build on Windows (run 39033348248),
but ID7 is not integrated with the Unreal runtime. Do not repurpose the
portable test EXE or diagnostic UEVR DLL as proof of four-eye-source rendering.

The original game-facing integration still has no verified safe route to
four independently allocated STALKER2 UE5.5 FSceneViewStateReference owners.
The private authorized Joey UESDK exposes borrowed existing InitOptions
scene_state and FSceneViewFamily views, NOT the needed constructor/destructor
ABI. Never memcpy a ViewState, assume private Unreal layout, overwrite a
ULocalPlayer ViewStates TArray, call unknown vtable slots, or replay
PostInitProperties on STALKER2 as a shortcut.

## Concrete new source committed today
* `quadview/NativePairHistoryOwner.hpp` — callback-driven four-role
  *engine-owned* allocation/verification contract. Roles LF,LP,RF,RP.
  The implementation can only operate when a verified engine-side
  acquire/inspect/destroy API is supplied; it **does not invent** one.
  It guarantees same owner-thread access, distinct reference slots/states,
  stable identities across multiple frames, monotonic XR/game frame keys,
  same D3D12 queue, monotonically increasing GPU consumer fences,
  explicit teardown, quarantine of stale/aliased owners and no
  premature release on ordinary frame completion. It deliberately
  never frees unknown engine-owned memory in a C++ destructor.
* `quadview/tests/NativePairHistoryOwnerTests.cpp` — independent negative and
  positive contract tests for aliasing, stale owner, startup rollback,
  wrong thread, nonmonotonic frame, fence reuse, queue migration, continuing
  histories across frames, and safe final retirement.
* `quadview/QuadStereoComposite.hlsl` — a real isolated ps_5_0 full-eye
  stereo composite shader: four input textures, same physical-eye
  fovea/periphery only, correct crop UV reconstruction, user vertical crop
  support, feather, bounded sampling and invalid eye-index rejection.
  It has **not** been bound to live producer textures or XR swapchains.
* `quadview/QuadStereoCompositeCPU.hpp` plus
  `quadview/tests/QuadStereoCompositeTests.cpp` — CPU reference math and
  negative/positive crop tests.
* `quadview/compile_compositor.py` — Windows SDK fxc.exe offline DXBC PS5.0
  compile gate. No runtime shader compilation.
* `quadview/CMakeLists.txt` updated with the new C++ tests.
* `.github/workflows/quadview-nativepairs-p0.yml` builds portable
  contracts on Windows Server 2022 and Ubuntu 24.04, verifies source probe,
  and compiles the HLSL shader on Windows; it publishes exact per-commit
  status checks to GitHub.

### Verified CI
Portable + offline FXC test run
https://github.com/liviutrn/OpenNR/actions/runs/39043526379
returned **success for Windows AND Ubuntu**. Additional lifecycle/fence
regression changes were committed after that run; check their new
per-commit CI statuses before claiming validation of the latest HEAD.

Pinned original UEVR Windows build + P1 observer:
https://github.com/liviutrn/OpenNR/actions/runs/39033348248
returned success; it is NOT a QuadView ID7 headset renderer.

Diagnostic Windows package workflow
`.github/workflows/quadview-p1-probe-ci.yml` was modified to upload a
read-only P1 frontend/backend zip when all tests succeed, and to report
the exact build commit status. Verify the actual result/artifact;
a status not yet returned means unverified.

## Missing game-facing implementation — do in this order
1. Run P1 in **STALKER2 DX12**, separately with Joey NativeStereo+Fix and
   SyncedSequential; collect [QuadP1] logs. Confirm actual GetDesiredNumberOfViews
   call context, FSceneView pass/family/scene-state mapping, original world
   tick and original engine-owned four-owner viability. The parser produces
   *candidates*, not proof of four persistent histories.
2. Find an actual engine-supported allocator and disposal route matching
   STALKER2 feature level and lifecycle. Verify with P1 source evidence and
   engine documentation. FSceneViewStateReference::Allocate(FeatureLevel),
   GetReference and Destroy exist in Unreal, but their *callable ABI/owner*
   for this injected game remains unresolved. Only then bind the verified
   callbacks to NativePairHistoryOwner.
3. Implement ID7 as a single guarded renderer method with two UE
   2-view families in a frozen logical game frame: LF/LP same LEFT pose
   and asymmetric projection, RF/RP same RIGHT pose and projection.
   Phase 2 must not advance gameplay simulation or XR input twice.
4. Implement NativeStereoFix-grade independent renderer singleton for
   each pair; persist four UE histories; capture FOUR D3D12 source textures
   without overwrite or wrong-eye reuse. Validate source generations,
   GPU state transitions, exact queue ordering, producer and consumer fences.
5. Bind the already-authored ps_5_0 composer to the exact four SRVs,
   choose PhysicalEye 0/1 per XR swapchain projection eye; preserve
   correct per-eye PSVR2 asymmetric frustum and 6DoF. Submit ONLY TWO
   XR projection views through OpenXR or OpenVR after real GPU completion.
6. Set mode ID7 only when complete. If prerequisites fail use real Joey
   Mono ID5 after safe frame retirement; never auto-fallback to Native
   Stereo ID0 at high resolution or falsely mark an invalid four-view
   atlas as complete.
7. Compile complete pinned Joey+authorized UESDK backend/frontend and
   verify STALKER2 headset before treating a binary as functional.
   Protect the user's 30-minute-stable Joey Build 3 in a separate directory.

## Ownership and ABI references
Official UE API:
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/FSceneViewStateReference
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/ULocalPlayer?application_version=5.5

NOTE: No private SDK source redistributed; no speculative engine memory patch
was made. This checkpoint is meant to be recoverable and honest.


## Historical Praydog QuadView branch discovered and audited

Public historical implementation: `praydog/UEVR`, branch `quad-views`
at commit `8acc274fabc12a2a86e004e5ae1a247d32e6d7d0` (2023-12-13).
The immediately preceding "Quad view test stuff" commit
`46e9c98d5284f3be2784e4b5d1f1ad927c7225ea` contains the important
prototype, not just the last view-rectangle arithmetic fix:
https://github.com/praydog/UEVR/commit/46e9c98d5284f3be2784e4b5d1f1ad927c7225ea

It changed the `GetDesiredNumberOfViews` hook from 2 to **4**, including
`inside_post_init_properties`. The official Unreal
`IStereoRendering::GetDesiredNumberOfViews` contract explicitly exists
to let XR devices allocate additional view states:
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/IStereoRendering/GetDesiredNumberOfViews

It also expanded runtime projection storage to 4, remapped view indices
with %4, tried narrow projections and a four-region atlas. Importantly,
this was an **early 2023 experimental single four-view path**, not two
verified independently shaded same-eye NativeStereo pairs. It has neither
demonstrated compatibility with STALKER2 UE5.5, Lumen parity nor safe
same-tick two-family temporal ownership. Its view rectangle was later
fixed in commit `8acc274`; the prototype was not merged as production.

Next technical investigation: check the existing P1 `[QuadP1] desired`
events from REAL STALKER2 injection to establish whether
`GetDesiredNumberOfViews` is called during natural ULocalPlayer owner
allocation, after initialization, or during a synthetic PostInit replay.
**Do not blindly port the historical return-4 patch:** STALKER2 Synced
intentionally skips PostInitProperties replay, because replay can
reset/duplicate game objects/delegates; changing a return after native
allocation may leave 2 owned states even when 4 were requested. Engine
source/history owner evidence across >=2 frames is required first.

If UE5.5 safely allocates 4 at original owner initialization, this might
remove the need to resolve the private FSceneViewStateReference ABI manually,
but getting two independent UE families and four source captures still
requires additional actual renderer work.
