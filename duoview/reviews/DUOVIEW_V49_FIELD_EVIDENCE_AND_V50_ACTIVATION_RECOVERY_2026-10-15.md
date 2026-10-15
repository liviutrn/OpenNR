# DuoView v49 field evidence → v50 activation recovery (15 October 2026)

## User-observed failure
Both v48 and v49 immediately appeared as Mono rather than two-view DuoView ID6.

## Concrete runtime evidence (provided UEVR log + v49 desktop collector)
- UEVR backend source `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6` and restricted UESDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`.
- UEVR log 19:50:04.961: `[DuoView][Bootstrap] Request guarded Native0 -> DuoView6 transition`.
- 19:50:04.987: `[Mono] Committed rendering method 6 at viewport boundary, generation=1`. Selection and transition were NOT the initial blocker.
- Frame 13602: constructor hook installed and both UE5.5 views constructed; both have different `scene_state` pointers.
- 19:50:05.357: `[DuoView] Quarantining two-view path; continuing original Mono inside ID6: XR copy/composite fault; safe original Mono requested`.
- Collected `frame_trace.csv` contains stage0 producer=3, stage1 pre-UE constructor=6, stage2 post-UE constructor=6; no stage3 GPU composite and no stage4 XR accepted.
- Every recorded frame carried `fovea_history_disabled=false`. For frame 13602, source view 0 and view 1 constructor records both had flag 2 (constructor returned, no fresh-fovea state suppression).
- `image_manifest.csv` only has its header. NO GPU captures or evidence of a composed DuoView frame. The log cannot tell which specific fresh-fovea guard expression failed, but it proves the mandatory v48/v49 no-history contract was unfulfilled when sampled.
- In both v48 and v49, `State::consume` refuses a frame if `fresh_fovea_no_history=true` and `fovea_history_disabled=false`. First incomplete frame then triggers unconditional session-latched `duoview_abort` even when compositor was never called. This is a **proven activation dead end**, although some independent missing-frame predicates may also exist.
- Separately, `[DuoView][Bootstrap] Native 0 boot scale 0.30, restore target 0.300` evidences incorrect or at least suspicious capture of the desired resolution: source assigns 0.30 before persisted config is read. v50 removes that early overwrite.
- The UEVR log also has hundreds of `xrBeginFrame: XR_FRAME_DISCARDED` and `xrEndFrame: XR_ERROR_TIME_INVALID`, even before ID6. This may independently prevent XR submissions. Do not attribute them solely to DuoView.

## Source changes on `experiments/duoview-v50-activation-recovery`
1. Keep the exact pinned Joey backend/front-end and UESDK unchanged; keep modes ID0 Native and ID5 Mono untouched.
2. Keep v49 synthetic and PSVR2 eye-gaze trace, logs, image readback and collector.
3. Add persistent `DuoViewFreshFoveaNoHistory` option, **OFF by default**. UE5.5 typed FSceneViewState constructor suppression stays available only when explicitly enabled, with its original strict required-proof gate. No guessed SceneView offsets.
4. To permit gaze motion for debugging on unsupported UE5.5 history ABI, add explicit `allow_uncorrected_gaze_history` setting, enabled only when experimental fresh-fovea is off. This overrides ONLY the previously impossible temporal-history-override requirement; geometry, source views, current transforms, scene-state continuity, pair validity and compositor validation remain guarded. Standalone default remains strict. **This is NOT an eye-motion stability fix** and the image may still tremble.
5. After failed `State::consume` from a missing/incomplete startup source pair, attempt normal Joey Mono copy and retry the next producer frame; do not quarantine ID6 forever. Throttled UEVR log includes current pair readiness: main family, rectangles, projections, cameras, scene states, freshness and history gate. With a complete pair, actual compositing/XR copy faults STILL quarantine.
6. Remove early `m_openxr->resolution_scale=0.30` in constructor; capture user's profile value before applying startup 0.30 in post-config bootstrap.
7. Add dedicated `verify_v50_activation.py`, preserve v49 diagnostic verifier and extensive pinned compatibility, geometry/CPU/DX12 WARP and package audits. Update package metadata to **accurately distinguish default history-uncorrected diagnostic mode from the optional v48 no-history test**.

## Remaining blockers and acceptance
- Do NOT call v50 compiled or headset-verified until Windows CI and ZIP SHA are checked.
- Source branch HEAD is to be used in GitHub Actions workflow `.github/workflows/duoview-joey-stage234.yml` (push branch filter `experiments/duoview-v50-activation-recovery`).
- If Windows source anchors/CI fail, fix the actual first failing step; never send a partial DLL.
- Runtime acceptance: ID6 commits; 120 center + 120 step + 120 sweep + 120 return + live gaze runs; at least one stage3 GPU and stage4 XR-composite-accepted event, plus GPU image tiles and restored user resolution scale; no repeated quarantine, no crash.
- If still no compose, log the new `[DuoView][Activation] incomplete pair` status and investigate precise missing geometry family/rect/proj/camera invariant; if XR errors persist, diagnose OpenXR frame timing separately.
- Later, revisit true UE5.5 temporal reconstruction from source-backed APIs or safe engine temporal consumers. Do not claim moving gaze jitter is solved by v50.
- Protected Joey Build3 must not be overwritten. Use isolated folder for testing.

## Verified final v50 Windows build (2026-10-15 17:42 UTC)
- Source build commit: `f2675abb28050a6af4bb66d1a1e404ec1c91f955`. (Later commits to this documentation do not change built source.)
- GitHub Actions **run 38776407208**, #109, overall **SUCCESS**: https://github.com/liviutrn/OpenNR/actions/runs/38776407208
- Passed: exact Joey/UESDK/frontend source pins, stage1/stage234/native bootstrap/v49 diagnostic/v50 recovery exact-anchor patches, generated-source audit, v50 behavioral pair tests, independent CPU/DX12 WARP tests, original Joey compatibility test suite, backend DLL build, frontend build, PE/ZIP/hash audit.
- Windows artifact ID **11994669294**, name `Joey-DuoView-Activation-v50-109`. Inner install ZIP `Joey-DuoView-Activation-v50-109.zip`, **11,673,990 bytes**, SHA256 `29c8dcf6c07ed57cbb6f94708a459524a3f29fb4137635f16b82db48a65393c2`; checksum checked independently after download. Includes UEVRInjector.exe, UEVRBackend.dll, OpenXR loader, diagnostic collector and policy JSON.
- Diagnostic evidence artifact ID **11994449422**.
- **Important**: passing Windows CI does NOT establish that the user’s real STALKER2/PSVR2 headset session composites even one frame. User has not yet tested v50. Source regression tests are not an Unreal game integration harness. The v49 XR_FRAME_DISCARDED and XR_ERROR_TIME_INVALID stream remains unresolved. If ID6 remains Mono, collect v50 UEVR log and the ZIP created by `Collect-DuoView-V49.cmd`; inspect newly added `[DuoView][Activation]` line for missing family/rectangles/projections/cameras/views.
