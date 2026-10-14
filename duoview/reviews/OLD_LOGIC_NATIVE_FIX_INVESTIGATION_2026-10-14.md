# DuoView investigation: old visual logic and Native Stereo Fix
Date: 2026-10-14. Investigation checkpoint; no runtime patch or new binary produced.

## Outcome and user's clarified target
Restore good shading in both DuoView sources while preserving the exact Joey backend's observed smoothness. User wants UE view 0 for the fovea and UE view 1 for the periphery. User clarified that the both-eyes-good Native Stereo Fix observation was in **Native Stereo ID0**, not ID6. It is evidence that Joey has a render path capable of good shading in both eyes, not evidence that the fix works inside DuoView.

The first candidate should restore the old DuoView integration behavior on exact Joey, starting with primary fovea / secondary periphery. Do not revert the whole old backend or activate the complete Native Stereo Fix inside ID6. If old ordering remains inadequate, investigate independently shaded view construction and renderer transactions as a separate step with measured overhead.

## Exact independently inspected sources
- OpenNR current quality branch HEAD: 655c211771be5fa093896795024a211ba82e1d73.
- Compiled v20 Build24: a68371d7777845986542782419198995bbf53a49; run 38536358929. Independently queried run and job/step metadata: completed/success; production tests, independent WARP tests, compatibility suite, backend, frontend and packaging all succeeded. Test counts of 3+6+41 are inherited from the handoff; this checkpoint did not download/recount the Windows test logs.
- Headset-proven smooth Build19: ce9c9abc67ec0dafa48634ae7a3a443377616de5.
- Historical reference: bd74b21f46aa51c6d535680a005682e2572d6965 (Injector-5), not an assumed favorite v14 binary.
- Exact Joey backend checked out read-only: joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6.
- Exact old backend checked out read-only: praydog/UEVR@4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d.
- Original Joey Build3 is unchanged. No SDK source was replaced, downloaded or bundled for this investigation.

The uploaded “complete” ZIP contains two documentation files, not source or executables. Actual comparison therefore used repository source and exact backend commits.

## Confirmed differences and their significance
| Area | Old Injector-5 | New Build19 / v20 | Consequence |
|---|---|---|---|
| Default engine role | Fovea UE0 (primary), periphery UE1 (secondary) | Fovea UE1, periphery UE0 by default | Strong candidate for upstream shading differences. v20 selector permits UE0, but default remains UE1. |
| Physical atlas | Fovea left at x=0; periphery x=foveal width | Build-time transformation puts periphery x=0 and fovea x=peripheral width | Choosing fovea UE0 in v20 changes engine role, **does not restore old atlas placement**. Treat engine role and atlas location as separate variables. |
| Gaze basis | Native ray -> OpenXR direction -> inverse left-eye optical rotation -> symmetric tangent UV | Native ray -> +Z Mono ray -> projection UV; left-eye optical rotation omitted | Potential alignment difference; actual PSVR2 optical orientation must be measured. No proof that it causes twitching. |
| Matrix timing | Calls runtime update_matrices before constructing frame, adjusts near plane | Reads cached Mono projection in producer snapshot | Inspect the projection freshness contract; don't blindly reintroduce runtime updates. |
| Settings | Source defaults .50 crop, 1.0 density, .20 peripheral scale | .30 crop, 2.5 density, .25 peripheral scale | Match effective dimensions before claiming quality parity/regression. Actual favored old settings unknown. |
| Runtime | Public Praydog backend + calibrated Mono patch + public SDK | Exact Joey backend and original SDK | Preserve Joey lifecycle and pins. Old hitches occurred even outside DuoView. |
| Compositor init | Runtime shader compilation | Offline DXBC and prewarming | Preserve new initialization approach. It does not prove the exact historical hitch cause. |

## Core old logic is already present
These Git blobs are identical between Injector-5 and Build19 **before build-time transformation**:
- DuoViewGeometry.hpp: 03dda01baee3a35b7a05d9d994598b89a167458f
- DuoViewConfig.hpp: fb3f9039f70e4fe56ec4dc01a2cef35bfcec1d53
- DuoViewState.hpp: 6ab0f911b85c545c783496c2c12ee878cd984133
- DuoViewFrame.hpp: ef619285c446a3251faf861fb199e362977d4394
- DuoViewComposite.hlsl: 872ae2f875675a610aa716bc6ae998ee388f8d11
- DuoViewCompositeRaster.hlsl: 0c1eb5e87a4a686bef67726a15c668a03c9fbc1b

v20 adds diagnostic branching and controls. Its main render integration lives in duoview/joey_stage1/apply_stage234.py. The final loop rewrites copied DuoViewGeometry.hpp to reverse atlas placement regardless of selected fovea source index. Raw header equality does not establish applied-source equality.

## Native Stereo Fix: what actually improves and why it cannot simply be enabled
Exact Joey VR.hpp::is_native_stereo_fix_enabled() requires method NATIVE_STEREO (ID0), apart from unrelated title-specific paths. Stage1 makes ID6 part of the Mono family without changing that requirement. VR::should_force_native_stereo_fix_same_pass() explicitly returns false for Mono.

In validated STALKER 2, Native Fix forces “Use Same Stereo Pass.” In FFakeStereoRenderingHook.cpp:
1. The FSceneView constructor path can relabel SECONDARY as PRIMARY when the owned capture generation is ready.
2. While constructing that view, it hides the existing family view list, then restores it.
3. BeginRenderViewFamily renders the proven first view in a singleton transaction on the original target.
4. It renders the second singleton into a separate generation-owned target.
5. It adjusts scene-frame identity and carries a validated native stereo packet to the compositor.

These are substantial construction, history/topology, target lifetime and submission changes. They are not a brightness filter. Admitting ID6 into the global Native Fix boolean would also activate incompatible rectangle, capture and submission behavior.

Old DuoView did **not** use Native Fix either:
- Injector-5 public_mono.patch adds an early false return when is_using_mono() is true.
- apply_public_duoview.py makes ID6 part of is_using_mono().
- Neither old nor new DuoView changes the engine pass lookup: index0 PRIMARY, index1 SECONDARY.
- No old DuoView-specific constructor relabel or singleton renderer was found.

Therefore, “restore old behavior” is a valid path, but “the old renderer already used Native Fix” would be false.

## Most plausible shading leads, ranked but not proven
1. **Engine primary/secondary role plus unequal view dimensions.** Old high-resolution primary fovea versus new low-resolution primary periphery is a meaningful topology change. Unreal officially distinguishes primary views and associates secondary views with a primary. Whether STALKER 2's Lumen/shadow/TSR code shares incompatible data here needs game/engine evidence; do not claim a specific Lumen resource-sharing bug is proven.
2. **Different scene-view/history behavior between pinned backends/SDKs.** Same camera and correct rectangles do not prove lighting/history parity. Current pair gating observes camera/rect/projection/family existence; it does not validate rendered GI, exposure, motion vectors or view-state independence.
3. **Unequal resolutions and moving crop.** Both can change screen-space lighting and temporal reconstruction. Default old/new settings are not controlled.
4. **Applied atlas placement / format / postprocessing.** Same source shader lowers the priority of a missing compositor effect, but does not rule out engine atlas processing or actual resource-format differences.

User's report that UE0 looks good and UE1 poorer is stronger evidence for an index-dependent issue than the earlier generic “periphery darker” report. Preserve this distinction.

## Gaze corrections to the earlier handoff
Old and new CAPI readers:
- Read nonblocking once per frozen frame.
- Reuse the last sample for at most 50 ms.
- Reject invalid combined direction or a blink in either eye.
- Return unavailable, causing State::begin to center the ROI, after expiration/invalid data.

There is no established newly introduced center-expiry policy. New counters are useful, but expiration alone cannot be called an old/new regression.

Joey get_eye_transform(0) returns runtime eyes[0]. OpenXR builds it from views[0].pose located in **view_space**; stage/head pose is located separately. The omitted rotation is a headset-relative optical transform, not a world-space head yaw/pitch transform. A fixed optical difference can create an alignment offset; it cannot by itself establish large head-motion-coupled twitching.

For symmetric projection and identity optical rotation, old ray_to_uv and new projection_uv are algebraically equivalent. Restoring a quaternion path by itself is not a stabilization algorithm. For a synthetic 3-degree optical yaw and tangent half-width 1.328981, the old correction shifts center UV by about .0197; 5 degrees gives .0329. These are mathematical fixtures, **not measured PSVR2 optical values**. Actual correction must use the real orientation and consistent basis signs.

## Minimal continuation candidate, after this investigation
1. Start a separate branch from exact quality baseline; keep Build3, Build19 and Build24 untouched.
2. Restore fovea UE0/periphery UE1 as an explicit preset (account for persisted profile values).
3. Restore old atlas layout coherently for both view selectors; validate both shader sampling and rectangle/projection mapping.
4. Restore the left optical gaze rotation with synthetic identity/yaw/pitch/roll tests and actual frozen-frame wiring. Preserve nonblocking CAPI, frozen projection, once-per-frame sampling and current valid-data checks.
5. Keep old/new source isolation diagnostics. Add bounded diagnostic evidence of scene-state/pass/projection/rect, rather than modifying global brightness or unrelated CVars.
6. Do not change frame/present gating, original ID5, runtime shader compilation or backend/SDK pins.
7. Run exact-source Windows CI, all existing suites and final package/hash inspection before delivering a candidate. Label it old-behavior restoration; shading/gaze fixes remain unproven until headset-tested.
8. If both sources still differ with UE0 fovea and matching old settings, isolate constructor PRIMARY treatment from singleton rendering. A constructor-only change may be insufficient and unsafe for paired engine expectations. Do not silently activate both PRIMARY in a two-view family.
9. If true independent primary shading requires separate render transactions, design atlas-safe target handling, stable independent temporal state and frame identity explicitly; measure CPU/GPU overhead before claiming production readiness.

## Checks performed here
- Read both supplied handoff documents completely.
- Queried exact Build24 run/job/step success metadata.
- Inspected exact old and new backends, old Mono patch, both integration scripts, geometry/state, gaze readers, projection construction, Native Fix constructor and render-family paths.
- Independently compared the six core Git blobs.
- Compiled and executed five portable C++20 test executables with g++: geometry, gaze, frame, config and state; all passed with assertions enabled.
- CMake is absent on this host; portable tests were compiled directly. Windows WARP, CAPI ABI tests, complete Joey suite and executable packaging were **not rerun here**. No new binary is being represented as verified.
- No runtime code, baseline branch, SDK or existing Windows artifact was modified.

## Primary documentation
Epic FSceneView documents primary-view association and secondary views:
https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/FSceneView
This supports the structural distinction, not a confirmed STALKER 2 Lumen root cause.
