# Build3 restart experiment status

The fresh restart branch is based on OpenNR
`64432d0442066715fa442660a0848cf4963640b0`, baseline workflow run
`38453012351`, and artifact `11842620175` (`Joey-101226-Clean-Baseline-Build-3.zip`).
The backend, SDK, and frontend source pins are recorded in `EXPERIMENTS.md`.
The previous v48 and v49 runs both fell back to Mono and provide no evidence
about moving-gaze stability.

The branch now includes an opt-in `Stable Source / Moving Mask` D3D12 control
at the pinned Mono copy boundary, along with a pinned-source patcher and a
Windows workflow for portable tests, WARP image tests, full compatibility
tests, and packaging. That workflow has not yet completed. This cloud
workspace cannot establish behavior in STALKER 2, on an OpenXR runtime, or on
PSVR2 hardware.

The control uses the original single full-frustum Mono source for both output
halves. It samples full-detail source pixels inside a deterministic replay mask
and coarser samples from that same image outside. It saves no scene-render work
and is not DuoView or two independently rendered engine views. The original
Mono behavior remains the default when the environment option is unset or
`off`.

Set `UEVR_STABLE_SOURCE_MASK` to `fixed`, `step`, `ramp`, or `alternating` in
the **target game process environment before starting the game**. Setting it
only in an injector process after the game is already running does not change
the game's environment. The first opted-in D3D12 copy prepares the shader and
falls back to Mono as a warmup frame. Optional bounded log summaries can be
enabled independently with `UEVR_DUOVIEW_DIAGNOSTICS=1`.

At the current integration boundary, only the D3D12 copy-frame counter is
observed. It is not established as an engine source-generation ID, projection
frame, or gaze-pose frame. The adapter separately records command recording,
the copy API return, and accepted producer-copy status. It does not claim that
`xrEndFrame` or headset presentation accepted an image. Diagnostic ring export
is still unavailable and is a follow-up implementation task.

The identical-full-frustum two-engine-view comparison remains blocked until
distinct engine-owned view state and an independently owned shading/history
consumer are proven. The current baseline evidence establishes the original
single-view Mono producer and its double-wide copy only.
