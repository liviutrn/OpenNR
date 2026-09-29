# MLX-DLSS September 7 performance update: OpenNR relevance

Recorded September 8, 2026 from the source-backed assessment in this task.
This is a research decision record, not a local reproduction or implementation.

## Decision

MLX-DLSS remains a valuable isolated offline teacher-comparison candidate. Its
latest performance commit makes that experiment more practical, but does not
change the immediate OpenNR fitting/visual-diagnostic priority or establish a
faster Windows/NVIDIA VR runtime. Keep native Feature 18 authoritative until
Skyrim-specific parity has been measured. Do not replace or silently relabel
existing native teacher targets with reconstructed outputs.

## Verified public update

Upstream commit: [4549ce6d99837e4fb182c38a028d8e96bc28c0df,
Reduce temporal video and frame generation inference latency](https://github.com/iamwavecut/MLX-DLSS/commit/4549ce6d99837e4fb182c38a028d8e96bc28c0df),
dated September 7, 2026. The commit and its reported measurements were inspected;
the benchmarks were not reproduced locally.

The change overlaps next-frame motion/confidence preparation with current-frame
inference, reduces stream copies, reuses global-attention/FFN scratch allocations,
and selects measured Metal SIMD-group convolution paths for frame generation.
NR and frame generation share decode/encode stages with float32 intermediate
frames instead of an intermediate MP4. Stream protocol v3 preserves unscaled
8/16-bit source RGB as packed integers, reuses constant depth, and retains
float32 resampled RGB, motion, confidence and returned RGB.

The author reports a 228-frame 512x384 temporal NR clip at detail strength 2 on
an M2 Max taking 10.1–16.1 seconds versus 18.4–22.8 seconds previously, including
startup, optical flow, decode and encode. Alternating comparisons report about
1.4x whole-pipeline acceleration, equivalent to approximately 29% less elapsed
time for the same workload. Other desktop GPU applications were running.

On tested 24-frame raw sequences at 512x384 (processing scales 1 and 2) and
1920x1080, the author reports at most 1.2e-7 output difference from the previous
implementation; prefetch on/off was bit-exact. Checkpoints, history semantics
and model precision were unchanged. These are bounded author-reported results,
not proof of equivalence for every input or backend.

## What the numerical evidence means

The 1.2e-7 comparison is optimized reconstruction versus previous reconstruction,
not reconstruction versus NVIDIA. The separate published NVIDIA comparisons
remain about 0.004–0.005 MAE on game renders and 0.0054 MAE / 42.3 dB on a
64-frame static temporal sequence. Motion, jitter and mask cases are not covered
by that reported temporal parity result. These metrics cannot be compared directly
with OpenNR student MAE without matching data, preprocessing and evaluation.

The project documents a PyTorch graph and Python temporal API accepting engine
motion as normalized current-to-previous UV offsets. Its ordinary video path
uses optical flow and added confidence/rejection heuristics; those heuristics
are not recovered NVIDIA behavior. See the [README at the assessed commit](https://github.com/iamwavecut/MLX-DLSS/blob/4549ce6d99837e4fb182c38a028d8e96bc28c0df/README.md).

The source supports an inspectable recovered teacher and possible future
feature-based distillation experiments. This performance commit does not
demonstrate successful backpropagation/fine-tuning, a useful LoRA checkpoint,
or successful DLSS5-output student distillation. PyTorch availability alone
does not establish those outcomes.

## Fit to the current OpenNR work

The local records inspected for this assessment supersede the earlier empty
renderer-conditioning-pilot snapshot in the September 7 research report:

- Additional one-pass/two-pass caches were prepared and accepted according to
  their recorded audits.
- The joint run completed 1,200 updates without a checkpoint improving all five
  validation cohorts. The verified step-5600 reference remains the baseline;
  the 0.011 objective remains unachieved.
- The saved joint-run record schedules independent final replay, galleries and
  ordinary full-training-fit diagnostics before the next optimization decision.
  This document does not claim those pending diagnostics have since completed.

Sources: [training status](OPENNR_TRAINING_STATUS_0.5.5_20260907.md),
[joint teacher integration/results](TWOPASS_DATA_INTEGRATION_20260907.md), and
[verified broad U-Net reference](STABLE_UNET_BROAD_20260907.md).
These are the saved records inspected during the assessment, not a live process
status check at the time this note was written.

| Update or capability | Practical relevance |
| --- | --- |
| Faster reconstructed teacher inference | Helps future auxiliary target generation after parity acceptance; does not accelerate training against existing cached targets. |
| Recovered graph and weights | Strong research lead for teacher behavior, history semantics and possible intermediate-feature supervision; predates this speed commit. |
| Preparation overlap, fewer copies, buffer reuse | Transferable engineering ideas only after profiling our implementation. |
| One decode/encode for NR plus frame generation | Little immediate value to raw-capture training. NR plus FG is different from our one-pass/two-pass NR teacher modes. |
| Metal/SIMD performance | No demonstrated CUDA, TensorRT, D3D11/D3D12 or stereo-VR speed gain for OpenNR. |
| Packed integer RGB / constant depth | Appropriate only when source representation and depth constancy permit it; do not quantize floating-point captures or discard changing native depth. |

## Bounded next experiment

1. Preserve exact local DLL hash, extracted-weight identity, upstream commit,
   backend/precision and controls. A matching DLL version is insufficient.
2. Compare a small set of native reset-qualified frames with identical source
   region, color/HDR preprocessing and controls. Preserve full-frame context
   where required; independent crop inference is not assumed equivalent.
3. Replay short static and moving sequences using the captured engine motion
   vectors, explicit reset/noise state and separate per-eye history. Verify
   motion units/sign, source rectangles and ordering; include disocclusions.
4. Measure reconstructed-to-native error and inspect faces, tone, both eyes and
   temporal behavior. Keep one-pass and two-pass teacher contracts distinct.
5. Only after acceptable parity, benchmark raw offline generation on our actual
   hardware and consider scaling it. Keep reconstructed outputs in a separately
   identified lineage and validate student changes against native cohorts.

This is a proposed research experiment, not authorization or evidence that it
has run. No source installation, weight extraction, dataset relabeling, training
launch, cloud rental, game/profile change or runtime promotion was performed
for this assessment or documentation update.

## Relationship to earlier research

This note adds the September 7 performance commit and a newer saved training
snapshot to [the earlier DLSS5 recommendations report](DLSS5_LATEST_DEVELOPMENTS_OPENNR_RECOMMENDATIONS_20260907.md).
Its earlier capture-pilot status is historical. The core recommendation remains:
validate MLX-DLSS as an isolated offline reference before depending on its labels.

## September 8 local-status correction

The saved training snapshot referenced above has since been completed and
independently diagnosed. The multi-layer 6,000-step endpoint did not pass the
five-cohort gate. A separate 1,200-step zero-initialized renderer-input stem
experiment also completed; it used native renderer-conditioned captures only as
student inputs, not MLX-DLSS labels, and did not pass the all-five gate. See
[renderer-context conditioning results](RENDERER_CONTEXT_CONDITIONING_20260908.md).

Nothing in this MLX-DLSS assessment authorizes weight extraction, proxy-binary
installation, source replacement, relabeling of native Feature 18 captures, or
runtime deployment. The next safe research step requires new paired native
teacher data or a separately validated causal-state distillation design.

## September 8 isolated parity follow-up

The proposed experiment was subsequently executed in an isolated research
lineage, without touching the active Skyrim profile, native labels or runtime.
The source checkout is pinned to
`4549ce6d99837e4fb182c38a028d8e96bc28c0df`. The active native DLL is an
unknown build despite file version `310,8,0,0`; its SHA-256 is
`e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e` and it
does not match the MLX-DLSS known hash set. The DLL was decoded privately for
comparison only. The resulting logical safetensors file has SHA-256
`058b4fa8a273724c64fe27bdcac4b0f7a1e6bd946f49675deb5259f36724b76c`.

The first short probe showed an apparent improvement, but the broader
calibrated replay is the decision-quality result: 24 eye rows from three
strict sequences changed input-to-native MAE from `0.0234133062` to
recovered-to-native MAE `0.0233862410`. Per-sequence behavior was not stable:
sequence 1 improved `0.0365440 -> 0.0313783`, validation sequence 25 regressed
`0.0128387 -> 0.0164644`, and frozen sequence 31 regressed
`0.0208572 -> 0.0223160`. These data do not validate the recovered graph as a
teacher replacement or a relabeling source. The detailed artifact is
`D:\OpenNR_ExternalResearch\MLX-DLSS-unknown-e16bcf15\parity_3seq_frames4_calibrated\parity.json`.

The isolated dependency path was
`C:\OpenNR\python312_ml_deps_20260908`; it contains the CUDA PyTorch stack and
the additional offline packages required by the existing evaluators. This
follow-up strengthens, rather than changes, the recommendation: keep MLX-DLSS
as a parity oracle only, and obtain exact reset/warm native pairs before
attempting teacher-state distillation.
