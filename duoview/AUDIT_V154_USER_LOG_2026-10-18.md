# DuoView v154 user log audit — 2026-10-18
Source: user-provided UEVR log `log(20261018-200536).txt` (5218 lines, 22:46:10–23:03:20 local).
Build: Joey upstream `5ac7edc207866569334175e4ed8a7517971547f6` + DuoView v154 patches, UESDK pinned `3cffbc82429b6165ceec2714f0f0d9ae48f55596`. System SteamVR OpenXR / PSVR2, STALKER 2 UE 5.5.
User reports great peripheral shading, GPU usage v22 Mono 91% Duo 69%; v154 Mono 91% Duo 75% (relative difference 8.7%, 6 percentage points; not directly equal to FPS cost), UI sometimes unresponsive, gaze OFF does not seem to work, cannot adjust fixed fovea vertical position, occasional image jitter even fixed, frequent black flashes.

## Reproducible extracted counts (string matching, rate-limited logs)
* `[DuoView] Requested quality settings exceed atlas geometry`: **95** lines (started 22:55:08, continued until 23:03:16). Config latch transaction failed: renderer ignores unrelated toggle edits while a slider is invalid. Underlying cause not uniquely encoded: could be crop/density tuple or gaze stillness>=breakout. `Fovea exceeds Native single-view capture size`: 2 lines. The current warning misleadingly calls all invalid transactions an atlas geometry issue.
* `[NativeStereoFix] Refusing stale submit packet`: **50** lines, most delta=2 render/engine frames. Rate-limited; not necessarily total rejected frames.
* `[Mono] No validated current scene/pose to submit`: **121** lines. Rate-limited; not necessarily total empty frames.
* 46/50 *logged* stale-packet warnings occur <=10 ms from a logged "No validated current scene/pose to submit" warning. Very strong temporal correlation; reject is a major contributor to intermittent black output, though no proof it accounts for every blackout.
* `xrEndFrame succeeded: layers=0`: 3 occurrences, 2 with `shouldRender=1`, one with `shouldRender=0`. Do not count all three as missing scene under normal rendering.
* `xrEndFrame failed: XR_ERROR_TIME_INVALID`: 5 occurrences, often around actual mode/session changes. Need context, not proof same problem.
* `[DuoView] First scene pose not captured`: 7 occurrences around activation.
* `[DuoView][Activation] Prepared 3/3 OpenXR command slots`: 8 lines. Prewarm not absent, so prior Build146 missing-slot problem not reproduced.
* **No** `[DuoView] Quarantining two-view path` or `Native compositing rejected` lines; don't claim repeated permanent fallback. ID5/ID6 explicitly committed 5 times each (mode activations), likely user actions/restarts rather than automatic per-frame cycling.
* `XR_SESSION_NOT_FOCUSED` input/action sync errors: 3. These may explain some controller-input interruptions independently of DuoView setting validation; need ask whether "buttons" refers to ImGui settings or in-game controls.
* NativeFix captured sizes vary: initially `3648x3220` through gen 5, then `3132x2768` gen 7, 9, 11. GPU comparisons must control dimensions; the former is ~35.5% more total pixels than latter. Capture shows 6 full source generational publications and a repeated gen9 acceptance.
* OpenXR `xrEndFrame` missed target timing requires corroboration with actual FPS/CPU/GPU traces.

## Verified source-root cause of settings failures
Production patch script `duoview/joey_stage1/apply_stage234.py` in Build 154:
- `VR::configure_duoview()` does an early `return` if `m_duo_width/height * m_duo_density > 1`.
- Otherwise constructs ONE `const Settings candidate` mixing size, gaze, shading and everything else; `m_duoview.configure(candidate)` calls `ConfigLatch::set_settings` and refuses ALL edits on ANY invalid setting.
- `DuoViewCropStability.hpp` used `if (!s.eye_tracked) { have_=false; return UV{}; }` which fixes gaze to center (0.5,0.5) and discards manual offsets.
- `duoview_gaze_active()` previously displayed stale reader active status even with eye toggle OFF.
Controls isolated patch branch `fix/duoview-v154-controls-offcenter-20261018` based on 154 keeps quality tuple on invalid requested geometry, clamps conflicting stillness independent of other toggles, applies saved offsets to fixed mode, and gates gaze-active status with actual active setting. Production rendering, packet, XR, shading unchanged. CI expected; do not claim headset validity.

## Next production fix priorities (DO NOT prematurely release)
1. Instrument *each* rejection: stale-packet frame token mismatch, invalid pose/projection token, missing Native capture, missing slot, missing packet, failed/empty xrEndFrame, copy failure. Show last-success and consecutive-missed packet counters.
2. Implement **short grace display** of last fully composed mono frame *with its original pose/FOV* via a valid XR swapchain and proper D3D12 fences. Do not relax frame_window to accept packet_delta=2 with a new pose, or reuse stale half-source as new valid frame.
3. Preserve output UI and input; distinguish XR_SESSION_NOT_FOCUSED from rejected settings.
4. For persistent fixed fovea image jitter, first disable gaze sample entirely and identify whether black/missing frames or UE temporal history remain. For moving gaze image *inside* crop, instrument per-pass previous/current foveal projection, engine TAA jitter, ViewState identity, Lumen/TSR/DLSS history. No indiscriminate history resets.
5. Profile gather: v154 `DuoViewD3D12.hpp::record_native` copies 2 whole captures into prewarmed atlas, then blends and stereo-copies; v22 directly composited old atlas. Time source capture vs 2 gather copies vs blend vs XR copy, same output resolution/crop/settings/shading. Potential zero-extra-gather PSO with two SRVs, GPU/WARP equivalence first.

Do not confuse count of rate-limited log messages with real frame counts.
