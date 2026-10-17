# Joey QuadView Native Pairs — P1 engineering checkpoint
Date: 2026-10-17
Repository: https://github.com/liviutrn/OpenNR
Branch: experiments/joey-quadview-nativepairs-p0-20261017
Status: FOUR-SOURCE RENDERER **NOT IMPLEMENTED**. Portable contracts and a passive,
opt-in, source-level diagnostic probe exist. Do not ship as functional ID7.

## Fixed physical-eye roles
LEFT native-style family: UE PRIMARY LF high-res fovea and UE SECONDARY LP
low-res periphery, BOTH LEFT physical eye pose and per-eye asymmetric frustum.
RIGHT native-style family: UE PRIMARY RF high-res fovea and SECONDARY RP
low-res periphery, BOTH RIGHT physical eye. There are two legitimate Unreal
families and four persistent, non-aliased temporal histories, not one 4-view
family. One logical game frame, normal two-eye OpenXR/OpenVR submission.

## Completed implementation source
* quadview/QuadPairLedger.hpp (previous): stable crop/pose/view-role geometry
  and two-eye XR acceptance contracts.
* quadview/QuadPairCoordinator.hpp (previous): game-thread left->right
  synchronous two-draw phase tokens with one immutable logical frame key.
* quadview/FourHistoryLease.hpp (new): independently validated source-owned
  reference identities; four distinct histories, stable through subsequent
  logical frames, exact queue and source/compositor fence retirement.
  **Validation of supplied identities does not allocate engine ViewStates.**
* quadview/p1_probe/apply_read_only_probe.py (new): strict source transformer
  applied AFTER pinned Joey Stage1+Stage234. STALKER2 DX12 only and opted into
  with UEVR_QUAD_P1_PROBE=1. Logs original UGameViewportClient draw lifetime,
  original engine frame, physical FSceneView source pointer, family, borrowed
  state pointer and original stereo pass. No extra draws, camera changes,
  DirectX target mutation, history allocation or XR submission changes.
  Checks and records exact before/after hashes, original newline format and
  reversible byte-exact source delta; verifies all other transformed backend
  paths and matching frontend still match Stage234's source manifest.
* quadview/p1_probe/audit_log.py (new): offline read-only log analysis,
  conservative four-distinct-state observations, draw frame continuity and
  alias checks. An output candidate does NOT prove two physical eye poses,
  four persistent owners, world simulation equality or separate renderers.
* Tests: FourHistoryLeaseTests.cpp, test_read_only_probe.py, test_audit_log.py,
  QuadPairCoordinatorTests.cpp, QuadPairLedgerTests.cpp, fixed DuoView
  stage10_state_tests.cpp. Stage10 preserves existing negative source-state
  tests and explicitly enables Release assertions.

## Exact fixed source
Joey backend: joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6.
Restricted Epic-authorized private SDK unchanged:
joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596.
Frontend: joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091.
Never redistribute private SDK files.

## ABI and engine owner investigation
Unreal Engine declares FSceneViewStateReference::Allocate(feature level),
Destroy and GetReference in Engine/Public/SceneTypes.h.
IRendererModule::AllocateViewState is officially responsible for allocating
the private engine-owned view-history implementation. This is an architectural
route to four authentic states (not memcpy), but the pinned UESDK does not
expose a verified callable STALKER2 GetRendererModule/AllocateViewState ABI,
feature-level contract or FSceneViewStateReference factory and destructor.
The Joey ghosting owner resolver at original FFakeStereoRenderingHook.cpp
lines ~12315–12399 reads existing two LocalPlayer reference slots; it does not
construct a new set. Source annotations do not solve that problem.

Direct documentation:
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/FSceneViewStateReference
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/RenderCore/IRendererModule/AllocateViewState

Existing Joey synchronized draw scheduling around original hook lines
~20957-21054 queues a redraw at the next tick boundary while trying not to
advance the game. Native Stereo Fix renderer source around ~23191-23275 and
~25233-25309 validates source pass, singleton view family and target.
Neither alone produces four persistent independent histories.

## Dedicated GitHub Actions
Portable C++ Windows and Linux CI:
https://github.com/liviutrn/OpenNR/actions/workflows/quadview-nativepairs-p0.yml
Pinned Joey Windows SDK/frontend baseline readiness (evidence only):
https://github.com/liviutrn/OpenNR/actions/runs/39031901742
Pinned Windows read-only probe integration (evidence only):
https://github.com/liviutrn/OpenNR/actions/runs/39032267356

Jobs may still be running when this handoff was committed. Inspect their
*actual final* run and step conclusions. A past source-only P0 run succeeded
on Windows and Linux; do not imply the full UEVR backend DLL was produced.
No artifact from these jobs is a playable QuadView ID7 headset build.

## Next required gates, in order
1. Confirm the Windows source probe compiled and its reversible pinned hashes
   match after backend+frontend tests. If not, fix the exact compiler line.
2. Run the passive probe on native stereo and synchronized sequential modes
   in STALKER2 to record existing state ownership, renderer family identities,
   tick behavior and source pass mapping; parse with audit_log.py.
3. Locate and validate a legitimate four-owner history creation route. Safely
   call engine-supported allocator with validated ABI and lifecycle; do not
   copy FSceneViewStateReference / FSceneView, hack refcounts or allocate fake
   ViewStates. Prove across 2+ frames and scene transitions.
4. Integrate one guarded same-logical-frame left->right scheduler, each Draw
   producing a real engine-created 2-view family and correct same-eye camera.
   Confirm no double gameplay tick and no hidden cross-eye projection.
5. Implement separate native-fix-grade renderer singleton and four GPU source
   captures with strict producer lifetime, then per-eye composite & two-eye
   OpenXR/OpenVR submission. Use the exact source/target frame lease gates.
6. Compile full pinned Windows backend/front end, HLSL, WARP and compatibility
   suite; package a headset test build ONLY when all relevant gates pass.
7. On runtime failure use real Joey Mono ID5 as the deliberate fallback,
   never automatic NativeStereo ID0 at high resolution; preserve Build3 and ID6.

IMPORTANT: Probe/portable tests cannot substantiate image quality,
Lumen/shading parity, true headset stereo, 6DoF or frame-time improvements.


## Additional STALKER2 UE5.5 owner bootstrap finding

Pinned Joey's \`stalker2_uses_lazy_synced_viewstates()\` (original
\`FFakeStereoRenderingHook.cpp\` ~5738) is a game-build/mode-specific guard.
At ~31345 and ~31370-31377 the backend explicitly **skips**
\`ULocalPlayer::PostInitProperties\` replay in STALKER2 Synced mode, with
a comment that Native/Native Fix must retain their own bootstrap. Thus
forcing PostInitProperties twice to create the second Quad pair would
reintroduce a known game-specific hazard; it is not the proposed factory.

An alternate **investigation only** is to have Unreal legitimately allocate
four \`FSceneViewStateReference\` owners through its normal feature-level-aware
allocation API and map two per draw. Never append raw bytes to the protected
\`ULocalPlayer::ViewStates\` TArray, call unvalidated virtual slots or assume
that a transient four-view bootstrap is safe. Its exact STALKER2 ABI, feature
level, constructor/destructor and owner replacement remain UNPROVEN.


## Windows CI backend compile correction (later on 17 October)

Pinned Joey foundation run 39031901742 passed Stage234 source identity, 3
production contracts, 6 DuoView independent tests and all 41 original Joey
compatibility tests, then MSVC C2039 failed in transformed
\`src/mods/VR.cpp\` lines 17865 and 17906: two calls to
\`runtime->error.empty()\`. Joey declares runtime \`error\` as
\`std::optional<std::string>\`, not \`std::string\`. The historical source
itself checks \`if (runtime->error)\`. Root cause was the
\`apply_stage234.py\` startup gate code; correction **replaces both** with
\`runtime && runtime->error.has_value()\`, so any engaged runtime error closes
the startup gate. Patch commit 945ce8294fc0cb99a8ce31abe1615b5b676561aa;
source verifier added explicit two-guard ABI check in commit
dcc17fd35cd6c310de2bda30d8a28ca2bd3beaa7. Portable regression
\`quadview/p1_probe/test_vr_optional.py\` and CI now check both sites.

Rerun foundation Windows full C++/C#/WARP:
https://github.com/liviutrn/OpenNR/actions/runs/39033345486
Read-only instrumented Windows backend:
https://github.com/liviutrn/OpenNR/actions/runs/39033348248

These builds **were not yet certified successful when this note was made**.
Inspect their final outcome and logs; do not confuse compilation in progress
with a functional UEVR headset plugin.

## Engine-owned four histories: GetDesiredNumberOfViews clarification
The source-backed Joey \`get_desired_number_of_views_hook\` (original
\`FFakeStereoRenderingHook.cpp\` ~30831-30911) **returns 2 when
inside_post_init_properties is true**. The UE4.25/4.26 branch documented
around lines ~9223-9226 allocates LocalPlayer ViewStates from that method.
That behavior does not establish a callable 4-state allocator for STALKER2
UE5.5; it is another reason NOT to fake a four-history LocalPlayer array.
STALKER2 Synced intentionally avoids PostInitProperties replay to prevent
resetting game delegates/objects (~31345 and ~31372).

The passive probe in P1 is a diagnostic prerequisite, not an implementation
of four real histories or a releasable new rendering mode.


## Continuation checkpoint: verified pinned Windows probe and distributable diagnostic workflow

Status checked 17 October 2026 after earlier P1 handoff.
- Windows pinned foundation run 39033345486: **SUCCESS**.
- Windows read-only probe run 39033348248: **SUCCESS**. Evidence artifact
  `QuadView-P1-READONLY-PROBE-WIN64-Evidence-2`, ID 12101337369.
- Checked Windows probe job 117398447377: compiled
  `backend/build/bin/uevr/UEVRBackend.dll` and passed all 41 original
  compatibility tests, frontend rendering-ID tests and reversible source hashes.
- Earlier run 39031901742 failed MSVC C2039 on invalid optional.empty()
  in Stage234 VR.cpp generated code; newer commit 945ce829 corrected both,
  verifier dcc17fd checks their ABI, and both newer runs passed.
- Work resumed with commit `9272b0a4c3a24ed6a4326802b4d9e0d80e3cce31`
  adding **diagnostic-only** binary packaging to
  `.github/workflows/quadview-p1-probe-ci.yml`. The workflow is push-triggered
  by edits to that workflow on this branch. Check the NEW run's actual final
  result and downloadable artifact; do not infer it passed from the prior jobs.
  Package contains compiled backend/auxiliary DLLs, matching frontend, probe
  and SHA-256 digest if its packaging checks succeed.

HARD STOP: No QuadView ID7 implementation exists yet. This downloadable
diagnostic (if CI completes) is **not** a working four-source QuadView build.
The high-risk missing layer remains safe UE5.5/STALKER2 creation/ownership of
four non-aliased temporal states, then two same-eye native-style view families,
phase scheduler, four producer render targets, compositor and XR submission.

Most actionable next evidence: with `UEVR_QUAD_P1_PROBE=1`, capture UEVR
`[QuadP1]` logs from STALKER2 DX12 in separately selected NativeStereo+Fix
and SyncedSequential sessions. Run `quadview/p1_probe/audit_log.py` against
the logs and verify 2+ logical-frame stability before claiming four owners.
Do not copy engine-owned states or write beyond LocalPlayer TArray capacity.
Do not overwrite known-good Joey Build3. Mono ID5 is the allowed fallback,
not NativeStereo ID0.
