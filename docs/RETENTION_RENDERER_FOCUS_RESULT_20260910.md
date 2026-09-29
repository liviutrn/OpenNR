# Retention-regularized renderer focus — result — 2026-09-10

## Decision

The predeclared 400-step calibration and matched 2,400-update primary pair are
complete. Neither arm reached the ordinary renderer-pilot target of **MAE <=
0.007**, neither final arm passed the broad temporal gate, and the retention
objective did not produce a Pareto improvement over the matched pixel-only
control.

This closes the current same-corpus optimization branch. Do not start another
blind extension, width change, scratch restart, or repeated retention run on
this information contract. The next high-value experiment requires new
information: continuous scene- and sequence-disjoint full-eye supervision with
native Feature-18 guides, RGB, depth, motion, renderer-state conditionings,
and reliable reset/warm/carried-state metadata. The existing learned
checkpoint should remain the initialization for that data tranche, with the
old corpus retained as a broad control.

This is an offline validation result. It does not establish teacher visual or
color resemblance, stereo quality, live Skyrim behavior, runtime integration,
or VR-budget acceptance.

## Immutable provenance

- Protected starting checkpoint:
  `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
- Protected SHA-256:
  `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- Architecture: `context_v7_capacity_temporal`
- Cohorts: `prior`, `high_effect`, `renderer_pilot`, `fresh_session`,
  `renderer_state`, `new_pairs`
- Sequence-disjoint validation; frozen-test rows were not loaded.
- Primary runner:
  `tools/train_semantic_retention_renderer_pair.py`
- Primary runner SHA-256:
  `34800615AF4050E982DE732D44E0A67128A1E7E81454A80CBA85F3A14947B4AC`
- Runtime: `E:\XTTS-local\server-env\Scripts\python.exe`, Torch
  `2.8.0+cu129`, local RTX 5070 Ti.
- All primary, calibration, and replay records report `test_used = false`.

The protected checkpoint, six source cohorts, 18-sequence cache, and all
earlier checkpoints were read-only controls. The pair wrote only to new
output roots.

## Calibration

The calibration root was
`C:\OpenNR\Training\semantic_retention_renderer_pair_20260910_calibration_retry2`.
It completed 400 updates in both arms after the correct CUDA/NumPy runtime was
selected. Step zero matched the protected evaluator reference; the retention
anchor had a bounded nonzero response and did not collapse the run.

| Calibration step | Arm | Renderer-pilot MAE | Six-cohort mean | Target | Broad outcome |
|---:|---|---:|---:|:---:|:---|
| 0 | control | 0.013283985 | 0.017770087 | fail | reference |
| 0 | retention | 0.013283985 | 0.017770087 | fail | reference |
| 400 | control | 0.012811570 | 0.017847298 | fail | broad fail |
| 400 | retention | 0.012727867 | 0.017839566 | fail | broad fail |

The calibration justified the predeclared primary run, but it did not suggest
that the target was within reach. Peak GPU memory was approximately 9.92 GiB
for control and 11.47 GiB for retention.

## Primary pair

Both arms started from the protected checkpoint with fresh AdamW state, the
same seed (`910`), serialized windows, learning-rate schedule, validation
cohorts, and 2,400-update budget.

- Control: per-frame RGB L1.
- Retention: RGB L1 + pooled-16 RGB L1 + adjacent residual temporal L1 + a
  normalized trainable-parameter drift anchor to the protected checkpoint.
- Renderer-pilot windows relaxed the retention anchor to permit a target-cohort
  response.
- Validation was run every 400 updates; no validation rows were optimized.

| Step | Control renderer | Retention renderer | Control six-mean | Retention six-mean |
|---:|---:|---:|---:|---:|
| 0 | 0.013283985 | 0.013283985 | 0.017770087 | 0.017770087 |
| 400 | 0.012623880 | 0.012646919 | 0.018526506 | 0.018511442 |
| 800 | 0.012602747 | 0.012625164 | 0.018069602 | 0.018085012 |
| 1,200 | 0.012168767 | 0.012185643 | 0.018375204 | 0.018388567 |
| 1,600 | **0.011910785** | **0.011962172** | **0.017220624** | 0.017244745 |
| 2,000 | 0.012016903 | 0.012088465 | 0.017253947 | 0.017286286 |
| 2,400 | 0.011967818 | 0.012020144 | 0.017245443 | **0.017234301** |

The control has the best renderer-pilot value in this pair at step 1,600. The
retention arm has its best renderer value at step 1,600 and its best six-cohort
mean at step 2,400, so it has no single dominant internal checkpoint. More
importantly, the matched control is slightly better on both ordinary and broad
mean at the retention arm's narrow-best step. The retention term therefore did
not recover the broad/ordinary tradeoff.

### Final held-out cohort comparison

These values are from independent batch-1 replay of the two 2,400-step
checkpoints. The temporal column is the cohort temporal-delta MAE.

| Cohort | Control MAE | Retention MAE | Control temporal | Retention temporal |
|---|---:|---:|---:|---:|
| prior | 0.018134585 | 0.018090529 | 0.008361131 | 0.008351046 |
| high_effect | 0.014432754 | 0.014484230 | 0.007418411 | 0.007426668 |
| renderer_pilot | **0.011967818** | 0.012020144 | 0.009345275 | 0.009380897 |
| fresh_session | 0.013830183 | 0.013991039 | 0.005242401 | 0.005249648 |
| renderer_state | 0.019750497 | 0.019737067 | 0.007380187 | 0.007385743 |
| new_pairs | 0.025356821 | **0.025082798** | 0.010815295 | **0.010812287** |

The final control and retention arms both failed the final broad MAE and broad
temporal gates. The retention arm improved `new_pairs` slightly at the final
checkpoint, but that isolated improvement did not offset its renderer,
fresh-session, and high-effect tradeoffs, and it remained far from the target.
At step 1,600 the broad MAE gate briefly passed in the run log for both arms,
but the broad temporal gate remained false; this is not a promotion condition.

## Independent replay and artifact integrity

The independent replay read only the recorded validation cohorts and did not
construct or read test data. Both final checkpoints reproduced their recorded
outputs exactly:

| Artifact | SHA-256 | Replay |
|---|---|:---:|
| `focus_control/checkpoint_2400.pt` | `0A48442776270C44D0DD4427CD177A05B3A0A7AE0A432856518C54044C853F87` | pass |
| `retention_focus/checkpoint_2400.pt` | `73AF1FFB30CE1071760A334CB71241F239EBF221EB378CEA15AB64407469A324` | pass |

Both replays report `replay_match = true`, `max_abs_difference = 0.0`, and
`test_used = false`.

Replay output:

`C:\OpenNR\Training\semantic_retention_renderer_pair_20260910_replay`

The replay JSON files have SHA-256 values
`A665317FF9581A22A3A5DD6341B0C0941657155824606E099DB183244C2B965D` for the
control and
`D62E84802CEB9774F8BA6EEB72979F1A409F81E6C6C1B390DC0E73FD3767F47C` for the
retention arm.

## Three-checkpoint control set

The requested comparison set is preserved and no file was overwritten:

1. Safe protected baseline —
   `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
   — ordinary reference approximately `0.013283985`, SHA-256
   `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`.
2. Narrow quality frontier —
   `C:\OpenNR\Training\semantic_scratch_v2_vs_finetune_20260910\finetune_v2\checkpoint_2400.pt`
   — ordinary `0.011729875`, SHA-256
   `C499889A889408D259DB07451E19DB5EE7FF41B6BC08DE6E3A7AE148EF252109`.
3. Retention diagnostic, broad-mean choice —
   `C:\OpenNR\Training\semantic_retention_renderer_pair_20260910\retention_focus\checkpoint_2400.pt`
   — ordinary `0.012020144`, six-cohort mean `0.017234301`, SHA-256
   `73AF1FFB30CE1071760A334CB71241F239EBF221EB378CEA15AB64407469A324`.

The retention narrow-best alternative is also immutable at
`...\retention_focus\checkpoint_1600.pt` (SHA-256
`B28D1ABF091894C1CD06E39894FA276EEAC90A31D386AB37EA92BFD6B6EB19A9`, ordinary
`0.011962172`). The matched control's run-local best is likewise retained at
`...\focus_control\checkpoint_1600.pt` (SHA-256
`F8A04119FE21F7D350F2C41E33E85AEE46CBE6EDE661BF60C5DCF5E7ECE3CF18`, ordinary
`0.011910785`). Neither is promoted because temporal and broad acceptance are
separate gates.

## Storage, concurrency, and spend

The completed primary root occupies approximately 8.21 GiB, calibration 2.69
GiB, and replay output less than 1 MiB. C: has approximately 126.1 GiB free,
above the 100 GiB cleanup guard. The two failed environment preflight roots are
retained as small audit records; no older data or checkpoint was deleted because
the storage guard was not approached and the files remain referenced by the
project controls.

The local RTX 5070 Ti handled the graph, so no Runpod credit was spent. The
concurrent OpenNR-GEN task was kept out of the student GPU window and no second
student or GEN CUDA workload was started during this pair.

## Final interpretation

The best number in this branch is still `0.011729875`, which is `0.004729875`
above the `0.007` target, about a 40.3% relative gap. The new retention
objective produced only small movements around the existing 0.012 basin and did
not improve the quality frontier or restore temporal stability. Across the
scratch-vs-finetune, renderer-focus, parent-frozen, and retention tests, the
repeated pattern is that the current corpus can be optimized locally but does
not supply enough information for the desired teacher-like full-eye temporal
match.

Therefore the current same-corpus training goal is stopped at this evidence
boundary. The next student run should be a learned-checkpoint finetune on new
continuous full-eye sequences carrying native Feature-18 RGB/depth/motion,
renderer conditionings, exact reset/warm metadata, and validated carried-state
or state-distillation information. It should be evaluated against all six old
cohorts and the new scene/sequence-disjoint holdout, with the three-checkpoint
control set kept immutable.
