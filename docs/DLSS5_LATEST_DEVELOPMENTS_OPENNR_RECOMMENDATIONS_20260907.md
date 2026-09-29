# OpenNR-VR: what the latest DLSS 5 developments change

## Technical summary

The Apple-Silicon reconstruction is the most consequential development in the
watch, but its value for OpenNR is specific: it creates a plausible, portable
offline reference implementation of the same 310.8.0.0 DLSS-NR runtime version
used by our pinned Feature 18 teacher. It does not yet prove a Skyrim-compatible
replacement, a live VR runtime, or a trainable fine-tuning path.

The recommended project decision is therefore:

- **Promote MLX-DLSS to an isolated parity-oracle experiment, not to the live
  renderer.** First verify the exact local DLL hash, then compare the recovered
  first-frame and temporal paths against our native Feature 18 captures.
- **Keep native Feature 18 as the only accepted teacher until Skyrim-specific
  parity passes.** The public implementation reports strong single-frame and
  static-sequence agreement, but motion, jitter, disocclusion, mask behavior,
  and every Skyrim route/control combination remain open.
- **Stop blind capacity expansion as the primary quality strategy.** The latest
  OpenNR status already shows that width, depth, scalar calibration, style, and
  identity pilots have not cleared the two-cohort gate. A recovered teacher
  graph gives us a better next question: whether the student lacks teacher
  structure, history semantics, or renderer context—not merely parameters.
- **Use the second-GPU project for transport and capture ideas only.** Its
  cross-adapter ring, frame seal, fence discipline, skip-to-newest policy, and
  same-frame A/B view are useful design references. Its D3D12/ReShade/color-only
  path is not a SkyrimVR Feature 18 replacement.
- **Use LoRA Dataset Studio as a workflow reference, not as the OpenNR trainer.**
  Its reversible derived-clip workflow and synchronized A/B review are useful;
  its public DLSS feature is not a published paired pixelwise
  student(input) ≈ teacher(output) experiment.

The immediate project-critical dependency is still the prepared renderer-
conditioning capture pilot. Its output root is empty in the current status, so
there is not yet a validated G-buffer cohort to train on. No cloud run or
production/MO2 change is justified by these public developments alone.

## The three developments and their actual OpenNR fit

| Development | What is genuinely new | Fit for OpenNR | Recommended use | Main boundary |
| --- | --- | --- | --- | --- |
| MLX-DLSS | Public source, local DLL-to-logical-Safetensors conversion, executable 71-block graph, PyTorch/MLX/Metal/Core ML backends, and a temporal reference path | **High for offline research; unproven for runtime** | Version-matched parity oracle, graph/feature teacher, and controlled input-contract investigation | One supported 310.8 build; temporal motion/jitter/disocclusion/mask parity is incomplete; A/B/C model variants are not recovered; not real-time in games |
| Neural Coprocessor / MGPU Bridge | A public D3D12/ReShade implementation that moves terminal DLSS-NR work to a second RTX GPU with explicit cross-adapter synchronization | **Medium for capture architecture; low for direct Skyrim integration** | Borrow frame identity seals, fences, stale-frame handling, and same-frame A/B instrumentation | D3D12 only; SkyrimVR is D3D11 with a separate Feature 18 interop path; color-only optical-flow input is not the native guide/history contract |
| LoRA Dataset Studio | A public workflow that keeps originals, commits DLSS-derived clips reversibly, and compares original/rendered video in lockstep | **Medium for review/provenance; low for core training** | Copy the reversible dataset lineage and synchronized A/B review concepts | It does not publish a paired pixelwise distillation loss or a successful DLSS5-to-student result |

This classification is deliberately asymmetric. The first development can
change our model-side research direction because its graph and weights are
close to our teacher version. The other two primarily improve the surrounding
instrumentation and review loop.

## Why MLX-DLSS is the priority experiment

The public project claims a complete 71-block neural-rendering graph and local
conversion of a user-supplied `nvngx_dlssnr.dll` into logical tensors. Its
published README reports about 0.004–0.005 MAE against the NVIDIA DLL on native
game renders, while the recovery notes report 0.0041–0.0048 MAE on five native
game-face crops. Its temporal reference reports 0.0054 MAE / 42.3 dB over a
64-frame static sequence, with vendor-like drift from frame zero. Those are
strong reconstruction results, but they are still the project's own parity
evidence and do not cover motion, jitter, disocclusion, or mask cases.

The version match is particularly valuable for us. Our pinned OpenNR baseline
records `nvngx_dlssnr.dll` version 310.8.0.0, while MLX-DLSS documents 310.8.0.0
as its one supported neural-rendering DLL build. This removes a major source of
uncertainty, but **version equality is not hash equality**. The first check must
compare our baseline SHA-256 with the public tool's accepted build and preserve
the result in a private experiment manifest.

The recovered input description also changes how we should interpret our
current student. The public recovery notes describe 16 base feature channels:
deterministic noise, a constant, current color, reprojected previous output on
temporal frames, style/tone/structure controls, and skin/automatic-mask
controls. In the analyzed configuration, depth is not a direct neural-network
input; motion is used outside the graph to reproject history. That does **not**
mean our captured depth is useless. It means we should separate three questions
that have been mixed together in many black-box implementations:

1. What the vendor graph directly consumes.
2. What the host/renderer must provide to construct the graph's history and
   control resources.
3. What extra renderer signals help a smaller OpenNR student approximate the
   vendor result when hidden mask/history state is unavailable.

Our current student can still benefit from depth, motion, or G-buffer features
as an approximation aid even if the recovered vendor graph does not bind depth.
The correct response is an ablation after parity and capture validation, not
the removal of the existing guide contract.

## What a successful parity harness would unlock

The recovered implementation can answer questions that output-only distillation
cannot answer reliably:

- whether the remaining student error is mainly caused by the 71-block
  appearance transform rather than insufficient width;
- whether our native Skyrim pre-NR color has the expected display/HDR contract;
- whether the captured motion-vector direction, scale, jitter, and crop
  transform match the recovered history reprojection;
- whether the current student is learning hidden history and mask behavior as a
  shortcut that fails outside the training cohort;
- whether selected intermediate activations can serve as a more sample-efficient
  feature-teacher signal than final RGB alone.

The harness should begin with the existing bounded capture pilot, not with a
full-resolution or live replacement. For each short sequence, it should retain
the exact input crop, native teacher crop, motion resource, depth resource,
source rectangle, model-resolution route, style/tone/structure controls, reset
state, and output hashes. The first comparison should use a reset-qualified
first frame. Temporal comparisons should then use the recorded motion with
explicitly tested sign/scale/jitter conventions. No convention should be
silently inferred from a visually plausible output.

The initial result should be classified, not collapsed into one number:

- first-frame RGB parity;
- static temporal drift;
- controlled camera motion;
- disocclusion/occlusion;
- jitter changes;
- style/tone/automatic-mask controls;
- left/right eye consistency;
- crop and full-eye extent behavior.

If the first-frame route fails, the likely causes are version/hash mismatch,
HDR/display preprocessing, control defaults, model-slot choice, or source
subrect semantics. If first frames pass but temporal frames fail, investigate
motion convention, jitter, history filtering, reset lifecycle, and disocclusion
before changing the student.

## The second-GPU bridge: useful architecture, wrong runtime target

Neural Coprocessor reports a meaningful systems result: on the author's dual
RTX 5060 Ti setup, moving the terminal neural pass off the render GPU retained
more of the performance available from DLSS Super Resolution than running the
same pass on the render GPU. The project is explicit that its measurements are
for a D3D12 ReShade add-on, not a native game integration; it sees finished
color and derives optical flow rather than receiving the engine's native depth,
motion, masks, or hidden history.

That makes it unsuitable as an immediate OpenNR runtime path for three separate
reasons:

- the add-on stands down on D3D11 titles, while SkyrimVR's game renderer is
  D3D11 and our working Feature 18 path crosses a separate D3D11/D3D12 boundary;
- a second-card presentation window is not the SteamVR/OpenXR compositor route
  we must validate for headset delivery;
- offloading neural work does not remove that work from the frame budget; it
  changes ownership and adds transport, synchronization, display, and latency
  costs.

The reusable part is the measurement discipline. The project's six-slot ring,
64-byte frame seal, shared fence, skip-to-newest rule, and flight-oriented log
shape address exactly the class of “looks fine on a static frame but is stale or
torn in motion” failures that matter to dataset capture. OpenNR already records
sequence/frame/eye/resource identity and queue/backpressure state, so this is a
targeted hardening reference, not a reason to replace the capture writer.

Do not buy or install a second GPU for this purpose. A future isolated bench may
measure a second-GPU teacher, but only after the single-GPU capture contract,
temporal parity, and live VR acceptance are already understood.

## LoRA Dataset Studio: borrow the review loop, not the training assumptions

The Studio's DLSS feature is useful evidence that a public tool can keep an
original video, create a derived DLSS-rendered version, restore the original,
and compare both clips in step at 1:1. That is directly relevant to OpenNR's
visual quality work because two separately captured game frames are not a fair
A/B pair.

It is not, however, an OpenNR training solution. The public workflow replaces a
clip in a dataset for downstream video-LoRA training; it does not publish a
paired objective in which a student receives the original frame and is penalized
against the DLSS output. We already have the more appropriate primitives:
strict manifests, immutable raw captures, sequence-level splits, cache hashes,
native guide resources, and independent two-cohort validation.

The useful project-level adoption is small and reversible:

- preserve source input and teacher output as immutable siblings;
- make any derived student/recovered-teacher output a new lineage node, never an
  overwrite;
- provide synchronized sequence playback with a same-frame wipe or split view;
- show route, reset, eye, source rectangle, control values, and validation state
  beside the image rather than relying on filenames;
- allow restoration of the original capture after any visualization or
  pre-processing experiment.

## Current OpenNR state and decision implication

The current project evidence points away from more blind model scaling. Arm C
was the selected width result, but the independent seed-338 run did not beat the
seed-337 Arm C reference on both validation cohorts. The latest local pilots for
effect emphasis, identity weighting, conservative continuation, style/context
modulation, and depth expansion likewise did not produce a two-cohort promotion.
The current status therefore pauses further cloud work until renderer-derived
conditioning data is captured and validated.

The renderer-conditioning probe is correctly staged as a bounded, capture-only
experiment: eight frames, one 512×512 crop, both eyes, raw G-buffer stages plus
the existing input/teacher/depth/motion resources. Its output root is still
empty. That means the next safe action is capture and audit, not training, model
replacement, or package editing.

The public DLSS5 developments strengthen that decision. They provide a way to
test the teacher contract and potentially expose useful internal features, but
they do not make the pending renderer capture unnecessary and do not prove that
an external implementation can carry Skyrim's stereo, temporal, compositor, or
VR-budget requirements.

## Recommended execution sequence

| Priority | Action | Why now | Acceptance gate | Do not do |
| --- | --- | --- | --- | --- |
| P0 | Run the prepared renderer-conditioning capture pilot and validate all six G-buffer stages against the existing input/teacher/depth/MV rows | It is the current highest-value missing evidence and is already isolated | Eight-frame sequences, initial `[true, true]` reset, contiguous IDs, both eyes, identical source rectangles, finite/nonempty typed tensors, no hidden drops | Do not train on unvalidated G-buffers or expand the existing 64-frame root with the 2.5× volume increase |
| P0 | Build a read-only MLX-DLSS 310.8 parity harness from the user's own DLL | Version match makes this newly tractable | Exact DLL hash accepted; first-frame comparison against native Feature 18 on the same crops; private manifest records model/control/route identity | Do not commit extracted tensors, install an external runtime into Skyrim, or call the Apple/portable path a live replacement |
| P0 | Calibrate temporal replay with strict captures | The recovered model's largest open risk is the host-side history contract | Reset, static 64-frame, controlled motion, jitter, and disocclusion cases are separately measured; no guessed MV sign/scale | Do not use optical flow as a substitute for the exact Feature 18 motion resource in the acceptance path |
| P1 | Run a recovered-teacher feature/adapter experiment | It may improve sample efficiency more than another capacity ladder | One-step gradient smoke; selected intermediate outputs stable; student candidate must beat the parent on both prior and new validation cohorts | Do not full-fine-tune the 71-block graph before differentiability, memory, and parity are proven |
| P1 | Run G-buffer ablations after capture | Tests whether renderer context helps the compact student even if it is not a direct vendor input | RGB/native-guide baseline, +depth, +G-buffer subset, and combined candidate on frozen two-cohort gates | Do not interpret a lower training MAE or new-cohort-only gain as promotion |
| P2 | Add only the transport/review ideas that address observed failures | OpenNR already has a functioning capture contract | Same-frame A/B, producer/consumer timestamps, seal/ordering diagnostics, and stale-frame counters improve a real identified failure | Do not transplant the D3D12 bridge or create a second `CommunityShaders.dll` owner |
| P3 | Consider a dual-GPU teacher bench only as a separate performance study | It could reduce teacher contention, but not teacher cost or VR compositor cost | Hardware, D3D12 route, cross-adapter transport, latency, and headset artifacts measured independently | Do not purchase hardware or claim VR-budget improvement from FPS alone |

## Model and data definitions for the next comparison

The next reportable experiment should keep these quantities separate:

- **Native teacher:** the actual Skyrim/Open Shaders Feature 18 output captured
  from the pinned 310.8 baseline.
- **Recovered teacher:** MLX-DLSS output from the locally extracted 310.8
  checkpoint, with its own preprocessing, temporal state, and provenance.
- **Student:** the compact OpenNR model, including any guide/G-buffer inputs
  and recurrent state.
- **Offline runtime:** TensorRT/D3D12 or PyTorch timings on recorded pairs.
- **Live acceptance:** renderer ownership, Feature 18 replacement semantics,
  stereo delivery, headset image/comfort, compositor timing, and VR frame-time.

Parity and quality should be reported at the same grain: sequence, frame, eye,
crop/source rectangle, route, and control preset. Report MAE/PSNR or perceptual
metrics alongside changed-region and low-effect bands, but do not use one global
mean to hide temporal drift, eye asymmetry, or low-effect regressions.

## Limitations, legal boundary, and open questions

The public projects are external research evidence, not audited OpenNR
components. Their measured numbers come from their own machines, captures,
drivers, and routes. The MLX-DLSS source is Apache-2.0, but its documentation
states that model packages built from vendor libraries retain vendor terms. The
NVIDIA RTX SDK license also places restrictions on reverse engineering,
redistribution, modification, and use outside its grant. For OpenNR, the safe
boundary remains: use only locally owned inputs, keep extracted weights and
vendor binaries private, do not commit or redistribute them, and do not run
untrusted proxy packages on the known-good MGO installation.

Open questions that can change the recommendation are:

- Does the current baseline DLL hash match the one MLX-DLSS supports, or only
  the version string?
- Does the recovered first-frame preprocessing reproduce Skyrim's HDR/display
  contract and the exact Feature 18 source rectangle?
- Does the recovered temporal path match native Skyrim output under real MVec,
  jitter, motion, and disocclusion rather than static color sequences?
- Are the public controls and model slot 0 equivalent to the active OpenNR
  settings, and can any Model A/B/C behavior be recovered without guessing?
- Which recovered intermediate activations are stable enough to supervise a
  compact student without importing the full graph's runtime cost?
- Do the newly captured G-buffers improve both validation cohorts, or do they
  merely let the student memorize the current scene mix?

## Bottom line

Use the reconstruction breakthrough to change the next experiment from
“increase student capacity and hope” to “validate a version-matched recovered
teacher, then distill structure and history deliberately.” Keep the current
native Feature 18 capture and strict two-cohort gates as the authority. Borrow
the second-GPU project's instrumentation discipline and LoRA Studio's reversible
A/B review mechanics, but do not import either project's runtime assumptions
into the OpenNR production path.

