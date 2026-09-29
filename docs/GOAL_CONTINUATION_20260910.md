# OpenNR student continuation — 2026-09-10

## Current outcome

The student has not reached the project target of **ordinary 1× MAE ≤ 0.007**. The best narrow ordinary renderer-pilot number measured in this continuation is **0.011729875** at step 2,400 of the matched scratch-v2 finetune arm. It is about 0.92% below the earlier renderer-focused pilot's `0.011838914`, but the checkpoint fails the broad retained-cohort gates and is not promoted. No runtime or live Skyrim acceptance claim is made.

The six experiments answer the current decision questions:

1. A learned initialization is materially better than a true scratch restart.
2. Adding clean7 at 5% does not improve the ordinary target relative to an old-data-only continuation.
3. Increasing renderer-pilot exposure from 10% to 25% improves the ordinary cohort, but broad MAE/temporal preservation is lost.
4. Freezing the learned temporal parent does not recover the lost broad behavior; it also removes the ordinary-metric benefit of the unfrozen focus arm.
5. A controlled scratch-v2 restart remains materially behind a matched finetune; the finetune's narrow gain still comes with broad MAE/temporal tradeoffs.
6. A matched retention-regularized renderer-focus pair does not recover that
   tradeoff: it remains in the same approximately `0.012` basin and does not
   improve the quality frontier or pass the final temporal gate.

The evidence now points away from more blind steps or another width increase. The remaining gap is more likely a combination of target/cohort coverage, objective allocation, and the lack of sufficiently broad continuous full-eye supervision than simple initialization.

## Immutable controls and safety

The protected production control is unchanged:

- Checkpoint: `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
- SHA-256: `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- Parent checkpoint SHA-256: `2024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60`
- Protected ordinary renderer-pilot validation MAE: `0.013283985`

The six older cohorts, clean7 cache, 18-sequence cache, and all existing checkpoints were read-only controls. No source training data or checkpoint was deleted or overwritten. The current worktree branch was not switched; the concurrent `OpenNR-GEN` task continued on its own isolated files and its GPU use was checked before every local student run.

## Experiment 1 — scratch versus finetune

Full report: [SCRATCH_VS_FINETUNE_RESULT_20260910.md](D:/\.CODEX_Projects/OpenNR-VR/docs/SCRATCH_VS_FINETUNE_RESULT_20260910.md)

Starting from the protected best, the finetune arm loaded the learned parent/head weights with fresh AdamW state. The scratch arm initialized the trainable parent and semantic/tone head anew while retaining only the frozen pretrained DINOv2 encoder. Both arms used the same exact graph, seven-cohort corpus, sequence-disjoint splits, seed `909`, window `8`, burn-in `2`, batch `1`, pixel-only L1 objective, learning rates `1e-4`/`1e-5`, and 1600 steps.

| Step | Finetune renderer-pilot MAE | Scratch renderer-pilot MAE | Finetune old-six mean | Scratch old-six mean |
|---:|---:|---:|---:|---:|
| 0 | 0.013283985 | 0.032923446 | 0.017770087 | 0.028786223 |
| 400 | 0.014060967 | 0.022225801 | 0.018256080 | 0.023344223 |
| 800 | 0.013522282 | 0.019899173 | 0.018158672 | 0.021173259 |
| 1200 | 0.012856951 | 0.017877388 | 0.018077886 | 0.020502571 |
| 1600 | **0.012460920** | **0.016137965** | **0.017834069** | **0.020947025** |

At step 1600, finetune was 29.5% better than scratch on renderer-pilot and 14.9% better on the old-six mean. Scratch did learn from its identity-safe initialization, but it never caught the learned representation. The finetune checkpoint remains experimental because it regressed at least `renderer_state` and `new_pairs` relative to the protected reference and missed the target by a wide margin.

The independent replay of both final checkpoints reproduced recorded validation exactly: `replay_match = true`, `max_abs_difference = 0.0`.

## Experiment 2 — tempered clean7 recovery pair

The recovery pair started both arms from the finetune step-1600 checkpoint:

`C:\OpenNR\Training\semantic_scratch_vs_finetune_20260910\finetune\checkpoint_1600.pt`

SHA-256: `F1DDABE27DE2BDE99CDD876535575B7B19A0BF3259443C2F3B2F19CBA27DB53C`

The control used only the six older cohorts. The arm used the same schedule but replaced approximately 5% of windows with clean7. Both used fresh AdamW state at head `5e-5`, parent `5e-6`, window `8`, burn-in `2`, batch `1`, and 800 steps.

| Step | Old-only control renderer MAE | 5% clean7 arm renderer MAE | Control old-six mean | Arm old-six mean |
|---:|---:|---:|---:|---:|
| 0 | 0.012460920 | 0.012460920 | 0.017834069 | 0.017834069 |
| 400 | 0.012413166 | 0.012501485 | 0.017585929 | 0.017606664 |
| 800 | **0.012020134** | **0.012130885** | **0.017437350** | **0.017548097** |

At the final checkpoint the arm was 0.92% worse than control on renderer-pilot and 0.64% worse on the old-six mean. It did not meet the ordinary target; its final renderer temporal delta MAE was `0.009417196`, and both final broad gates were false. The 5% clean7 recipe is therefore rejected for continuation. It did not justify using the new cohort as a routine training ingredient.

Recovery artifacts:

- Root: `C:\OpenNR\Training\semantic_recovery_from_finetune1600_20260910_retry1`
- Control checkpoint SHA-256: `0E67E0BBBC4247DC7CABF1966FE5ACC23CD19184567B99D2EA77494FFE6C5493`
- Arm checkpoint SHA-256: `DA0AA3E2ADD076BADC287ABBB5447F3F959F9C0A3CBDA2CC79FF0B69EDFD94D1`
- Independent replay: both checkpoints `replay_match = true`, `max_abs_difference = 0.0`

The first recovery launch stopped before training because the original provenance loader saw the post-run bookkeeping patch as a source change. That stopped attempt is retained separately at `C:\OpenNR\Training\semantic_recovery_from_finetune1600_20260910`; the successful retry used a strict compatibility loader that allowed only that known reporting-file hash delta and continued to enforce parent, data, encoder, and model-source hashes.

## Experiment 3 — renderer-pilot-focused exposure

The focus pilot started from the same finetune step-1600 checkpoint, kept all six older cohorts in training, excluded clean7, and changed the sampling distribution from:

`[0.40, 0.15, 0.10, 0.15, 0.10, 0.10]`

to:

`[0.30, 0.15, 0.25, 0.15, 0.10, 0.05]`

for `[prior, high_effect, renderer_pilot, fresh_session, renderer_state, new_pairs]`. It used head `5e-5`, parent `5e-6`, seed `909`, window `8`, burn-in `2`, batch `1`, and 800 steps.

| Step | Renderer-pilot MAE | Old-six mean | Broad MAE gate | Broad temporal gate |
|---:|---:|---:|:---:|:---:|
| 0 | 0.012460920 | 0.017834069 | pass at starting reference | pass at starting reference |
| 400 | 0.012277460 | 0.017888926 | fail | pass |
| 800 | **0.011838914** | 0.017613752 | fail | fail |

Final step-800 validation:

| Cohort | MAE | Temporal delta MAE |
|---|---:|---:|
| prior | 0.018481183 | — |
| high_effect | 0.015020336 | — |
| renderer_pilot | **0.011838914** | **0.009339115** |
| fresh_session | 0.014080584 | — |
| renderer_state | 0.019886364 | 0.007380943 |
| new_pairs | 0.026375129 | — |
| full_eye_pilot / clean7 validation | 0.015106478 | 0.010520645 |

Within Experiment 3, the ordinary metric was the best number measured at that
point, but the old-six mean was still 1.01% worse than the old-only recovery
control (`0.017613752` versus `0.017437350`). The focus arm also fails broad
temporal preservation at step 800. This is useful diagnostic evidence that
renderer-pilot exposure is a real lever, but the current allocation
over-trades generality for the narrow ordinary validation cohort. It is not a
production candidate.

Focus artifacts:

- Root: `C:\OpenNR\Training\semantic_renderer_focus_from_finetune1600_20260910`
- Final checkpoint: `C:\OpenNR\Training\semantic_renderer_focus_from_finetune1600_20260910\focus\checkpoint_800.pt`
- SHA-256: `0E909606F5B3EB5F0890F08326B78E5E8AB66AC35678BDF58A9D307784088FC4`
- Schedule SHA-256: `9DCDD4A001E9F8FA3CC2F1BA5F2AEF2D4C09DEDACB70A1D8C59D5EA87B8F5DE7`

The independent focus replay was briefly deferred while the concurrent GEN task used the RTX, then completed with batch `1` once the device yielded. It passed exactly: `replay_match = true`, `max_abs_difference = 0.0`. Replay artifact: `C:\OpenNR\Training\semantic_renderer_focus_from_finetune1600_20260910\replay\focus_checkpoint_800_replay.json`; artifact SHA-256: `8459B66E50015B60E57D173418E981973D8212E73030C260D54712C1CE3B384A`. The focus checkpoint and recorded validation remain immutable.

## Experiment 4 — parent-frozen renderer focus

This arm used the same starting finetune checkpoint, 25% renderer-pilot sampling, six older cohorts, no clean7, learning rates `5e-5`/`5e-6`, and 800 steps as Experiment 3, but set the temporal/reconstruction parent to `requires_grad = false`. Only the semantic/tone head was optimized.

| Step | Parent-frozen renderer-pilot MAE | Parent-frozen old-six mean | Broad MAE gate | Broad temporal gate |
|---:|---:|---:|:---:|:---:|
| 0 | 0.012460920 | 0.017834069 | pass at starting reference | pass at starting reference |
| 400 | 0.012446964 | 0.017724965 | fail | fail |
| 800 | 0.012463567 | 0.017792601 | fail | fail |

The parent-frozen arm did not reproduce the unfrozen focus gain (`0.011838914`) and still failed broad MAE and temporal preservation. Its final cohort values were prior `0.018037405`, high_effect `0.015022496`, renderer_pilot `0.012463567`, fresh_session `0.014069522`, renderer_state `0.020345155`, new_pairs `0.026817460`, and full_eye/clean7 validation `0.014159395`. Its renderer temporal delta MAE was `0.009472996` and renderer-state temporal delta MAE was `0.007398317`.

The final checkpoint is `C:\OpenNR\Training\semantic_renderer_head_focus_from_finetune1600_20260910\focus\checkpoint_800.pt`, SHA-256 `23A2C2A23F56721E533A78E2B6C75223D887D55B833888374BDFA95967B7BB19`. Independent replay passed exactly with `replay_match = true` and `max_abs_difference = 0.0`; replay artifact SHA-256 is `5B8BA741E60521888F7F9B11D0F24B26D807987365AEC1EF317628CD71C93F2E`.

## Target status and interpretation

| Metric | Current best measured | Required | Status |
|---|---:|---:|---|
| Ordinary renderer-pilot MAE | `0.011729875` at finetune-v2 step 2,400 | `≤ 0.007000000` | not met |
| Old-six broad MAE | `0.017217151` at finetune-v2 step 2,400 | no regressions | not met |
| Broad temporal stability | focus final gate false | no regressions | not met |
| Teacher visual/color match | no new visual A/B completed here | convincing match | unverified |
| Live Skyrim/VR budget | no runtime deployment from these candidates | pass required | unverified |

The narrow number is not evidence that more of the same will reach `0.007`.
The remaining gap from `0.011729875` to `0.007` is `0.004729875`,
approximately 40.3% relative to the current best. A long run could continue
moving the narrow validation number, but these paired tests show that the cost
is broad regression unless the objective or data distribution is changed. The
current evidence does not support a 50,000-step blind extension.

## Storage and concurrent-work safeguards

After the GEN model download and student artifacts, C: had approximately **163.1 GiB free**, above the **100 GiB** guard. No old data or checkpoints were triaged out because the guard was not approached and the retained files remain referenced by controls/reports. Runpod was not used: the local RTX 5070 Ti handled the student graph under roughly 10 GiB, so spending the remaining credit would not be the cheapest option for these runs.

The concurrent GEN process was detected as a real GPU workload (`generate_flux_kontext_targets.py`, about 15.7 GiB allocated), so student replays were delayed rather than forced through it. The student-side processes are now complete; any current GPU use belongs to the GEN task, not this continuation.

## Next high-value action

Do not promote or extend the scratch, recovery-arm, renderer-focus, or parent-frozen checkpoints. The next student-side run should be gated behind one of these substantive changes:

1. a retention-regularized renderer-focused objective that explicitly limits movement on renderer-state/new-pairs and other broad cohorts while increasing ordinary-target exposure; or
2. new scene- and sequence-disjoint native-guide captures with continuous full-eye temporal supervision, then a fresh paired evaluation against the current controls.

The second option is more likely to close a 40.9% relative MAE gap than another pure optimizer continuation. Any GEN targets must first pass the separate teacher-preference, identity, geometry, material, lighting, and stereo-review gate; they must not be mixed into the Feature18 student corpus merely because they exist. The 18-sequence cache and current protected checkpoints remain immutable controls.

All artifacts in this continuation set `test_used = false`.

## Experiment 5 — scratch-v2 versus matched finetune

The bounded scratch-v2 test is complete. It used the exact protected graph,
the six protected old cohorts, frozen DINOv2 features, no test rows, and a
predeclared 3,200-update three-stage schedule. A matched finetune arm started
from the protected overall-best checkpoint and used the same serialized
windows, optimizer, rates, and validation.

| Final arm | Renderer-pilot MAE | Old-six mean | Renderer temporal delta | Broad gates | Decision |
|---|---:|---:|---:|---|---|
| Scratch-v2 | `0.015965142` | `0.019546636` | `0.011119240` | fail / fail | reject |
| Matched finetune-v2 | `0.012004774` | `0.017254557` | `0.009296845` | fail / fail | experimental only |
| Protected reference | `~0.013283985` | `0.017770087` | `0.009722360` | pass at reference | control |

Finetuning was 24.8% better than scratch on the ordinary renderer-pilot
cohort and 11.7% better on the old-six mean. The finetune arm improved five of
six old-cohort MAEs, but `new_pairs` regressed from `0.024374998` to
`0.024936339`, and the `prior` temporal delta regressed from `0.008317676` to
`0.008411688`; therefore the broad MAE and broad temporal gates both remain
false. Neither arm reached the ordinary target `<= 0.007`.

Independent batch-1 replays of both final checkpoints matched their recorded
outputs exactly (`replay_match = true`, `max_abs_difference = 0.0`). The
checkpoints, the protected best, and the 18-sequence cache remain immutable.
The primary result occupies about `10.42 GiB`, calibration about `2.69 GiB`,
and C: remains at approximately `147.3 GiB` free, above the `100 GiB` cleanup
guard. No Runpod credit was spent.

Full report: `docs/SCRATCH_V2_RESULT_20260910.md`.

Decision update: stop random scratch restarts and do not blindly extend this
finetune. The next high-value student experiment requires either a
retention-regularized renderer-focused objective or new scene- and
sequence-disjoint native-guide full-eye temporal/state supervision. Teacher
visual/color resemblance, live Skyrim behavior, and VR-budget acceptance are
still unverified for these candidates.

## Experiment 6 — retention-regularized renderer focus

The predeclared calibration and primary matched pair are complete. Both arms
started from the immutable protected-best checkpoint, used the six protected
cohorts, fresh AdamW state, the same serialized schedule, and 2,400 updates.
The control used pixel-only RGB L1. The treatment added pooled RGB, adjacent
residual temporal, and normalized parameter-retention terms, with the anchor
relaxed only on renderer-pilot training windows.

| Arm/checkpoint | Renderer-pilot MAE | Six-cohort mean | Broad MAE | Broad temporal | Decision |
|---|---:|---:|:---:|:---:|---|
| Protected reference | `0.013283985` | `0.017770087` | reference | reference | safe control |
| Control step 1,600 | `0.011910785` | `0.017220624` | pass at checkpoint | fail | diagnostic only |
| Retention step 1,600 | `0.011962172` | `0.017244745` | pass at checkpoint | fail | diagnostic only |
| Control step 2,400 | `0.011967818` | `0.017245443` | fail | fail | diagnostic only |
| Retention step 2,400 | `0.012020144` | `0.017234301` | fail | fail | broad-mean diagnostic |

The treatment's best narrow value was `0.011962172` at step 1,600; its best
six-cohort mean was `0.017234301` at step 2,400. The matched control was
slightly better on both ordinary and broad mean at the treatment's narrow-best
point, so retention did not create a Pareto improvement. Both final checkpoints
independently replayed with `replay_match = true`, `max_abs_difference = 0.0`,
and `test_used = false`.

Full report: [RETENTION_RENDERER_FOCUS_RESULT_20260910.md](D:/\.CODEX_Projects/OpenNR-VR/docs/RETENTION_RENDERER_FOCUS_RESULT_20260910.md).

Primary root:
`C:\OpenNR\Training\semantic_retention_renderer_pair_20260910`

Independent replay root:
`C:\OpenNR\Training\semantic_retention_renderer_pair_20260910_replay`

Decision update: stop same-corpus optimization at this evidence boundary. The
current best ordinary value remains the finetune-v2 step-2,400 value
`0.011729875`, far above `0.007`. The next run must introduce new information:
continuous scene- and sequence-disjoint full-eye sequences with native
Feature-18 RGB/depth/motion, renderer state, exact reset/warm metadata, and
validated carried-state or state-distillation information. Keep the protected
baseline, finetune-v2 step-2,400, the retention broad-mean checkpoint, the
18-sequence cache, and all source cohorts immutable controls. Teacher
visual/color match, live Skyrim behavior, and VR-budget acceptance remain
unverified.
