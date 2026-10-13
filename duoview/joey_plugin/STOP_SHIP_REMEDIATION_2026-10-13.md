# DuoView Joey-first v11 — STOP-SHIP engineering gate

Date: 2026-10-13
Source under review: `681b962237c702d2b09486b56d7526233f922dd0` (Windows Actions Build 25)
Last in-game evidence: Build 16, which failed to load the Lua UI; no Build 25 game test.
Status: **NOT SAFE TO REQUEST ANOTHER ACTIVE-MODE USER TEST**.

The independent review uploaded on October 13 was corroborated by inspection of Build 25
`duoview/joey_plugin/Plugin.cpp` and pinned **public reference** Joey commit
`e30b0ee5dd480ce607abb63ef74c317bd43bd871`. This public commit
does not prove exact execution of the released backend. The official Joey Mono
backend hash `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`
must remain unchanged. Do **not** restore the substituted public backend.

## P0 — establish a viable frame-copy and fallback contract first

1. `end_hook` discards projection layers when no mailbox packet exists. This can remove
   the scene while preserving other UEVR layers. Neither forwarding an uncomposited atlas
   nor substituting stale pose-labeled pixels is a valid fix.
2. Frame publication currently happens *before* `original_frame()`; the plugin has no
   confirmed relationship to the actual successful source-to-OpenXR swapchain image copy.
3. Compositing transitions an engine-owned scene target from RENDER_TARGET without a
   proven current resource state or synchronized producer queue ownership. Render-target
   resource flags are not evidence of current state.
4. **Required architectural work:** inspect the exact released backend's D3D12 scene
   selection, acquire/copy/release/submit path and graphics queue ordering. Select a
   validated hook/copy boundary. Prepare an owned composite texture ahead of time,
   consume it at the validated copy boundary, and prove destination swapchain identity
   before declaring a frame published. Confirm D3D12 debug-layer state transitions.
   The plugin must not convert source rects/projections until the replacement path
   is prepared; after activation, any failure transitions *subsequent* frames to an
   original-stereo producer, with a coherent same-frame handoff policy.

## P1 — true producer/consumer identity

1. `locate_hook` uses `xrLocateViews.displayTime` as the mailbox key. Joey's
   public OpenXR.cpp uses `predictedDisplayTime + predictedDisplayPeriod *
   prediction_scale` for pose sampling; normal submit can use the original predicted time.
2. Do not equate pose-sampling time with `xrEndFrame.displayTime`. Identify
   exact released backend frame-index/generation, frame prediction time,
   gaze/pose sample time and presentation swapchain image index.
3. Add regressions: nonzero prediction scale; overlapping pose calls; late or
   missing producer; failed source copy; simultaneous frames; device reset and recovery;
   late OpenXR layers. Never match packets by an arbitrary time tolerance.

## P2 — eye tracking and optics (after fixed-fovea correctness)

`locate_hook` calls `get_pose` immediately after `xrLocateViews`, but
public Joey code updates view-space head pose via `xrLocateSpace` later.
Require a head and eyes at the *same* prediction time and coordinate space,
or derive eye geometry in head-relative space. Add constant-head-relative-gaze /
 rotating-head test; eye-relative UV must not drift. Eye-tracked mode stays blocked
until this is proven.

## P3 — UI and performance hygiene

* Validate the **combined** crop width/height, peripheral scale and
  foveal density against `make_layout` for the *actual output size* before
  allowing save. At 3000×3000, crop height 0.5 and density 3 creates
  4500 pixels of fovea height, which does not fit the atlas.
* Show actual dimensions and estimated pixel counts; label density=1 at
  default 0.5 crop as **no central pixel-density increase**.
* Remove `D3DCompile` from active-frame `Compositor::prepare` using
  build-time shader compilation or prewarming before the first modified view.
* Preserve an unobtrusive in-game menu with counts for prepared frame,
  actual successful GPU composite/copy, XR-presented frame and fallback reason.

## Acceptance gate before a single user test

- Pin exact released Joey binary, hook addresses and observed copy/submit ABI;
  test the production-adjacent hook path against a deterministic integration
  harness with mock original-frame success/failure and OpenXR submit.
- Verify fail-closed behavior for missing packet, mismatched prediction times,
  invalid resource state, reset, and scene-copy failure. The user must not be
  used to discover these already predictable failure cases.
- Windows CI: C++ tests + full D3D12 debug-layer path + executable Lua UI
  + installer verification; include dependency refs, complete job logs and hashes.
- Deliver one deliberate **fixed fovea** acceptance build only after all P0/P1
  conditions are met. Then validate gaze (P2), then compare FPS/PPD.
- Successful compilation, WARP compositing on assumed states, and valid Lua
  syntax/runtime mocks do not constitute successful operation in STALKER 2.

Related evidence: successful Build 25 Windows CI
https://github.com/liviutrn/OpenNR/actions/runs/38378964134
and its exact source:
https://github.com/liviutrn/OpenNR/tree/681b962237c702d2b09486b56d7526233f922dd0

The Build 25 handoff ZIP lacked `source/.github/workflows/duoview-joey-plugin.yml`;
include it in any replacement ZIP with a corrected full manifest.
