# DuoView v154 — temporal instability, transient black frames and performance audit
Date: 2026-10-18
Status: SOURCE-BASED INVESTIGATION; no production code changed and no headset validation claimed.
Stable reference: v22 commit bd8024c9e83debaaee6890d36c756f186e8421e1 (user-tested performant).
Known stable fallback: Build 149 commit 41077d51d29019a1579441a7bc7ca9334d2d22a0.
User-tested v154: 8c64ec6030043d5c10b9616598356be7685f860e, CI 39148325975.
Pinned Joey upstream UEVR: 5ac7edc207866569334175e4ed8a7517971547f6; restricted UESDK: 3cffbc82429b6165ceec2714f0f0d9ae48f55596.

## User observations
- v154: shading looks good; DO NOT roll back the current native-fix/stock-secondary shading behavior.
- Eyetracked crop: scene *inside* fovea trembles/translates/"moves forward/backward" on movement and keeps settling after the crop stops. Persists with "Stable gaze crop" OFF and with deliberately very slow gaze movement. This excludes the adaptive deadzone as sole/root cause and points toward scene render/temporal reprojection, though no GPU capture has yet proved which pass.
- Short frequent black flashes precisely coincide with apparent Mono fallback/recovery.
- Slightly worse performance versus original performant v22.

## A. Black-frame cause independently supported by implementation
DuoView patch: duoview/joey_stage1/apply_stage234.py.
At D3D12 copy branch, `packet_pair_valid` requires current packet + duoview snapshot/binding + generation + two Native Fix scene textures + `scene_capture_packet_ready` + `get_openxr_runtime()->has_mono_frame(packet_source)`.
If invalid -> no copy, status "Waiting for a complete Native Stereo Fix DuoView source pair"; sometimes invokes `note_mono_copy(source,false)`.
If the XR command slot copy is skipped or returns false, also leaves frame non-copied.
Original Joey OpenXR.cpp `OpenXR::get_submit_state()` uses `mono_copied_frame`, rejects if no `mono.copied` or mismatching frame and returns an EMPTY `PipelineState` with no scene views.
`OpenXR::end_frame` logs "[Mono] No validated current scene/pose to submit"; `xrEndFrame` with no projection layers clears the scene. `OpenXR::end_mono_transition_frame()` explicitly sends an empty frame.
This can cause transient black flashes even without any actual permanent renderer fallback.

Differentiate:
* Temporary rejected/missing source pair -> current DuoView branch stays active, a frame is left blank.
* `duoview_abort(...)` -> `m_duoview_quarantined=true` and original Joey Mono inside ID6 until mode reset. Repeated automated recovery in a single session should not be presumed without logs; look for mode/transition reset.
* User perceives both as Mono fallback. Instrument separately.

OpenXR spec: https://registry.khronos.org/OpenXR/specs/1.1-khr/html/xrspec.html
- `xrEndFrame` may reference the most recently released swapchain image without a new release, and zero layers clears the display.
- An old image + *matching old image pose/FOV* can be re-used as a short grace fallback with current predicted display time; do NOT relabel as a freshly rendered pose.
SteamVR concern: https://steamcommunity.com/app/250820/discussions/0/3843305519472175943/ reports reusing the last image without updating swapchain sometimes not functioning on SteamVR. Validate with PSVR2/SteamVR; a synchronized GPU copy of last fully composed image into a *currently acquired* XR slot may be safer.

Recommended fix architecture:
1. Track ReadyDual, Warmup, TemporarilyMissing, FatalQuarantine separately. Never flip native/mono rendering modes during short packet gaps.
2. On missing pair for 1–3 frames, present last fully composed VALID DuoView image with matching pose/FOV through a correctly acquired/released XR swapchain image, preserving all command-slot fences and lifetime. Do NOT submit a null projection layer after first valid frame. No new DX shader compile/PSO creation/resource allocation in XR copy callback.
3. On persistent invalid or GPU device-loss faults, explicitly log and fail closed to original Mono only at a safe transition, with hysteresis / no fast oscillator.
4. Never reuse a cropped/half-initialized Native source as a full screen Mono substitute.
5. Diagnostics COUNTERS: no_packet, null_snapshot, invalid_generation, wrong_source_frame, incomplete_pair_binding, scene_capture_missing, missing_mono_pose, slot_not_ready, compositor_failed, empty_submit, quarantines, true_mode_resets, first_valid_submitted; log summary max once/second, key/generation/capture generation and `xrEndFrame` layer count. Do not log every frame by default.

## B. Within-fovea temporal "inertia": top investigation
In `DuoViewState.hpp::apply_frame_projection`, `apply_foveal_crop()` modifies the current camera projection, via patched FFakeStereoRenderingHook::calculate_stereo_projection_matrix().
`duoview_begin_frame()` freezes current pose/projection/gaze per native source frame.
The DuoView patch has NO explicit handling of PREVIOUS off-axis foveal projection nor previous-view UE shader uniform matrices and no motion-vector correction. Unreal may internally derive previous projection using its own persistent FSceneViewState; verify this before writing any patch, otherwise double-correcting would make artifacts worse.
UE `FSceneView::SetupCommonViewUniformBufferParameters` requires current AND previous view matrices, and a persistent `FSceneViewStateInterface` controls temporal accumulation.
References:
https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/FSceneView
https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/FSceneViewStateInterface
https://dev.epicgames.com/documentation/unreal-engine/temporal-super-resolution-in-unreal-engine
Current implementation already observes both native UE `init_options_scene_state` pointers in `VR::duoview_state().scene()`, exposed by UI as shared/separate, but doesn't actively guarantee independent fovea/periphery view-state history or correct previous projection.

Strong hypotheses to discriminate:
a) `PrevViewMatrices` does not match the actual last rendered foveal crop (missing/mis-tracked previous crop, jitter included) -> camera velocity vectors/reprojection mismatch; history crawls after the gaze settles.
b) fovea and periphery share FSceneViewState or Native Fix relabel PRIMARY distorts per-pass UE history -> one region overrides the other's prior view state; inspect pointer continuity and `get_effective_stereo_pass()`.
c) post-AA (TSR, DLSS/TAA) or Lumen's own screen-probe/reflection histories accumulate over moving off-axis foveal frusta; specific pass can lag.
d) native packet/pose frame discontinuities exacerbate problem, especially during brief blank/restart intervals.

Suggested non-destructive isolation sequence in STALKER2, preserving user shading:
- A/B with stable gaze crop ON/OFF already rules out the gaze filter (user confirmed both artifact).
- With current Native shading unchanged and same scene, temporarily disable DLSS/temporal AA (check game actually obeys commands) and compare; restore.
- Separately test `r.Lumen.ScreenProbeGather.Temporal 0` to distinguish Lumen GI history; restore 1. This can introduce noise and is diagnostic, not a quality fix.
- Diagnose view-state pointers and current/previous projection/rect phase *on accepted frames* through throttled log or GPU debugger, including whether first/second UE pass histories are actually separate. Avoid guessed private SDK offsets and indiscriminate "camera cuts".

Candidate production fix if confirmed:
- Per-view permanent history identities, current *and previous* crop projection/rect matrices coherent with a source frame. Preserve UE's own temporal jitter and motion-vector conventions.
- Pass the previous ACCEPTED RENDERED FOVEAL frame's projection, camera, crop and texture extent through the UE prior-frame uniforms. Do not use latest eye sample or OpenXR submit frame as the UE rendered-history index.
- Temporal discontinuity only: a bounded history invalidation on large crop moves/changed generation if reprojection correction not feasible; avoid resetting history EVERY gaze movement or every blink (performance and shimmer).
- Keep tested shading and Native Fix split logic unchanged.

## C. Performance
v22 compositor can consume already-present atlas; v154 `DuoViewD3D12.hpp::record_native()` performs two `CopyTextureRegion` gathers from primary and secondary NativeFix captures into an extra atlas, then full-frame shader blend/draw and stereo output copies. Extra GPU bandwidth, resource transitions, checks and packet-lifetime bookkeeping. This is strong candidate, not measured explanation.
DuoView GPU timer is measured around `record()` and does not cover two initial source gather copies, so "compositor ms" may undercount.
Optimization candidate: bind the two validated BGRA8 scene textures as distinct SRVs to a SINGLE precompiled blend PSO, sample fovea/periphery directly (no staging atlas gather); keep original Native Fix capture and shading. Requires changing compositor shaders and prewarm PSO but not UE rendering. WARP pixel-equivalence tests, source resource/fence lifetime tests and shader output parity BEFORE headset testing.
Time GPU capture, renderer pass, copy, blend, xr copy separately and compare same FOV/crop/resolution/shading settings to original v22. Log FPS/CPU/GPU and active render target dimensions; avoid interpreting raw FPS without controlled settings.

## Release gates
- Source identity/SDK pins, Stage1/Stage234 exact-anchor audit, Windows backend/frontend compile, ALL original Joey compatibility tests, independent CPU state/projection/gaze, WARP direct dual-SRV equivalence, full GPU lifetime and XR frame state-machine tests.
- Test simulation: 120 frames alternating valid pair, missing pair, async Present lag, temporary XR copy not ready, blink/gaze moving/stop, device loss, reselect. Assert no projection layer disappears after first valid DuoView; no stale packet combined with NEW pose; no permanent Mono fallback from recoverable gap.
- Preserve Build149 and Build154 byte-for-byte, develop on isolated branch. Require headset logs and explicit user confirmation before asserting stability.

## Evidence needed from a fresh v154 headset log
Start logging before first activation, include 20–30 seconds of normal image, deliberate gaze sweep/hold and at least two black flashes; upload full original UEVR log. Look for "Waiting for a complete Native Stereo Fix DuoView source pair", "[Mono] No validated current scene/pose to submit", "[DuoView] Quarantining two-view path", "xrEndFrame succeeded: layers=0", Native capture generation, repeated device/setup, "[DuoView][Activation]" and any `XR_ERROR_TIME_INVALID`.
Current production logs don't enumerate per-gate invalid reasons, so a separate diagnostics build may be needed if the raw log is inconclusive.
