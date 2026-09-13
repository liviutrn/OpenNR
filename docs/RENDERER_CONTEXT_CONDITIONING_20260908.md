# Renderer-context conditioning endpoint — September 8, 2026

This report records the completed multi-layer conditioning endpoint and the next controlled renderer-input experiment. It is an offline training report, not a SkyrimVR, headset, stereo-delivery, frame-time, package, or runtime acceptance report.

## Decision

The ordinary 1× MAE target of `<= 0.011` was not reached. No checkpoint is promoted.

The current multi-layer arm and the next justified renderer-context arm are fully evaluated on all five validation cohorts, including independent checkpoint replay, temporal metrics, a complete training-split replay, fixed visual galleries, and a renderer-branch utilization probe. The renderer branch learned a nonzero response, but it did not produce a broad held-out quality win or a convincing teacher color/appearance match. More local steps with the same data and frozen parent are not an evidence-backed next move, so this bounded line stops here.

The safe next research direction is new, broader paired renderer-conditioned data and/or a validated teacher/state distillation design. It is not blind width scaling, a DLSS proxy installation, or a production/runtime change.

## Current multi-layer endpoint

Run: `E:\OpenNR_Training\stable_unet_joint_teacher_multilayer6000_20260908`

The 6,000-step arm retained the 38M stable U-Net and added zero-initialized scale/bias controls after 51 GroupNorm layers. It used the verified broad step-5,600 warm start, frozen parent, seed 359, cohort probabilities `30/18/12/20/20`, eight-frame windows with two burn-in frames, BF16, fresh AdamW at `1e-4`, and the existing L1 + pooled-RGB + temporal-error objective. The renderer cache was retained as metadata/data provenance but was not consumed as U-Net input in this arm.

| Validation cohort | Weak control, step 6,000 | Multi-layer arm, step 6,000 | Arm minus control | Arm temporal delta MAE |
| --- | ---: | ---: | ---: | ---: |
| Prior | 0.0211865552 | 0.0205285050 | −0.0006580502 | 0.0087147101 |
| High-effect | 0.0172860518 | 0.0173715550 | +0.0000855032 | 0.0077133583 |
| Renderer pilot | 0.0149215438 | 0.0150178303 | +0.0000962865 | 0.0097937846 |
| Fresh one-pass | 0.0165788035 | 0.0161182648 | −0.0004605388 | 0.0053311373 |
| Two-pass | 0.0445835711 | 0.0458451717 | +0.0012616006 | 0.0296341045 |

This is not an all-cohort win. The final checkpoint replay reproduced all five validation cohorts exactly; `test_used=false`. The final checkpoint SHA-256 is `33b72d09d6f3477e7d31538e6a29ae4ee03182714498bb4593d707b8c6393ffa`.

The response diagnostic found no tanh saturation and only approximately `5e-5` precision-prediction error on the ordinary cohorts. The fixed visual sheets still show a darker, less detailed student than the teacher around faces, skin, hair/highlights and mouth/hood-shadow areas, especially on the fresh one-pass and two-pass examples.

## Next controlled experiment: renderer features at the stem

Run: `E:\OpenNR_Training\stable_unet_renderer_conditioned1200_20260908_retry2`

This was the smallest direct test of the missing renderer-context hypothesis:

- The original 19 input channels remain unchanged.
- The 17 verified renderer channels are appended at the first 3×3 stem convolution, for 36 input channels.
- The 17 new stem-weight slices are zero-initialized and the original 19 slices are copied bit-for-bit.
- The added branch contributes only 2,448 convolution weights; the final teacher-mode head contains 38,479,948 parameters.
- Legacy cohorts receive explicit zero renderer channels; the fresh and two-pass caches use their hash-verified `conditioning.npy` data.
- The parent, cohort membership, validation holdouts, seed, cohort probabilities, loss, window, burn-in, BF16 path, learning rate and AdamW initialization are matched to the fresh 1,200-step control at `E:\OpenNR_Training\stable_unet_joint_teacher_20260907`.
- The sample schedule hash is identical: `14e00f179d446ba8df21fb4213830906b7338b69667dab030aad7966f157c520`.

The direct functional smoke test gave zero max/mean difference between the original and expanded head when the 17 added inputs were zero. The full BF16 step-zero streaming replay differed from the matched control by at most `6.35e-7` in the recorded MAE/PSNR/temporal fields, below the declared `5e-6` replay gate.

### Final held-out result

Negative MAE delta is better. This comparison is against the fresh 1,200-step control, not the unrelated 6,000-step continuation.

| Validation cohort | Fresh control MAE | Renderer-input arm MAE | Arm minus control | Renderer-input temporal delta | Temporal delta difference |
| --- | ---: | ---: | ---: | ---: | ---: |
| Prior | 0.0195343183 | 0.0195801011 | +0.0000457828 | 0.0084830180 | −0.0000133165 |
| High-effect | 0.0178832093 | 0.0177046111 | −0.0001785983 | 0.0077206416 | −0.0000100581 |
| Renderer pilot | 0.0148332520 | 0.0148462412 | +0.0000129892 | 0.0098326674 | −0.0000321628 |
| Fresh one-pass | 0.0161590809 | 0.0162566698 | +0.0000975889 | 0.0052741062 | −0.0000208781 |
| Two-pass | 0.0439323490 | 0.0440758521 | +0.0001435032 | 0.0271282140 | +0.0000547961 |

The branch therefore improved only the high-effect MAE cohort, while its temporal error delta improved on four cohorts and worsened on two-pass. It failed the existing all-five promotion rule. Weighted across the four ordinary 1× validation cohorts, the renderer-input arm is `0.0189790447` versus `0.0189489985` for the matched control; the best individual ordinary 1× cohort is `0.0148332520`, still `0.0038332520` above the `0.011` target. No ordinary 1× cohort reached the target.

### Independent checks

- Final checkpoint replay: all five validation cohorts passed with zero recorded reproduction differences. Final checkpoint SHA-256: `337f7e83fa8a2730f2de6e772934a1f90e09ee2d792555f08fb671710cd75c56`.
- Training-fit replay: prior `0.0183137361`, high-effect `0.0172967046`, renderer pilot `0.0146692882`, fresh one-pass `0.0212567621`, two-pass `0.0438968340`. This is diagnostic only and does not use the frozen test.
- Utilization probe: learned renderer-stem weight L2 `0.3855278790`, maximum absolute weight `0.0268677063`, nonzero fraction `1.0`; on two sampled validation streams per renderer-bearing cohort, actual-versus-zero-conditioning output MAE was `0.0010084041` for fresh one-pass and `0.0007561681` for two-pass. The branch is not inert, but the response does not improve broad held-out teacher match.
- Fixed galleries: [final gallery index](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/final_gallery/index.html>) and [prior face sheet](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/final_gallery/prior-seq-1788671399304-47-eye0.png>). The renderer-conditioned student remains visually close to the warm U-Net rather than moving convincingly toward the teacher; the fresh skin/face sheet remains too dark and the two-pass sheet remains under-matched in color and fine appearance.

## Latest public DLSS 5 / distillation findings

The current NVIDIA research description is consistent with the direction of this experiment: DLSS 5 is described as a one-step pixel-space diffusion renderer conditioned on the current rendered frame, engine motion vectors, carried temporal state and artistic-direction values, with renderer-derived scene attributes used for training consistency. That supports renderer-grounded conditioning as a sound hypothesis, but it also shows why a stem-only input branch on top of a frozen parent is incomplete. See the [NVIDIA ADLR DLSS 5 project](https://research.nvidia.com/labs/adlr/DLSS5/).

The public [MLX-DLSS repository](https://github.com/iamwavecut/MLX-DLSS) now documents a recovered inference graph and reports approximately `0.004–0.005` MAE against the vendor DLL on its own game-render comparisons. Its README explicitly describes the project as not real-time/drop-in/endorsed, uses optical-flow heuristics for its ordinary video path while allowing supplied engine motion, and does not provide a validated OpenNR/Skyrim distillation recipe. It remains an offline research reference only; its labels must not replace native Feature 18 targets.

The public [video2dlssnr wrapper](https://github.com/DaniilSokolyuk/video2dlssnr/blob/main/README.md) and other community DLSS-NR bridges are runtime/inference experiments, not evidence-backed student trainers. The [unofficial Reddit comparison thread](https://www.reddit.com/r/nvidia/comments/1w1817k/megathread_unofficial_dlss_5_neural_rendering/) is useful for discovery only; its unofficial status makes it unsuitable as a quality or safety gate. No closed proxy binary, recovered weight, or external runtime was installed or executed on the known-good OpenNR/MGO path.

## Runpod and deployment boundary

Live Runpod checks found no pods, network volumes or endpoints. The billing query returned historical usage of `$5.8774783390` for its queried period; that is not a wallet-balance read and was not treated as confirmation of the user's stated `$3` remaining. The catalog showed community RTX A6000 around `$0.33/h`, A40 around `$0.35/h`, and L40S around `$0.79/h`, but no exact-path upload preflight was measured. Because the renderer arm fit locally and the controlled cache transfer would consume more time and budget than the added 2,448 weights justify, no cloud resource was rented and no cloud upload was performed.

## Reproducibility pointers

- [Renderer-conditioned implementation](<D:/.CODEX_Projects/OpenNR-VR/tools/renderer_conditioned_stable.py>)
- [Controlled trainer](<D:/.CODEX_Projects/OpenNR-VR/tools/train_renderer_conditioned_stable.py>)
- [Independent verifier](<D:/.CODEX_Projects/OpenNR-VR/tools/verify_renderer_conditioned.py>)
- [Training-fit replay](<D:/.CODEX_Projects/OpenNR-VR/tools/evaluate_renderer_conditioned_training_fit.py>)
- [Conditioning utilization probe](<D:/.CODEX_Projects/OpenNR-VR/tools/diagnose_renderer_conditioning.py>)
- [Endpoint validation JSON](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/final_checkpoint_verification.json>)
- [Step-zero replay JSON](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/step_zero_replay.json>)
- [Utilization JSON](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/conditioning_response_v2/result.json>)
- [Training-fit JSON](<E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2/training_fit/result.json>)

No production model, native Feature 18 resource, active MGO profile, public package, or runtime DLL was changed.

## Superseding output-formulation follow-up

The next bounded output-formulation test also completed and is recorded in the
[chroma-preserving luminance ablation report](CHROMA_PRESERVING_LUMA_ABLATION_20260908.md).
It learned a nonzero luminance response but regressed the matched ordinary
mean, remained well above `0.011`, and did not close the visual teacher/color
gap. This does not reopen the renderer-input line: additional steps with the
same data and frozen parent are not justified. New paired renderer/state data
or a validated teacher/state distillation design is required before another
material experiment.
