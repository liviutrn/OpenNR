# Full-eye temporal/state tranche: training evaluation

Date: 2026-09-10

## Result

The new 16-frame capture tranche is structurally usable and can be read by the
temporal trainer without fabricating 64-frame clips. A bounded new-data-only
continuation was run from the recovered exact-parent/head checkpoint for 400
updates (checkpoint step 800 through step 1200). It did not improve the
tranche's held-out error. The best validation result was the unmodified start
checkpoint; the trained output is not promoted.

The current ordinary 1x MAE target is `<= 0.007`. The new-data-only probe is
well above that target and is evidence against using this small tranche by
itself as a replacement or direct continuation.

| evaluation | step | MAE | temporal-delta MAE | use |
|---|---:|---:|---:|---|
| validation baseline | 800 | 0.01770564 | 0.00513664 | starting control |
| validation | 900 | 0.01931931 | 0.00512546 | descriptive |
| validation | 1000 | 0.02055997 | 0.00511606 | descriptive |
| validation | 1100 | 0.02030937 | 0.00515668 | descriptive |
| validation | 1200 | 0.01948285 | 0.00517837 | descriptive |
| held-out test baseline | 800 | 0.02115525 | 0.00407541 | independent CUDA evaluation |
| held-out test after probe | 1200 | 0.02235354 | 0.00411446 | read once after training |

The 400-step probe took about 231 seconds and reached approximately 9.52 GiB
peak GPU allocation. It used the restored optimizer state and the same 8-frame
temporal objective as the prior joint recipe. The test split was not used for
tuning or checkpoint selection.

## What this means

The new captures are useful information: they provide continuous reset-qualified
full-eye streams, native guide/context arrays, and a safe temporal evaluation
split. However, this nine-sequence tranche is too small and/or distributionally
different to support a new-data-only fine-tune without regression. This does
not prove that a broad mixture continuation cannot help. It means the next
credible training experiment must restore or rebuild a broad sequence-disjoint
corpus and mix this tranche into it while retaining independent validation and
test controls.

No 64-frame recapture is required. The input contract used here is:

- nine real reset-qualified sequences;
- 16 frames per sequence;
- 8-frame windows sampled only within one sequence/eye stream;
- no concatenation across sequences and no synthetic padding;
- initial reset metadata preserved;
- validation and test sequences never sampled for updates.

The 34 all-zero raw-motion tensors are retained. The user confirmed that these
occurred while the headset was intentionally placed on the table, so they are
valid static/state-anchor supervision rather than capture corruption. They are
not counted as dynamic-motion coverage.

## Runtime and integrity

The original training environment was unable to execute CUDA kernels on the
RTX 5070 Ti because it used `torch 2.3.1+cu121` without `sm_120` support. The
isolated `C:\OpenNR\Tools\OpenNRTrainVenv` was upgraded to
`torch 2.7.1+cu128`; an `sm_120` CUDA matrix smoke test and the full model
evaluation then passed. The global Python installation was not changed.

Protected and derived artifacts:

- protected best model: `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
- protected best model SHA-256:
  `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- labeled recovered working checkpoint:
  `C:\OpenNR\Training\recovery\semantic_full_eye_state_short_20260910\recovered_best_all_cohorts.pt`
- recovered checkpoint SHA-256:
  `5D929D2976250D370AF4AD45C248E44F7F75C4ADA8CF3B3EE130D9C1AB583D8B`
- immutable derived cache:
  `C:\OpenNR\TrainingCache\full_eye_temporal_state_tranche_20260910_v1`
- cache `complete.json` SHA-256:
  `4EAFC4509780FF5BC351078341B688CD4E7079D8EA1D1D71FB77C1C2F9E8645E`
- new-data-only probe:
  `C:\OpenNR\Training\semantic_full_eye_state_new_only_20260910`
- CUDA baseline evaluation:
  `C:\OpenNR\Training\semantic_full_eye_state_short_eval_20260910_cuda`

The protected best model was not overwritten. The new-data-only output is a
diagnostic artifact and is not a promoted model.

## Storage note

At report time, free space was approximately 962.8 GiB on C:, 421.7 GiB on E:,
and 2.2 GiB on D:. New training artifacts should remain on C: or E:; D: is
near capacity and should not receive another large cache. No raw capture or
protected checkpoint was deleted as part of this evaluation.

## Data sufficiency recommendation

The current nine-sequence tranche is enough to validate capture integrity, but
not enough to establish a general model improvement. The held-out test contains
only two independent sequences, with sequence MAEs of `0.01220` and `0.03011`.
That spread makes a two-sequence result highly sensitive to scene choice.

These are operational thresholds based on the observed sequence-level variance,
not a formal statistical power guarantee:

- 24 total sequences / 384 full-eye frames: minimum decision tranche; use about
  16 for training, 4 for validation, and 4 for test. This requires 15 more
  sequences beyond the current nine.
- 48 total sequences / 768 full-eye frames: recommended meaningful experiment;
  use about 32 for training, 8 for validation, and 8 for test. This requires 39
  more sequences and gives a materially less fragile held-out result.
- 64–96 total sequences / 1,024–1,536 full-eye frames: stronger promotion-level
  evidence, especially if the target is ordinary 1x MAE `<= 0.007` and a
  convincing teacher/temporal match rather than merely detecting a small trend.

The independent unit is a sequence/scene condition, not an individual frame.
Longer clips from the same scene are correlated and do not replace scene-
disjoint sequences. Keep the real 16-frame burst length; do not extend these
captures to 64 frames just to increase the frame count.

At the current observed storage rate, each raw sequence uses approximately
3.3–3.6 GiB and the derived training cache uses approximately 0.056 GiB. The
recommended 48-total-sequence plan therefore adds roughly 136 GiB of raw data
and 2.2 GiB of derived cache beyond the current nine-sequence tranche. Store it
on C: or E:, not D:.

## Blocker for broad paired continuation

The retained joint checkpoint's metadata still references historical parent and
cohort sources that were removed during the earlier storage cleanup. The exact
parent weights were recovered into the labeled checkpoint above, but several
old cohort source caches are no longer present, so the historical six-cohort
paired loader cannot currently establish its broad no-regression controls. A
future broad continuation must either restore those exact source caches or be
declared a new corpus experiment with new manifests and baselines.
