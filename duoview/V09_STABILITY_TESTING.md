# DuoView v09 stability diagnostic build — 13 October 2026

## Exact Windows build
- GitHub Actions run: https://github.com/liviutrn/OpenNR/actions/runs/38365762543
- Compiled source: `40c5b72abd5805645a3e63def5a8a85d748abad8`
- Artifact: `DuoView-v09-Stability-Windows-Injector-7` (ID `11797615838`)
- ZIP SHA256: `bb8899300d0e91c974e90d4cbe70657933028d8af638ba3d0c4ed3c364db5d6f`
- Backend SHA256: `a5242ce328451a3454013c53556048a2fac3025c033594e93f9db8ebbdad52c0`
- Injector SHA256: `1472acdfcbe37d2a554335ca8c0a458891674372e45fd330b49938e4aac794bd`

The v09 Windows build, six production/portable tests, injector packaging and artifact upload completed successfully. The downloaded 17-entry artifact passed a ZIP-integrity check. **This does not mean STALKER 2/PSVR2 behavior has been validated.**

## Changes from Injector-5

Only two targeted behavior changes:
1. Do not skip DirectXTK graphics-memory Commit when a Mono transition blocks backbuffer clearing. Continue to suppress **only clearing** while unsafe. This may help resource retirement but is not yet proven to fix hitching.
2. On a committed return to Native/non-Mono, mark the new generation ready instead of demanding Mono-only frame metadata. This addresses a stale-gate pathway after exiting Mono.

Bounded counters now capture Present entry gaps, D3D12 frame-handler max duration, rejected Mono frames, post-present call/clear/graphics commit counts, maximal graphics commit and clear durations, raw Unreal view indices and main-family counts. One aggregated line is written every 10 seconds:
`[DuoView stability v09] ...`

No fovea, peripheral resolution, camera pose, eye-gaze, crop, feathering or compositor behavior is intentionally changed. **Direct cold startup and ordinary Mono are NOT yet fixed.**

## Priority headset tests

Back up the successful Injector-5 and current game profile. Extract the complete v09 package into a different folder. Preserve the exact save, scene, in-game graphics, OpenXR runtime, resolution and plugins for both builds. Do not delete profiles as part of this comparison.

**A — Fresh Native-only:** Exit STALKER completely; launch fresh; inject v09 with Native Stereo; stay in Native Stereo for 45–60 seconds. Record whether the periodic hitches occur **before any Mono/DuoView selection**.

**B — Native to DuoView:** Exit STALKER completely; launch fresh; inject v09 in Native Stereo; switch to DuoView Mono only once Native appears correctly. Run 45–60 seconds; check fovea, eye tracking, peripheral reduction and hitching.

**C — Ordinary Mono (optional):** In another fresh process, inject Native, then choose Mono ID 5. Report whether it is still black and how the counts differ. Do not keep testing if the display freezes or a crash follows.

After each process, save the full UEVR.log, any new crash report, and a SteamVR frametime graph screenshot. Send the logs with A/B/C labels. Also report whether unmodified Joey UEVR hitches under identical Native Stereo conditions, if tested.

The `raw_view_bits` field reports a bitset: bit 0 negative, bit 1 index 0, bit 2 index 1, bit 3 index 2, bit 5 index 4 or higher. `families_1/2/other` count native Unreal main-view-family sizes observed during Mono frame gating. Frequent `rejected` counts suggest a validity/ownership issue; a large `max_gap_us` with normal `max_frame_us` suggests the stall occurred outside the measured UEVR frame handler. These are clues, not automatic root-cause verdicts.

## Next steps after evidence

Use runtime traces to repair automatic Native bootstrap, ordinary Mono black-screen indexing/family validity, and the actual cross-mode hitch source. Preserve the Injector-5 reference build and do not mistake the untested v08 Joey adjunct plugin for the successful source-integrated DuoView renderer.
