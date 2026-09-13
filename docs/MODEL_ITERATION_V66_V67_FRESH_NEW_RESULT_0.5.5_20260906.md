# OpenNR distilled-model iteration: v66/v67 fresh-new data result

Date: 2026-09-06  
Scope: offline crop-space training and held-out sequence validation only. This
report does not claim live SkyrimVR activation, stereo-headset acceptance,
frame-time acceptance, or full teacher equivalence.

## Outcome

The newly collected default-setting cohort is structurally sound enough to use,
but neither controlled adaptation probe improved the inherited v65 model. Both
probes were early-stopped at their first meaningful regression/flatness gate.
The current promoted offline candidate therefore remains:

`E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`

The requested MAE `0.011` target remains open. On the previous apples-to-apples
streaming baseline over the new cache test split, v65 measured MAE
`0.021374621`; the remaining reduction required to reach `0.011` is about
`48.5%` relative to that baseline.

## Data used and validation boundary

The fresh source root is:

`E:\OpenNR_Captures_StrictTemporal_0.5.5_20260906`

The full-root structural audit currently contains 359 sequences, of which 354
are temporal-ready; the five rejected sequences remain preserved. The newly
created cohort contains 146 sequences, 145 structurally temporal-ready. The
default teacher-setting subset is organized as:

- 131 structurally complete default-setting candidates;
- 124 clean temporal sequences after excluding suspicious zero-motion or
  invalid-motion content;
- 7,936 frames and 15,872 eye rows in the training cache;
- deterministic sequence split: 79 train, 20 validation, 25 untouched test;
- cache row identity SHA-256:
  `5c5fa28a92c33127005a5900be696d2befa88d8eedc0d51b41819d9b6c0a9f68`.

The 14 sequences captured with reduced local-structure/local-tone/skin settings
remain a separate style-variant cohort. They are not mixed into an
unconditioned default-setting target because the current student has no input
for those teacher-control values.

The content audit found 344 all-zero-motion eye rows and 32 eye rows with
invalid motion pixels in the 131 default candidates. Those rows are retained
in the audit evidence but are not silently admitted to strict recurrent
training. This preserves the native Feature 18 motion-vector contract and
keeps the new test split untouched.

## Controlled training probes

Both probes initialized from v65 and used the new default-setting cache as the
temporal stream. The old strict and spatial caches were supplied only as
regularization sources in v66; v67 disabled spatial sampling entirely.

| Probe | Controlled change | Validation result | Decision |
|---|---|---:|---|
| v66 | All inherited branches trainable; new cache primary temporal stream; v65 capacity/gates retained; 1,500-step plan | step 0: `0.025239196`; step 250: `0.025266717`; step 500: `0.025341261` | Early-stopped at 500/1,500; regression |
| v67 | Inherited spatial/capacity branches frozen; temporal branch only; 2e-7 temporal LR; no spatial steps; 500-step plan | step 0: `0.025239196`; step 250: `0.025241255` | Early-stopped at 250/500; statistically flat |

The v66 run reached a GPU peak of approximately 12.31 GiB. The v67 run reached
approximately 8.42 GiB, so local GPU memory was not the limiting factor for
these probes.

The launcher condition for `--freeze-base-capacity` was also corrected in
`tools/train_capacity_temporal_student.py`: the mode now places temporal
parameters in the optimizer while keeping inherited spatial/capacity
parameters frozen. The script passes Python compilation after this narrow fix.

## Frozen output check

The standard raw-crop evaluator produced the following same-protocol results
for the saved step-0 candidates:

| Candidate | Step | Held-out new-cache MAE | PSNR |
|---|---:|---:|---:|
| v66 best-MAE | 0 | `0.021420813` | `29.95718` dB |
| v67 best-MAE | 0 | `0.021420811` | `29.95718` dB |

These are step-0 inherited-function checkpoints, not learned improvements.
The earlier v65 new-cache streaming baseline (`0.021374621`) was produced by
the temporal streaming evaluator; it should not be numerically compared to the
single-frame raw-crop evaluator above without rerunning v65 under the same
evaluator.

The broad A/B gallery is preserved at:

`D:\.CODEX_Projects\OpenNR-VR\out\fresh_new_v65_v66_gallery_20260906`

Representative files:

- `pair00_seq-1788731910506-107_f1_e0.jpg`
- `pair01_seq-1788731935163-111_f64_e0.jpg`

The sheets show input, v65, v66-best, and Feature 18 teacher. v65 and v66-best
are visually indistinguishable at the sampled locations, while the teacher
continues to show broader local tone, shadow, and material-detail changes.

## Decision and next step

Do not promote v66 or v67 and do not spend a long continuation on either
recipe. More steps on this exact representation are unlikely to close the
gap: prior capacity, loss, and cooldown experiments already showed saturation,
and the fresh-data adaptation curves reproduce that behavior immediately.

The highest-value next step is a capture/representation iteration, not another
blind capacity increase:

1. Preserve the current strict RGB/depth/native-MV capture path and collect
   independent environments with deliberate lighting, material, camera-motion,
   foliage, cloth, face/hair, and high-effect cases.
2. If the renderer boundary permits it, add auditable teacher conditionings:
   albedo, normals, illumination/light features, material/object/light masks,
   artistic-direction controls, and the exact carried history tensor. Record
   shape, coordinate space, range/sign, reset behavior, and hashes for every
   added tensor before training.
3. Extend spatial coverage beyond the single center crop when storage allows;
   a center-only crop cannot teach the model the full-frame distribution even
   though the source render is 2496x2688.
4. Keep the seven suspicious sequences as quarantined evidence. They may be
   recoverable for spatial-only use after row-level motion screening, but they
   must not be admitted to strict temporal loss without a clean native-guide
   audit.

This decision is consistent with NVIDIA's current public DLSS 5 description,
which identifies the current rendered frame, engine motion vectors, carried
temporal state, artistic-direction values, and renderer-derived consistency
supervision as important conditioning/training signals:

- [NVIDIA ADLR DLSS 5 research page](https://research.nvidia.com/labs/adlr/DLSS5/)
- [NVIDIA DLSS 5 product announcement](https://nvidianews.nvidia.com/news/nvidia-dlss-5-delivers-ai-powered-breakthrough-in-visual-fidelity-for-games)

Community reverse-engineering work remains research-only. It provides useful
private Feature 18/runtime-contract clues, but no independently verified,
portable, trainable teacher graph or checkpoint. It does not replace the
native Feature 18 capture path.

