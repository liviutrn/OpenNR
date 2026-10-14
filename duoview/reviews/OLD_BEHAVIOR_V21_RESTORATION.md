# DuoView v21: old visual behavior on exact Joey

## Scope and status

User requested restoration of the old hitching build's behavior, controls,
quality and features, with a Windows build for testing. This branch restores
the old visual integration on the exact, user-proven Joey backend. It does
not restore the old public backend or its frame/present gates.

The old reference is Injector-5 at
bd74b21f46aa51c6d535680a005682e2572d6965. The new base is v20 source
a68371d7777845986542782419198995bbf53a49 plus its documentation checkpoint.
See OLD_LOGIC_NATIVE_FIX_INVESTIGATION_2026-10-14.md for the independent
comparison and the user's clarification that good shading with Native Fix
was observed in Native Stereo ID0.

## Restored behavior and features

- Fovea defaults to first Unreal view 0; periphery to view 1.
- Foveal atlas rectangle begins at x=0; periphery follows it, matching the
  old applied geometry rather than Build19's reversed atlas.
- Gaze returns to the old inverse left optical rotation before projection.
  The implementation uses the transpose of the orthonormal rotation matrix
  in OpenXR coordinates, equivalent to the old inverse eye quaternion.
  The optical matrix and projection are frozen in the once-per-frame
  producer callback. No world-space head rotation, smoothing or deadzone
  is added. Invalid/blink/50ms-expiry handling remains bounded.
- Persisted width/height crop, peripheral scale, foveal density, feather,
  eye tracking, border and source-view controls remain available.
- Crop controls again reach 100%, subject to atlas size validation.
- Original source defaults return: crop .50/.50, density 1, periphery .20,
  feather .08, source view 0 and eye tracking on.
- Restore old DuoView settings applies these values to profiles that still
  contain Build19/v20 settings. User's actual preferred old tuning is unknown;
  these are verified source defaults, not claimed personal settings.
- Effective render dimensions, source role, gaze validity/UV and pixel
  budget are displayed. Gaze freshness counters and source isolation remain.
- GPU compositor plus both-eye-copy cost is available through an optional
  persisted toggle, off by default. Its setting is frozen per source frame.
  Timestamp resources/frequency are prepared at swapchain setup. Recording
  and readback occur only when enabled, on a retired command slot, without
  additional GPU waits or timestamp allocation inside the copy callback.

## Deliberately preserved safeguards

Exact Joey backend 5ac7edc207866569334175e4ed8a7517971547f6, original SDK
3cffbc82429b6165ceec2714f0f0d9ae48f55596 and matching frontend
60be4b0f9a646109fd9fdf448bacd41477234091 remain pinned. Original Mono ID5,
Native Stereo ID0, current same-camera pair validation, quarantine fallback,
offline shader compilation and swapchain prewarming remain in place.
Native Stereo Fix remains disabled inside ID6. No global game CVar or gamma
adjustment is used to disguise shading differences.

## Verification and limits

Local checks: exact-anchor source application to the pinned backend/frontend;
five portable C++20 suites; the production contract compiled against the
applied backend headers; Python syntax and whitespace checks. Synthetic
identity, optical yaw/pitch/roll and invalid-rotation fixtures verify the
gaze basis, including its connection to the CAPI projection test. Pinned
contracts validate restored atlas positions and immutable timing settings.

Windows CI must compile and run the three pinned suites (including CAPI
and WARP), six independent suites and all 41 original compatibility tests,
then build backend/frontend and inspect the packaged artifact. Exact
run/commit/artifact and hashes will be recorded after completion.

This is a source-level restoration candidate. Old/new backends and engine
view histories differ. Perfect shading in both sources, twitch-free gaze
and long-session frame pacing cannot be claimed before headset testing.

## Minimal headset test

1. Extract separately; run STALKER 2 DX12 with SteamVR as OpenXR runtime.
2. Select DuoView ID6. Open quality controls and press Restore old DuoView
   settings once. Confirm fovea UE0, periphery UE1 and source diagnostic 0.
3. Match your old preferred crop/density/peripheral settings if known.
   At 3000 output, old defaults yield a 1500 fovea; density 2 yields 3000.
   Actual sizes shown in the menu take precedence over these examples.
4. Check shading in a fixed scene with gaze off, then turn gaze on and check
   alignment/twitching and any hitches. Use source diagnostic 1/2 only if
   there is still a shading mismatch.
5. GPU timing is optional. It measures the compositor and eye copies,
   not the full Unreal scene-rendering cost.

## CI checkpoint — 2026-10-14

Initial restoration commit: 975d3580df9d540e1d60d68888d139c2aa822af4.
Run 38543434962 (25) passed the three pinned production tests but stopped
in independent GPU test compilation: timestamp frequency declaration was
after its prewarm use in production_warp_test.cpp. No build was delivered.

Test-only correction: 28dae2e13666b4f5513b6666546e8620d0926ce4.
Full Windows run 38543842360 (26) is the active candidate. Production tests
have passed again. All further gates and package inspection remain required.
https://github.com/liviutrn/OpenNR/actions/runs/38543842360

## Authoritative user retest — 2026-10-14, 12:45 Bucharest

After downloading and retesting old Injector-5, the user reports:
- good foveal shading;
- worse peripheral shading;
- twitchy gaze movement.

This supersedes the earlier recollection of perfect shading in both sources.
Old/new peripheral shading and twitching are shared limitations, not proven
new-backend regressions. The user accepts them for the upcoming test and
wants to see how the restored version behaves. Do not claim v21 eliminates
these defects. Prioritize retaining smooth Joey frame pacing; lighting parity
and optional low-latency gaze stabilization can be investigated subsequently.
The nine Windows DuoView test suites passed in run26; the original test
compatibility targets are still compiling at this checkpoint.

## Final verified Build26

Source 28dae2e13666b4f5513b6666546e8620d0926ce4; run38543842360 succeeded.
Logs independently confirm 3 + 6 + 41 tests passed. Matching backend/frontend,
source identity and package checks passed. Downloaded archive integrity and
16 applied-backend source hashes independently checked; all three DLLs are
AMD64 PE32+. Artifact11884263766 has 14 package entries.
Outer SHA256 ad7273f3527b961df2a0e64742a45207da3f4b8dc0923d1349bcd5f8c2a3d9fe.
Inner ZIP SHA256 078ab88e39515f0b5eaeb06f7f571765d0f6ec4bf994271e7ca466d6b692f10d.
UEVRBackend.dll SHA256 668c8b58b6ac631c3a9bfd4a906bf1b8b4db8943963f198b135d82daedd56f86.
https://github.com/liviutrn/OpenNR/actions/runs/38543842360/artifacts/11884263766

New user request: separate next build with optional gaze stabilization,
temporal crop/image coherence and in-game independent-shading toggle default
off, enableable after DuoView settles. Use verified OpenNR/Cheeky mechanisms.
Build26 does not contain these later additions. Preserve it as a comparison.
