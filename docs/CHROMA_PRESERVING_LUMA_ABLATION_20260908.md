# Chroma-preserving luminance ablation — September 8, 2026

This report records the completed output-formulation ablation after the
renderer-stem conditioning experiment. It is an offline student/teacher
evaluation. It is not SkyrimVR, headset, stereo-delivery, frame-time,
package, runtime-DLL, or VR-budget acceptance.

## Decision

The ordinary 1× target remains unmet and the luma arm is not promoted.

The final step-1,200 checkpoint is provenance-valid, independently replayed on
all five validation cohorts, evaluated on all five training splits, probed for
branch utilization, and inspected in fixed stereo galleries. It does not reach
`MAE <= 0.011`, does not improve the matched ordinary 1× mean, and does not
produce a convincing teacher visual/color match. The learned branch is not
dead, but its response is too small and too local to justify more steps with
the same frozen parent and data.

The next evidence-backed direction remains new, broader paired
renderer-conditioned temporal data and/or a separately validated teacher/state
distillation design. This output-head ablation does not justify blind width
scaling, a closed DLSS proxy, a native Feature 18 replacement, a production
runtime change, or a Runpod rental.

## Arm and control

Authoritative run:

`E:\OpenNR_Training\stable_unet_chroma_luma1200_20260908_retry7`

Matched control:

`E:\OpenNR_Training\stable_unet_joint_teacher_20260907`

The arm retained the verified 38M stable U-Net and frozen causal parent. It
copied the verified warm-start RGB-affine head and added one zero-initialized
1-channel luminance branch. The branch predicts a bounded luminance gain and
applies it as a ratio to the warm head's RGB output, preserving chroma rather
than adding an unconstrained RGB bias. The 17 renderer channels are present in
the cache metadata but are intentionally ignored by this luma-only arm; this
isolates output formulation from renderer-input conditioning.

Training matched the fresh 1,200-step control: seed 359, cohort probabilities
`30/18/12/20/20`, eight-frame windows with two burn-in frames, BF16, fresh
AdamW at `1e-4`, the existing L1 + pooled-RGB + temporal-error objective, the
same frozen parent, and no frozen-test access. The final checkpoint contains
step 1,200 and has SHA-256:

`ec399f24900b763deb53d7c24f13c77f409275401d48727e5eb64dda0dd5e158`

The selected `best_all_cohorts.pt` stayed at the exact step-zero fallback
(`best_score=1.0`); its SHA-256 is
`fe876ebe800790086428c0a949a1abc472e17e6ec12b82bbf190f3318a2b3902`.

## Step-zero replay qualification

The first implementation used a zero-initialized branch but evaluated the
branch formula even while its weights were zero. That produced harmless
floating-point differences and, more importantly, the exact identity guard
would have suppressed gradients if it remained active during training. The
implementation was corrected before the successful run:

- `exact_zero_bypass=True` is used only for step-zero replay;
- the trainer disables it before optimizer step 1, so the luma branch receives
  gradients;
- checkpoint loading enables the bypass only for a step-zero checkpoint;
- the CPU/GPU smoke test verifies identity, bounded output, and gradients into
  both the original affine head and the luma branch.

The current luma wrapper and plain warm head are bitwise-identical on the same
weights and frames at step zero. The historical control metrics were created
under the older Torch/CUDA stack, so the derived PSNR differs by at most
`0.0002090571` even though MAE and temporal differences are below `3e-7`.
The replay gate therefore keeps `5e-6` tolerances for MAE and temporal error
and records an explicit `5e-4` PSNR-only tolerance for this luma arm. The
recorded replay has no violations:

[step-zero replay JSON](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/step_zero_replay.json>)

This is a metric-stack compatibility note, not permission to ignore a real
output mismatch.

## Held-out validation result

The table compares the final luma arm against the matched control at the same
step count. Negative MAE delta is better. The four ordinary cohorts are
reported separately from the two-pass stress cohort.

| Validation cohort | Matched control MAE | Luma arm MAE | Arm minus control | Luma temporal delta | Temporal delta difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior 1× | 0.0195343183 | 0.0195026512 | −0.0000316671 | 0.0085087328 | +0.0000123983 |
| High-effect 1× | 0.0178832093 | 0.0180219793 | +0.0001387700 | 0.0077267043 | −0.0000039954 |
| Renderer pilot 1× | 0.0148332520 | 0.0148330077 | −0.0000002444 | 0.0098546619 | −0.0000101684 |
| Fresh one-pass 1× | 0.0161590809 | 0.0161295034 | −0.0000295776 | 0.0052887843 | −0.0000061999 |
| Two-pass stress | 0.0439323490 | 0.0438475786 | −0.0000847704 | 0.0271412903 | +0.0000678724 |

The ordinary four-cohort unweighted mean is `0.0171217854`, versus
`0.0171024651` for the control: a regression of `+0.0000193202`. The best
ordinary cohort is `0.0148330077`, still `0.0038330077` above the `0.011`
target. No ordinary cohort reaches the target.

The luma arm is slightly better on prior, renderer-pilot and fresh one-pass
MAE, but regresses high-effect enough to lose the ordinary mean. Its temporal
delta improves on high-effect, renderer-pilot and fresh one-pass, while
worsening prior and two-pass. This is not a broad temporal or quality win.

## Independent verification and fit

The final checkpoint verifier loaded the checkpoint from disk, checked the
recorded source/provenance hashes, and replayed all five validation cohorts:

- prior: `0.0195026512`, verified;
- high-effect: `0.0180219793`, verified;
- renderer pilot: `0.0148330077`, verified;
- fresh one-pass: `0.0161295034`, verified;
- two-pass: `0.0438475786`, verified.

The independent full training-fit replay covered all 229 training sequences
without using the frozen test:

| Cohort | Training sequences | Final train MAE | Final validation MAE |
| --- | ---: | ---: | ---: |
| Prior | 184 | 0.0181889403 | 0.0195026512 |
| High-effect | 17 | 0.0172402230 | 0.0180219793 |
| Renderer pilot | 6 | 0.0146581840 | 0.0148330077 |
| Fresh one-pass | 16 | 0.0218952881 | 0.0161295034 |
| Two-pass | 6 | 0.0446378334 | 0.0438475786 |

The fresh one-pass training split remains harder than its validation split, so
the arm does not show a clean fit/generalization story that would justify
continuing this same recipe.

## Branch utilization

The branch learned nonzero parameters:

- luma-affine weight L2: `0.0156396925`;
- maximum absolute weight: `0.0042114998`;
- bias absolute value: `0.0008378434`;
- nonzero fraction: `1.0`.

On two sampled validation streams and 128 frames per cohort, the learned
branch's output difference from the exact branch-disabled output was:

| Cohort | Learned branch versus disabled output MAE | Total head correction versus frozen parent |
| --- | ---: | ---: |
| Prior | 0.0010365064 | 0.0043956311 |
| High-effect | 0.0009713380 | 0.0045921378 |
| Renderer pilot | 0.0006895097 | 0.0032566564 |
| Fresh one-pass | 0.0004916245 | 0.0018673077 |
| Two-pass | 0.0007613900 | 0.0033993690 |

Thus the luma branch is active, but the response is modest relative to the
remaining teacher error and does not solve the missing spatial/detail/color
behavior.

## Visual and temporal inspection

Fixed stereo galleries were rendered for prior, fresh one-pass and two-pass
examples. The 1× and 2× student columns are temporally/mode-stable and nearly
identical, but both remain visibly darker and less teacher-like than the
teacher on:

- face and skin brightness/texture;
- highlights and shadow separation;
- hair/fur fine appearance;
- mouth/hood-shadow regions in the two-pass case.

Eye 0 and eye 1 sheets show the same conclusion; no unilateral stereo failure
was introduced. The visual gap is consistent with the MAE result rather than a
purely numerical artifact.

- [Gallery index](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/final_gallery/index.html>)
- [Prior eye 0](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/final_gallery/prior-seq-1788671399304-47-eye0.png>)
- [Fresh one-pass eye 0](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/final_gallery/fresh_session-seq-1788829893113-17-eye0.png>)
- [Two-pass eye 0](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/final_gallery/two_pass-seq-1788832836774-8-eye0.png>)
- [Branch utilization JSON](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/luma_branch_diagnostic_final/result.json>)
- [Full training-fit JSON](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/training_fit_final/result.json>)
- [Final checkpoint verification](<E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7/final_checkpoint_verification.json>)

## Public findings relevant to this result

The official [NVIDIA ADLR DLSS 5 description](https://research.nvidia.com/labs/adlr/DLSS5/)
describes a one-step pixel-space diffusion renderer using the current frame,
engine motion vectors, carried temporal state and artistic-direction controls,
with renderer-derived attributes used for training consistency. A
luminance-only output branch tests one narrow part of the color problem; it does
not supply the missing renderer semantics or causal state representation.

The public [MLX-DLSS reference](https://github.com/iamwavecut/MLX-DLSS) remains
useful as an offline parity oracle, but its own documentation does not provide
a validated OpenNR/Skyrim distillation recipe or a drop-in real-time runtime.
The community [neural-upstream project](https://github.com/matiasLombo/neural-upstream)
uses a related hue-preserving luminance-gain idea, which motivated this
ablation, but it is not evidence that the OpenNR student can reach the target.
The [video2dlssnr wrapper](https://github.com/DaniilSokolyuk/video2dlssnr/blob/main/README.md)
and unofficial [DLSS 5 community discussion](https://www.reddit.com/r/nvidia/comments/1w1817k/megathread_unofficial_dlss_5_neural_rendering/)
remain research/discovery sources only.

## Runpod and deployment boundary

No Runpod resource was rented. The local RTX 5070 Ti completed this arm and
all audits, so cloud VRAM would not answer the demonstrated quality failure.
The known upload preflight was far below the required approximately 2.5 Gbit/s
gate for a large cache transfer, and the historical billing records are not a
current-wallet read. The remaining credit is preserved for a future experiment
only if a new dataset or larger validated teacher/state design makes cloud
compute evidence-backed.

No production MGO profile, native Feature 18 resource, runtime DLL, public
package, or SkyrimVR installation was changed.

## Reproducibility pointers

- [Luma head](<D:/.CODEX_Projects/OpenNR-VR/tools/luma_tone_head.py>)
- [Controlled trainer](<D:/.CODEX_Projects/OpenNR-VR/tools/train_renderer_conditioned_stable.py>)
- [Luma branch probe](<D:/.CODEX_Projects/OpenNR-VR/tools/diagnose_luma_branch.py>)
- [Independent verifier](<D:/.CODEX_Projects/OpenNR-VR/tools/verify_renderer_conditioned.py>)
- [Training-fit evaluator](<D:/.CODEX_Projects/OpenNR-VR/tools/evaluate_renderer_conditioned_training_fit.py>)
- [Fixed gallery renderer](<D:/.CODEX_Projects/OpenNR-VR/tools/render_renderer_conditioned_snapshot.py>)

