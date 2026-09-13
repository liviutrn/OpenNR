# OpenNR latest findings and next steps

## Superseding update — temporal-delta continuation and runtime handoff

The matched temporal-delta pair from the rebalanced absolute-step-3,200
checkpoint completed at step 4,000 after being paused for the isolated TensorRT
build. Doubling the temporal-delta weight from `0.12` to `0.24` produced only a
small mixed change: the boosted arm improved prior, high-effect, fresh-session
and new-pairs against its matched baseline, while slightly regressing the older
renderer and renderer-state cohorts. Neither arm improved all six cohorts from
the step-3,200 candidate start, and every cohort remains above ordinary 1× MAE
`0.011`. The pair is retained as research evidence and neither checkpoint is
promoted. See the [temporal-delta continuation report](SEMANTIC_DELTA_CONTINUATION_20260908.md).

The runtime task completed its isolated TensorRT work while training was
paused. The validated candidate is the 33% FP16-I/O builder-opt5 engine with
native guides retained; its preserved-capture sequential-stereo forward median
is about `17.008 ms`, and the native TensorRT ABI probe passed. The exploratory
FP8/Q-DQ build was stopped after repeated TensorRT reformat/fallback failures;
no FP8 engine was accepted. This is offline runtime evidence only, not live
Skyrim/headset acceptance. The next quality step is a small, separately
budgeted full-eye temporal pilot; three-second sparse snapshots may inform
global spatial/color context but cannot replace contiguous recurrent bursts.
The live profile is now armed for the bounded one-button version of that pilot:
80 Hz eligibility, 240 accepted samples, both eyes, native Feature 18 guides,
renderer conditionings, and one periodic full-frame master at sample 240. The
burst key is `\` (`220`), the new root is
`C:/OpenNR_Captures_FullEyeTemporalPilot_20260908`, and the applied profile is
hash-verified with a rollback copy. The exact settings, storage rationale and
post-capture gate are in the [pilot setup report](FULL_EYE_TEMPORAL_PILOT_SETUP_20260908.md).
The disabled-by-default config copy passed the validator with no warnings.

A separate runtime task is currently finishing an isolated A/B backend-route
build against the validated TensorRT artifact. It is kept outside the active
MGO installation and has not launched Skyrim or started a GPU training job;
the newly armed capture is therefore idle until that route work is complete.

## Superseding update — mixture endpoint and whole-eye context study

The longer hard-cohort mixture pair completed at absolute update 3,200. The
rebalanced candidate improves MAE over the common start on all six ordinary
cohorts and reduces renderer-state below its common-start value, but two
temporal deltas regress slightly and the candidate is worse than the matched
original-mixture arm on prior, older-renderer and new-pairs. It is a useful
research checkpoint, not a promotion; every cohort remains above the `0.011`
target. Exact metrics and the endpoint paths are in
[the mixture/context report](SEMANTIC_CONTEXT_AND_MIXTURE_20260908.md).

The existing full-resolution masters also support a controlled global-context
study. On all 352 sequence-disjoint spatial validation patches, true whole-eye
RGB context reduced the verified semantic step-1200 model's MAE by 1.936% in a
fixed inference comparison. After identical 800-step spatial training, the
full-eye arm remained 0.480% better than the crop-context arm, but the
sequence-level direction was mixed (two of four improved, two regressed). This
supports a small, separately budgeted full-eye temporal pilot later; it does
not justify a large sparse capture or mixing three-second snapshots into the
current recurrent cohorts.

Storage reached about 1 GiB free during the paired work. I removed only the
unreferenced derived `dynamic_guides_v1` and `RendererPairsAligned_20260908`
caches after preserving metadata and verifying absence; raw full-resolution
masters and active strict caches remain. C: returned to about 117 GiB free.
The next bounded training comparison is a matched temporal-delta continuation
from the rebalanced endpoint. Runpod remains unused.

## Active continuation superseding the previous stopping point

### Latest verified training state

The seed812 paired duration continuation completed absolute update4000. The joint endpoint independently replayed exactly, but no checkpoint reached the all-cohort target: the best accepted joint checkpoint remains update1200 at MAEs 0.018173/0.015693/0.012690/0.014377/0.020027/0.028111 in canonical cohort order. Update3200 has the lowest mean MAE ratio but fails renderer-state retention; update4000 leaves new19 at 0.029274. Longer affine-head training alone is therefore insufficient.

A zero-initialized native-resolution residual extension was tested from the verified joint update1200 checkpoint. The GPU smoke was bitwise identical at start and the predecessor replay reproduced all six validation metrics exactly, but its update1600 and update2000 checkpoints both failed the all-cohort retention gate; it is rejected as a broad fix. A separate teacher-tone-weighted loss pilot also failed the gate at update1600, improving high-effect/new19 while worsening four other cohorts. Neither branch is promoted. See the replication report for the complete metrics. The next data decision is a controlled whole-eye-context study using existing full-resolution masters; no new sparse capture is justified yet.

A hard-cohort mixture pilot is the current promising direction. Raising renderer-state and new19 sampling to0.20 each improved their update1600 MAEs versus a fresh original-mixture control by0.000642 and0.001997, respectively, while keeping their temporal errors lower than control. It worsened prior/older-renderer MAE and leaves renderer-state just above common start, so it is not promoted. A longer paired mixture continuation is warranted before deciding whether better exposure can close the broad gap.

### Current update: independently verified seed812 endpoint and longer paired run

The seed812 replication is complete at update1200. Independent replay reproduced MAE, PSNR and temporal error exactly on all six ordinary validation cohorts. Joint MAEs are0.018172906 prior,0.015692761 high-effect,0.012689539 older renderer,0.014377497 fresh session,0.020027444 renderer-state and0.028111196 new19. All six MAEs and temporal errors beat common start; five MAEs and all six temporal errors beat matched control. New19 MAE loses to control and worsens from joint step800. No cohort meets0.011.

Both arms completed the restored optimizer/RNG continuation to absolute update4000, retaining every evaluated checkpoint and original sequential execution. This confirmed that duration alone does not solve the broad validation tradeoff. See [full replication and continuation record](SEMANTIC_PARENT_REPLICATION_20260908.md). The [batching benchmark](SEMANTIC_WINDOW_BATCHING_20260908.md) passed its approximate numerical screen and measured1.385x faster joint updates on one training window; it was not used in the duration comparison and is not inference/VR evidence.

Direct inspection of new19 sequence13 left-eye frame64 still shows the student cart wood darker and less warm than the teacher, with ground/stone tone differences. Static sheets do not establish temporal/headset acceptance. The verified endpoint SHA256 is `fa8a2497e0f89c25dada3d1007fbbf7981fe1c9a2fe2f8fb6c5200ec3ab75bb9`; replay evidence and48 sheets are under `C:/OpenNR/Training/semantic_parent_seed812_joint1200_20260908/independent_replay`. C: had120.11GiB free before continuation. No data was removed and no Runpod credit spent. The goal remains active and unmet.

The following paragraphs preserve the earlier pilot and preparation snapshot; running/prepared statements there are superseded by this update.

The September8 follow-up found19 new strict64-frame clips and an initialization defect in the previously rejected temporal-only continuation: its capacity architecture did not match the parent. The corrected run preserves all304 parent tensors exactly. Independent replay improves four ordinary cohorts slightly and regresses on the older renderer cohort, so it remains unpromoted. All19 new clips passed structural and decoded content audits; their strict and aligned renderer caches use12/3/4 sequences. The formal audit found zero exact reset/warm pairs. See [exact-parent correction and results](EXACT_PARENT_CONTINUATION_20260908.md).

The matched [native residual experiment](NATIVE_RESIDUAL_ABLATION_20260908.md) completed400 steps per arm, with identical initial outputs and sample schedules. The native output regressed against the affine control on all six ordinary cohorts; independent six-cohort replay passed, and the endpoint remains rejected. A [context extent diagnostic](CONTEXT_EXTENT_DIAGNOSTIC_20260908.md) found a13.1% gain from true full-eye RGB context on52 fixed training patches, but this did not replicate on eight spatial-validation patches: MAE worsened from0.0329101 to0.0336674. Current crop caches contain only crop-derived RGB context; the diagnostic establishes sensitivity, not a general quality gain.

The [frozen semantic-feature comparison](SEMANTIC_FEATURE_ABLATION_20260908.md) completed 400 steps per arm. Pretrained DINOv2 conditioning improves five of six cohorts against common start and four against its matched random-encoder control. Its registered training-subset probe confirms a useful learned response on all six subsets. A subsequent projection-only comparison completed 1,200 steps per arm and independently replayed exactly. It improves five MAEs against both references, but renderer-state MAE regresses and temporal error worsens on all six cohorts. A fixed feature-history probe slightly improves MAE and temporal error on six training subsets; it remains unvalidated on holdouts.

The [joint-parent pilot](JOINT_PARENT_SEMANTIC_PREPARATION_20260908.md) completed 400 updates at 9.92 GiB peak allocation and independently replayed exactly. It improves MAE and temporal error on all six ordinary cohorts against common start. Compared with its matched frozen-parent control, four MAEs and all six temporal errors improve; fresh-session and new19 MAEs regress slightly. A [new-seed paired replication](SEMANTIC_PARENT_REPLICATION_20260908.md) is now running for 1,200 updates per arm, with optimizer/RNG state saved for a later evidence-led continuation.

The seed812 frozen-parent control has completed: five MAEs improve, renderer-state worsens to0.021030, and all six temporal errors worsen. Its parent/encoder freeze audit passes. The paired joint arm is running. An [optimizer/RNG-preserving continuation](SEMANTIC_PARENT_CONTINUATION_PROTOCOL_20260908.md) is prepared, with three CPU restoration property tests and an exact real-checkpoint sample-schedule preflight; a longer phase awaits the paired results.

### Latest independently replayed endpoint: jointly trained parent and semantic head

| Ordinary validation cohort | Verified common start | Joint endpoint |
|---|---:|---:|
| Prior |0.019231266|0.017920465|
| High-effect |0.017656344|0.016532684|
| Older renderer |0.014859464|0.014176818|
| Fresh September7 |0.016249614|0.015512909|
| Renderer-state September8 |0.020117967|0.020089761|
| New19 September8 |0.029031637|0.028102639|

This endpoint is not promoted: its two control regressions, small renderer-state retention margin, visible facial/scene tone differences and remaining gap to 0.011 require further work. The joint run selects step400 as its research candidate, with the common-start fallback preserved and runtime deployment unchanged. The projection-only arm remains a separate tradeoff: its newest-cohort MAE is lower at0.024893, but it fails renderer-state retention and temporal checks. No frozen tests were used in these continuation experiments. No new runtime or capture configuration was installed.

Local storage remains sufficient (approximately C:122 GiB, D:40 GiB, E:33 GiB, G:38 GiB free at this checkpoint). No data was deleted and no Runpod rental was made; the user's $3 authorization remains unspent. Historical statements below that paired capture is the only executable next step are superseded by the new data and experimental evidence above. Ordinary 1× MAE <= 0.011 and convincing visual/color/temporal match remain unmet.

The following is the earlier September 8 snapshot, preserved for historical context: multi-layer, renderer-input and chroma-preserving luma arms were complete before the active continuation above.

## Technical summary

The MAE 0.011 goal remains unmet. The weak-conditioning 6,000-update endpoint, the stronger multi-layer 6,000-update endpoint, and the next zero-initialized renderer-input 1,200-update arm all failed the all-five promotion gate. The renderer-input branch learned a measurable response but did not improve broad held-out teacher match or visual/color resemblance. No model is promoted and no runtime path changed.

## Scope and measurement

Ordinary MAE measures student-versus-teacher RGB error on the normalized 0–1 scale; lower is better. It is not the compound optimization loss. Full evaluations use 64-frame causal sequences and both eyes. Five training cohorts contain 184/17/6/16/6 sequences; validation contains 47/5/2/5/2. Sequence holdouts are separate, but same-session scene similarity remains a limitation. Frozen tests are not used for tuning. Normal 1× and amplified 2× results must remain separate; a pooled score must not hide normal-mode regressions.

The 27 new one-pass sequences and 10 accepted two-pass sequences are converted, hash-verified and registered. Two additional two-pass captures remain preserved and excluded: one incomplete capture and one conservative all-zero left-eye AO exclusion, which is not proof of corruption. Raw data and the public/runtime builds were not changed.

## Completed duration experiment: fitting improved, held-out quality did not broadly improve

At update 6,000, weak-conditioning validation MAE is 0.021187 prior, 0.017286 high-effect, 0.014922 older renderer, 0.016579 fresh one-pass and 0.044584 two-pass. Only high-effect beats the common starting checkpoint. The selected checkpoint remains the step-zero fallback; final-checkpoint diagnostics deliberately measure step 6,000 instead.

Full two-pass training MAE decreased from 0.044466 at update 1,200 to 0.038867 at update 6,000. Fresh one-pass training MAE is 0.019575 at the endpoint. This is real fitting progress, but it does not establish generalization or useful transfer from 2× to 1×.

The fixed-subset two-pass mode-switch response grew from approximately 0.000050 to 0.000464, rather than remaining unchanged. It is still small in absolute terms. These are sensitivity measurements on six selected training images per cohort, not full training MAE. Previously inspected face sheets still show substantially stronger teacher appearance.

Independent final checkpoint replay reproduced all 15 validation MAE/PSNR/temporal values exactly. Full training-fit evaluation covered all 229 training sequences. The final checkpoint SHA256 is `3f006f2c0c4e986fdd4bb21c79b7296d9011b53978db2b593c1866c56261ee14`.

## Stronger conditioning at update 400: essentially tied with control

The table uses matched updates and identical sample hashes; negative arm-minus-control MAE is better. Exact lookup is important here because all differences are below 0.000008—too small to justify a meaningful-win claim.

| Cohort | Weak control | Multi-layer arm | Arm minus control |
|---|---:|---:|---:|
| Prior | 0.019768463 | 0.019774348 | +0.000005885 |
| High-effect | 0.018248146 | 0.018247275 | −0.000000871 |
| Older renderer | 0.014819801 | 0.014812318 | −0.000007482 |
| Fresh 1× | 0.016091040 | 0.016088123 | −0.000002917 |
| Two-pass | 0.044030793 | 0.044035877 | +0.000005084 |

Prior, high-effect and two-pass remain worse than their common starting values. Update 400 is ineligible for promotion. Temporal differences versus control are also tiny, at most approximately 0.00000165 in absolute value. This is one early checkpoint and one seed; neither a conditioning benefit nor a final null has been established. The recorded history comparison does not replace independent checkpoint replay.

## Experimental design: change conditioning only

Retain the 38M U-Net backbone and stem control; add zero-initialized per-channel scale and bias after 51 GroupNorm layers. This adds 22,688 parameters, bringing the head to 38,500,188 parameters. Input features, backbone dimensions and output formulation are unchanged. The retained renderer-feature cache is not an additional model input in this experiment.

Both trajectories start from the verified broad step-5,600 head and frozen parent. Seed 359, cohort probabilities 30/18/12/20/20, uniform within-cohort sampling, BF16, eight-frame windows with two burn-in frames, AdamW at 1e-4 and the L1 + 0.5 pooled RGB + 0.12 temporal objective remain unchanged. The weak control restored optimizer/RNG at 1,200; the new arm runs from the same original warm start with fresh AdamW, not from the weak 6,000 endpoint.

All 15 initial validation values match exactly. Update-400 sample and base-sample hashes, cohort draws and hard-draw counts match the control. CPU identity, gradient and checkpoint-state tests passed. Shared-backbone updates can still change 1× output even though the new controls are bypassed in 1× mode. Initial GPU execution is verified, not deployment or headset readiness.

## Next steps and decision gates

1. Continue the existing local arm unchanged to 6,000 updates. Do not restart the optimizer, alter sampling/loss, add 3× data or scale the backbone during this comparison.
2. Compare update 800, 1,200 and every later 400-step checkpoint against the matched weak control. Preserve per-cohort MAE, relative improvement from step zero, temporal error and sample/exposure checks.
3. At a useful saved checkpoint, make fixed-scene 1×/2× visual and mode-response comparisons. Run GPU diagnostics sequentially, without competing with the active trainer. A mode response that is merely larger is not enough; it must move toward the requested target.
4. At completion, independently replay the selected candidate and/or diagnostic endpoint, evaluate ordinary full training MAE, and inspect faces, skin tone, highlights, mouth/hood shadows and temporal behavior. Clearly distinguish selected checkpoint from final checkpoint.
5. Require improvement across all five MAE cohorts under the existing promotion rule. Inspect temporal and visual results separately; do not call offline success runtime acceptance.

If conditioning consistently improves fitting and validation while preserving 1×, pursue replication and a controlled follow-up. If it improves fitting without validation, investigate the newly exposed distribution/generalization gap. If it remains null, inspect conditioning utilization and output limitations before choosing another experiment; a null alone does not prove a capacity ceiling. Establishing that 2× data helps 1× ultimately requires a matched no-2× control.

## Evidence pointers

- `out/joint_teacher_data_20260907/conditioning_comparison.json`: paired update-zero and update-400 audit, source hashes and temporal deltas.
- `E:/OpenNR_Training/stable_unet_joint_teacher_duration6000_20260907/final_checkpoint_verification.json`: exact final replay.
- `E:/OpenNR_Training/joint_teacher_duration_final_training_fit_20260908/result.json`: complete endpoint training-fit metrics.
- `E:/OpenNR_Training/joint_teacher_duration_final_response_20260908`: fixed-subset response and precision diagnostic.
- `E:/OpenNR_Training/joint_teacher_duration_final_gallery_20260908/index.html`: previous endpoint visual comparisons, not new-arm output.
- `E:/OpenNR_Training/stable_unet_joint_teacher_multilayer6000_20260908`: active run configuration, status and history.
- `docs/TWOPASS_DATA_INTEGRATION_20260907.md`: preserved chronological integration history.

No new cloud spending, test evaluation, data deletion or runtime/public-build changes are part of this update.

## Superseding result: chroma-preserving luminance-output ablation completed

The follow-up luma-only arm completed at `E:/OpenNR_Training/stable_unet_chroma_luma1200_20260908_retry7`. It retained the verified stable U-Net and frozen parent, copied the warm RGB-affine head, and added a zero-initialized bounded luminance-gain branch that applies a ratio to the warm head's RGB output. It intentionally ignored renderer channels so output formulation was isolated from the preceding stem-conditioning arm.

The final step-1,200 checkpoint replayed all five validation cohorts and all 229 training sequences without frozen-test access. Its MAE was `0.0195026512 / 0.0180219793 / 0.0148330077 / 0.0161295034 / 0.0438475786` for prior, high-effect, renderer-pilot, fresh one-pass and two-pass cohorts. The ordinary four-cohort mean was `0.0171217854`, versus `0.0171024651` for the matched control, so it regressed by `0.0000193202`. No ordinary cohort reached `0.011`; the best was `0.0148330077`.

The branch was active rather than inert: its weight L2 was `0.0156396925`, with sampled learned-branch-versus-disabled output MAE from `0.0004916245` to `0.0010365064`. It still failed to produce a broad held-out win. Temporal delta improved on three ordinary cohorts and worsened on prior and two-pass. Fixed eye-0/eye-1 galleries show the same remaining darker, less detailed face/skin/highlight/fur and shadow mismatch, with mode 1×/2× outputs close to one another.

The step-zero replay gate required a documented PSNR-only tolerance of `5e-4` because the historical control was generated under an older Torch/CUDA stack; MAE and temporal tolerances remained `5e-6`, and the plain warm head and luma wrapper were bitwise-identical on the current stack. The final checkpoint SHA-256 is `ec399f24900b763deb53d7c24f13c77f409275401d48727e5eb64dda0dd5e158`. See the dedicated [chroma-preserving luma report](CHROMA_PRESERVING_LUMA_ABLATION_20260908.md).

This closes the current local conditioning/output-formulation line. Do not promote the luma head, spend Runpod credit, change native Feature 18, or edit the public/runtime build from this result. The next safe step requires new paired renderer-conditioned temporal evidence or a separately validated teacher/state distillation design.

## Superseding final update: renderer-input conditioning completed

The stronger multi-layer arm completed at `E:/OpenNR_Training/stable_unet_joint_teacher_multilayer6000_20260908`. Its final validation MAE was `0.0205285050 / 0.0173715550 / 0.0150178303 / 0.0161182648 / 0.0458451717` for prior, high-effect, renderer-pilot, fresh one-pass and two-pass cohorts. Independent replay passed all five; full training-fit, response/precision diagnostics and fixed galleries were completed. It was not promoted.

The next controlled arm completed at `E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2`. It exposed the 17 verified renderer channels at the first stable-U-Net convolution, copied the original 19 input weights, zero-initialized the 17 added slices and used the fresh 1,200-step control `E:/OpenNR_Training/stable_unet_joint_teacher_20260907`. The final MAE was `0.0195801011 / 0.0177046111 / 0.0148462412 / 0.0162566698 / 0.0440758521`. Only high-effect improved against control; temporal delta improved on four cohorts and worsened on two-pass. Step-zero replay, final checkpoint replay, full training-fit replay, branch utilization and visual gallery all completed. No frozen test was used.

The branch was not inert: renderer-stem weight L2 was `0.3855278790`, actual-versus-zero-conditioning output MAE was `0.0010084041` on fresh one-pass and `0.0007561681` on two-pass samples. That response did not move the student toward a convincing teacher color/skin/face match. See the dedicated [renderer-context conditioning report](RENDERER_CONTEXT_CONDITIONING_20260908.md).

This closes the current safe conditioning line. More steps with the same paired data and frozen causal parent are not justified by the matched result: the arm did not pass the all-five gate, and the earlier 6,000-step weak control likewise did not generalize broadly. The next evidence-backed work would require a new, larger renderer-conditioned temporal cohort or a separately validated state/teacher distillation design. Do not promote this head, run it in Skyrim, replace native Feature 18 resources, spend Runpod credit, or change the public build from this result.

## Preparation started: renderer/state evidence tranche

The next phase is prepared but not launched. The existing fresh and two-pass
caches are valid renderer-conditioned temporal data, but neither has clean
same-current-frame/different-history pairs or a hash-verified teacher
hidden-state tensor. A new bounded capture tranche therefore precedes any
stateful student training.

The preparation contract requires at least 24 new accepted ordinary 1× clips,
8 state-response pairs, six scene/motion strata, strict 64-frame reset and
contiguity gates, both eyes, exact Feature 18-bound native guides, all six
renderer stages, and sequence-level holdouts. The stateful student design is
behavioral by default: it may use its own recurrent state plus current
RGB/native guides/renderer features, but never teacher pixels or hidden state at
inference. A small matched A–D pilot (plain, renderer-only, state-only,
combined) comes before any pair-loss arm.

See the [renderer/state distillation preparation protocol](RENDERER_STATE_DISTILLATION_PREP_20260908.md),
[capture contract](../config/renderer_state_capture_contract.example.json),
and [readiness auditor](../tools/audit_renderer_state_pairs.py). No capture,
training, Runpod spend, runtime change or production modification was started
in this preparation step.

The live capture profile was armed for the new tranche at
`C:\OpenNR_Captures_RendererStateDistillation_0.5.7_20260908`. The prior
2x output root was not reused. The settings backup and rollback source are
preserved under
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-output-root-20260908`;
the capture settings remain 64-frame, both-eye, native-guide and
renderer-conditioning enabled. The first tranche now contains 38 sequences;
37 pass the strict crop temporal gate and one is preserved/excluded for a
mid-clip reset plus a 45-frame host gap. See the [final capture audit](<E:/OpenNR_Training/renderer_state_capture_validate_final_20260908.json>).
At the time of this preparation note the game and capture process were stopped;
the subsequent audit and pilot results are recorded below.

The profile is now prepared for the next paired replay at the new empty root
`C:\OpenNR_Captures_RendererStatePairs_0.5.7_20260908`; the first tranche root
is preserved separately. Only `OpenNR Capture.output_directory` changed, with
the pre-edit settings backup at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-pairs-output-root-20260908`.
The game and runtime remain stopped.

## Superseding completed result: capture audit, pair discovery, and null pilot

The capture tranche is now fully audited. The raw root contains 38 64-frame
sequence folders; 37 pass the strict crop temporal gate and one is preserved
as an exclusion because `seq-1788876151201-8` has a mid-clip history reset and
a host-frame gap of 45. The decoded renderer-content audit accepts all 37
temporal-ready sequences. The immutable aligned cache contains 4,736 stereo
rows, 17 renderer channels and a 23/6/8 train/validation/frozen-test
sequence split. The cache completion SHA-256 is
`c699bb6464001b1b4cd3798a0bd33680fb02a6f224769829dbeab40ce4ce7f3c`.

The cache preserves an important caveat rather than hiding it:
`invalid_native_guide_pixels=[0,842672]` for depth and motion. The motion
validity mask must be retained for future exact-pair identity checks; this is
not evidence that the masked native motion is a valid byte-identical guide.

Reset/warm discovery hashed 3,712 non-test rows and skipped 1,024 frozen-test
rows. It found zero exact-signature candidate pairs. The formal pair audit
therefore reports `ready=false`, `ready_pair_count=0`, `minimum_pairs=8` and
`test_used=false`. The state-loss/recurrent branch is not justified by this
tranche.

A safe no-pair branch was evaluated locally for 400 steps at
`E:/OpenNR_Training/renderer_state_conditioning_pilot_400_20260908`. The
62,016-parameter conditioned refiner and its no-renderer control both selected
step zero. Parent, control and conditioned validation MAE are all
`0.0201330753`; all three test MAE values are `0.0250988306`. The selected
control and conditioned checkpoints are SHA-identical, and independent replay
passed with a maximum evaluator discrepancy of `3.72e-11`. The result is a
clean null for this small refiner/cache, so the pilot was not extended to
1,200 and no new visual claim is made.

This closes the current evidence tranche without reaching ordinary 1x MAE
`<=0.011`. The next justified experiment is a deliberate reset/warm paired
replay: at least eight pair units, normally 16 valid 64-frame clips, followed
by the formal pair audit. The detailed evidence and exact artifact paths are
in [renderer state capture and pilot report](RENDERER_STATE_CAPTURE_AND_PILOT_20260908.md).
No Runpod rental, runtime change, native Feature 18 change or public-build
change follows from this result.

## Public-source refresh — 2026-09-08

The current [NVIDIA ADLR DLSS 5 overview](https://research.nvidia.com/labs/adlr/DLSS5/)
describes the relevant architecture boundary as current rendered frame plus
engine motion vectors, carried temporal state and artistic-direction values,
with renderer-derived consistency supervision during training. It also calls
out causal, deterministic inference and frame-to-frame temporal-stability
training. This is directional public evidence, not access to NVIDIA weights,
hidden state or a reproducible teacher loss.

The latest GitHub results were primarily runtime/integration work. The
[dlss5-video-player architecture](https://github.com/2600th/dlss5-video-player/blob/main/docs/ARCHITECTURE.md)
reconstructs approximate guides for ordinary video, while the
[DLSS5-Toolkit](https://github.com/daniel-madrid-07/DLSS5-Toolkit) documents an
OptiScaler interception path and reversible DLL installation. Neither provides
a validated DLSS 5 student-training recipe or teacher-state export. Unofficial
ports and social/news performance claims therefore remain research-only and do
not authorize a binary installation, native Feature 18 change or a Runpod
spend. The public refresh supports the local next step: exact reset/warm paired
capture with native engine guides and measured state response.

## September 8 continuation and recovered-teacher parity update

The strict crop cache for the 37 accepted renderer-conditioned sequences was
completed at
`D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`.
It contains 4,736 eye rows with strict initial reset and a 23/6/8
train/validation/frozen-test split. The cache completion SHA-256 is
`34ff59c2852d9ceb3af5bc6a330ee85c23eaa8a293155ce0922ec865d9094ca1`.
Depth invalid count is zero; the known motion invalid count is `842672` and
remains mask-aware.

One pre-registered unpaired temporal continuation was evaluated from the
verified parent with the base/capacity branches frozen. The independently
replayed parent validation MAE was `0.0201341000`; the 400-step temporal-only
child was `0.0205482053`. Temporal-delta MAE moved from `0.0075894919` to
`0.0076733533`, and first-frame MAE moved from `0.0201701969` to
`0.0211512248`. The child was rejected without frozen-test access. This is a
negative result for more unpaired continuation on this tranche, not evidence
against paired state supervision.

The isolated MLX-DLSS recovery was also checked more broadly, without changing
native labels or runtime files. Using the exact active unknown-build DLL hash
`e16bcf15e16e13f527491cdf7845b2fe6521a738d8f7c9c721866a8496e1fc8e`, the
decoded logical weights hash
`058b4fa8a273724c64fe27bdcac4b0f7a1e6bd946f49675deb5259f36724b76c`, and
commit `4549ce6d99837e4fb182c38a028d8e96bc28c0df`, the calibrated no-auto-mask
configuration was replayed for 24 eye rows from three strict sequences. Overall
MAE changed only from `0.0234133062` (input versus native teacher) to
`0.0233862410` (recovered graph versus native teacher). The per-sequence result
was mixed: sequence 1 improved `0.0365440 -> 0.0313783`, while validation
sequence 25 regressed `0.0128387 -> 0.0164644` and frozen sequence 31 regressed
`0.0208572 -> 0.0223160`. The recovered graph is therefore not a stable
teacher substitute or label source for OpenNR. It remains an isolated parity
oracle/research lineage only.

The isolated dependency path used for these offline checks is
`C:\OpenNR\python312_ml_deps_20260908`; `torch 2.10.0+cu128`, `torchvision
0.25.0`, `lpips 0.1.4`, `scipy 1.18.1` and `tqdm 4.70.0` were installed there.
No production Python environment, Skyrim profile, native DLL, capture labels,
or public package was changed. No Runpod spend is justified by these results.

These results leave the decision unchanged: the next justified experiment is
at least eight exact reset/warm state-response pairs, normally 16 valid
64-frame clips, followed by the formal pair audit and matched plain,
renderer-only, state-only and combined controls. Until that evidence exists,
do not add a state-loss term, relabel with MLX outputs, or spend cloud credit.

## September 9 full-eye pilot and pause

The new 80-FPS full-eye capture was validated and used in bounded spatial and
temporal pilots. The spatial anchor cache shows a useful full-eye context
advantage, but the paired temporal arm did not hold the broad old-cohort gate.
The context-initialized continuation was paused at arm status step 1,425 at
the user's request; its last persisted checkpoint is the common step-1,200
baseline. No test rows, runtime changes, storage deletion, or Runpod spend
were involved. See the [full-eye pilot training and pause record](FULL_EYE_PILOT_TRAINING_20260909.md)
for exact cache hashes, MAEs, storage state and interruption evidence.

## September 9 goal continuation supersedes the pause note

The active target is now ordinary 1x MAE `<=0.007`, together with temporal
stability and convincing teacher visual/color match. The retained pilot was
re-inspected and its six renderer G-buffer stages were materialized into the
hash-bound overlay described in the [authoritative goal continuation report](GOAL_CONTINUATION_20260909.md).
The matched zero-conditioning control and real-conditioning arm both completed
absolute step 1,600 locally. The real renderer branch learned a nonzero,
material response but worsened the new full-eye validation and the old-six
mean; its endpoint was independently replayed with `max_difference=0.0` and
was rejected for promotion. The best current ordinary cohort is `0.013283717`,
so the tightened target remains unmet. No Skyrim/MGO launch, runtime change,
test tuning, raw-data deletion or Runpod spend occurred in this continuation.
