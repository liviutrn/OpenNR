# Renderer-conditioned training pilot — September 7, 2026

## Purpose and authority

User authorized validation and training using the newly collected samples, without requiring another capture session. This bounded local experiment tests whether the six renderer buffers add predictive information to a frozen selected Arm-C model. No cloud rental, production promotion, public-build change, or source-capture deletion is authorized by this recipe.

## Preregistered experiment

- Source: twelve new 64-frame sequences, `seq-1788803746547-1` through `seq-1788803895392-12`, subject to exhaustive file/temporal validation and content audit. Failed sequences remain on disk and are explicitly excluded.
- Parent: `E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\arm_C\best_mae.pt`. All parent weights are frozen. Parent predictions use complete causal streams with independent eye/sequence resets. Refiner output is never fed back into parent state.
- Cache: separate schema `opennr-aligned-renderer-pilot-v1`. RGB/teacher retain original 512x512 color data; depth, exact Feature-18 motion vectors, and all renderer features are mapped from native crop coordinates into the teacher region. Native guide validity masks are propagated during interpolation. Existing caches are unchanged.
- Features: 17 components from six buffers: albedo RGB; decoded signed normal XYZ and roughness; masks RGB; masks2 R; specular RGB; reflectance RGB. Packed alpha is omitted. HDR/mask float features use fixed `x/(1+x)`, without fitting any validation/test distribution. Normals are decoded before resampling. Guides/conditioning use 128x128 feature maps; context uses 96x96.
- Split: deterministic chronological whole-sequence holdouts. With all twelve accepted: seven training, two validation, three frozen test. Both eyes and all frames remain together. Exact duplicate input/teacher pairs crossing holdouts fail cache creation. Near-duplicate scenes can still cross splits; these are same-session pilot results, not independent-scene generalization.
- Two arms: identical 48-wide, three-block quarter-resolution residual refiners. Zero output-head initialization reproduces the cached parent exactly. The control has zero-filled renderer inputs; the conditioned arm receives all 17 renderer components. Both retain RGB, frozen-parent output, and native guides. Same seed 347, pair sampling, AdamW schedule, 1,000 steps per arm. No geometric augmentation is used, avoiding accidental invalid normal/MV transforms.
- Batch: two adjacent-frame pairs (four images). Loss: MAE + 0.12 adjacent error-delta MAE + 0.10 pooled-tone MAE. Learning rate cosine 1e-4 to 1e-5. Gradient norm capped at 1.0; nonfinite values fail the run.
- Validation: complete validation streams every 200 steps; best whole-cohort MAE selects one checkpoint, with untrained step zero eligible. Report per-sequence MAE, PSNR, and temporal-delta MAE. Both selections finish before frozen-test scoring. Test results do not trigger additional tuning in this run.
- Safety: missing renderer features bypass the adapter and return the frozen parent exactly. This is an architectural fallback, not evidence of improved old-domain performance. No legacy frozen-test rerun or old-cohort improvement claim is made.

## Scope of conclusions

The comparison can distinguish a useful renderer-feature signal from a small correction network learning from the new RGB data alone. It cannot establish that this lightweight feed-forward adapter is the best conditioned architecture, that recurrent end-to-end training would behave identically, or that MAE 0.011 has been achieved generally. The same-session sample size and partial G-buffer representation (including visibly incomplete eye/hair appearance) limit conclusions. Any result remains an offline research checkpoint, not a game-ready deployment.

## Reproduction

Implementation: `tools/prepare_conditioning_pilot.py`, `tools/train_conditioning_pilot.py`, and `tools/test_conditioning_pilot.py`. Existing `tools/audit_conditioning_content.py` provides raw content statistics and visual sheets. Cache completion records source metadata hashes, audited payload identities, exact array hashes, guide-mask counts, split membership, and exclusions. The training run records parent/cache/code hashes, settings, status, selected and last checkpoints, metrics, and validation visual samples.

The older eight-frame clips are preserved as prior diagnostics and are not silently relabeled as 64-frame temporal streams.

## Structural gate outcome

Eleven clips passed both exhaustive artifact validation and the strict temporal gate. Sequence `seq-1788803832124-9` failed at frames 2 and 3 with recorded `gpu_query_timeout_or_failure`; 40 raw artifacts are missing. It is preserved and the whole clip is excluded. No frames are stitched across the gap. Thus 704 stereo frames / 1,408 eye rows are available pending final content gates; the deterministic split becomes six training, two validation and three test sequences. No further capture is required to execute this bounded pilot.

The five implementation tests pass, including native-coordinate mapping, normal/HDR transformation, zero-output parent preservation, control-input equivalence, finite gradients, evaluation aggregation and sequence-boundary reset, and a full-size four-image BF16 GPU training step. The refiner has 62,016 parameters; smoke-test allocated GPU memory was approximately 0.362 GiB, not a measurement of parent-inference memory or live VR overhead.

## Content gate outcome

All 11 complete clips passed finite-value and mapped-coverage checks: 8,448 decoded renderer-conditioning payloads (704 frames x 2 eyes x 6 stages). Same-eye/current-frame mean edge correlation exceeded both wrong-eye and adjacent-frame means in each accepted clip. Representative first/last-frame comparisons showed corresponding scene geometry in color and native guides, including camera/character motion. This is diagnostic evidence, not exact synchronization certification.

Sequence 11 has only 46 distinct right-eye `gbuffer_masks2` hashes across 64 frames, but zero consecutive identical payloads in that channel. All other stage/eye streams have 64 distinct hashes, including input/teacher and all other guides for this eye. The almost stationary view and recurring quantized mask content are consistent with this observation; no whole-stream stale-buffer pattern was found. Retain this clip with the caveat, rather than labeling every repeated material-mask value a capture failure.

Selected training sequences: 1–6; validation: 7–8; frozen test: 10–12. Sequence 9 is excluded. Full structural reports, raw statistics, provenance hashes, and per-sequence galleries are in `out/conditioning_64frame_gated_20260907`.

## Completed training result

Both local arms completed 1,000 steps without OOM or nonfinite loss/gradients. Validation selected step 1,000 for both. No optimization occurred after the first frozen-test scoring.

| Candidate | Validation MAE | Test MAE | Test PSNR | Test temporal-delta MAE |
|---|---:|---:|---:|---:|
| Frozen Arm-C parent | 0.019421480 | 0.021267248 | 30.0124 dB | 0.006720773 |
| Control refiner (no renderer channels) | 0.017874353 | 0.018983047 | 30.4697 dB | 0.006756342 |
| Renderer-conditioned refiner | 0.017273429 | 0.021005986 | 30.0407 dB | 0.006820087 |

The unchanged input baseline is MAE 0.032923445 on validation and 0.024675511 on test. All scores use RGB values in [0,1] at 512x512, pixel-weighted across both eyes and all frames, including initial frames. Validation contains 128 stereo frames; test contains 192 stereo frames. These are new same-session holdouts, not the prior project's validation or frozen-test cohorts.

The fresh-data control reduces test MAE by **10.7405%** relative to the parent, with improvements on each of the three test sequences. The conditioned arm improves the test average by only **1.2285%** relative to the parent and is **10.6566% worse than the control**. It regresses relative to the parent on test sequence 12. Its stronger validation score does not establish a general renderer-feature benefit. The pattern is consistent with overfitting/domain sensitivity in this small feature branch; it does not prove the buffers lack useful information or that all conditioned architectures will fail.

Temporal-delta error increases versus the parent by approximately 0.529% for the control and 1.478% for the conditioned arm. Neither is a temporal-quality or production promotion. MAE 0.011 has not been reached. Preserve the control as the stronger offline follow-up candidate; reject this conditioned recipe for promotion. Do not retune against the now-evaluated test split.

## Verification and visual inspection

`tools/verify_conditioning_pilot.py` independently replayed all 256 validation eye frames directly through the frozen causal parent and loaded refiners, resetting each eye/sequence. Fresh parent predictions exactly matched the FP32 parent cache. Missing-feature bypass had maximum pixel difference zero. Direct MAEs agreed with the batched cached evaluator within 6e-11. All five implementation tests passed.

The validation gallery and fixed-frame-32 test galleries show input, teacher, parent, control and conditioned outputs at the same display scale. They are diagnostic image comparisons, not headset acceptance. No sharpening/brightness enhancement was applied to the display sheets. The selected checkpoints, quantitative test results and visual inspection did not trigger further tuning.

## Artifacts and state at handoff

- Cache: `E:\OpenNR_TrainingInputs\RendererConditioningPilotAligned_20260907` (1,408 eye rows; all four array SHA-256 values committed in `complete.json`; zero invalid native depth or motion pixels).
- Run: `E:\OpenNR_Training\renderer_conditioned_refiner_pilot_20260907`.
- Selected control adapter: `control\best.pt`, SHA-256 `d041966aaa3c55204697ad214f1536766fd1ce4eb6c88d723fa937cb76a70521`.
- Selected conditioned adapter: `conditioned\best.pt`, SHA-256 `204773f14e5a44efb5cb200aed7a711f10b82c2184b0cdcd4256c7109bcd8a37`.
- Required frozen parent: SHA-256 `d644d8fe04efe78df37da46451ae3d665fa96707755131fe999419628bb7cf51`. Adapter checkpoints are not standalone parent replacements.
- Evidence: `run.json`, `result.json`, both `history.jsonl` files, `parent_provenance.json`, `direct_validation_verification.json`, `validation_samples.png`, and `samples.html` with three held-out test sheets.
- Timed optimization/validation portions: control 20.59 seconds, conditioned 18.59 seconds. This is possible because the 3.481M-parameter causal parent was frozen and precomputed; exhaustive CPU validation/cache preparation and parent inference are additional time. Peak Torch allocation during the logged training run was approximately 0.389 GiB; this excludes desktop overhead and is not live VR cost.
- Training finished and GPU returned to idle. No RunPod resources were created or used by this task. No original captures, old caches, production models, game settings, runtime DLLs, or public packages were changed or deleted.

No additional capture is required now. The bounded experiment is complete; future work should preserve these holdouts and test transfer on independent data before deployment or a broad MAE claim.
