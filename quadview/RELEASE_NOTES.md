# Local ID7 candidate notes

This candidate adds stereo ID7 frame-lifecycle guards, per-eye gaze projection,
the published v186.1 DuoView gaze recovery and crop-stability behavior, quality
controls, fused focus sharpening, and optional per-slot D3D12 GPU timing. It
keeps ID6's DuoView source and the v186.1 production helper implementations
unchanged. The `GLAMARYE_LICENSE.txt` file applies to the fused sharpening
implementation and ships beside this note.

Portable geometry, producer/history, delivery, and asynchronous tests pass. The
guarded source overlays applied to the pinned backend and frontend copies.
Windows shader compilation, Windows backend compilation, and GPU WARP tests
remain pending for this candidate. No headset test has been run.

The Build32 dump establishes a null indirect write while Unreal traverses
render-graph resource metadata. It does not establish the specific resource or
root cause. The nearby UI toggle is temporal correlation only. This candidate
must not be described as crash-fixed or headset-stable.

The transition drain covers tracked ID7 engine tickets and command tails. An
unknown owner, an overflow, or a missing tail deliberately blocks the
transition. This ledger does not prove that every Unreal render-thread or RHI
consumer has drained. Native secondary-pass shading is excluded because the
existing DuoView path changes mono-dependent state and cannot be reused safely
for true stereo four-view rendering without a separate engine design.

Before use, require the full Windows CI build and a headset retest. Verify
stereo depth, per-eye focus alignment, gaze-loss recovery, GPU timing output
when enabled, and a sustained gameplay run. CI success alone does not establish
headset stability or resolve the dump's unproven root cause.
