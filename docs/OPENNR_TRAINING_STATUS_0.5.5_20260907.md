# OpenNR training status — 2026-09-07

## Current status — September 8, 2026

This file preserves historical experiments below. The authoritative latest synthesis is [latest findings and next steps](OPENNR_LATEST_FINDINGS_20260908.md). Weak-conditioning, multi-layer, renderer-input and chroma-preserving luma arms are complete with no eligible promotion; independent replay and full training-fit audits are complete for the latest luma arm. The first renderer/state capture tranche is collected and strictly accepts 37 of 38 sequence folders; its aligned cache is complete, exact reset/warm discovery found zero pairs, and the registered 400-step renderer-conditioned pilot was a verified null with both arms selecting step zero. Goal MAE 0.011 remains unmet; no runtime/public-build change or cloud rental. See the [luma ablation report](CHROMA_PRESERVING_LUMA_ABLATION_20260908.md), [renderer-context report](RENDERER_CONTEXT_CONDITIONING_20260908.md), [renderer/state preparation protocol](RENDERER_STATE_DISTILLATION_PREP_20260908.md), and [renderer/state capture and pilot report](RENDERER_STATE_CAPTURE_AND_PILOT_20260908.md).

The first renderer/state capture root
`C:\OpenNR_Captures_RendererStateDistillation_0.5.7_20260908` is preserved
separately. The live profile is now armed for the next paired replay at the
new empty root `C:\OpenNR_Captures_RendererStatePairs_0.5.7_20260908`; a
hash-verified pre-edit settings backup is at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-pairs-output-root-20260908`.

## Superseding result: verified two-seed retention improvement

Corrected-guide retention training completed for seeds352/353, 1200 steps each. Both select step400 under the all-cohort rule against the original Arm-C baseline. Selected prior/high-effect/latest MAE: seed352 0.019445660 /0.017931557 /0.015411406; seed353 0.019470947 /0.018039097 /0.015471227. Both saved models reproduced their metrics on validation replay. Fixed visual comparisons are in E:/OpenNR_Training/retention_comparison_20260907/index.html and were inspected. Teacher texture/contrast differences remain; no frozen-test confirmation, deployment, or target0.011 claim. No training or verification job from this experiment remains live. See [retention protocol and evidence](D:/.CODEX_Projects/OpenNR-VR/docs/ALIGNED_RETENTION_CONTINUATION_20260907.md). Next investigate remaining training-fit versus generalization error; more identical seed trials are not the immediate priority.

## Latest result — completed native-guide alignment comparison

Both local 1,200-step runs are complete. Corrected-guide prior/high-effect/latest validation MAE is **0.019734763 / 0.017683441 / 0.015286623**, versus the matched existing-guide control **0.019696476 / 0.017727330 / 0.015918944**. The corrected model improves new cohorts, but remains slightly worse on prior data than the original-input parent (0.019690721). No production promotion. The MAE 0.011 goal stays active.

A confirmed legacy guide-crop mapping defect is addressed in separate, hash-verified training/validation guide overlays and in the canonical builder for future caches (explicit legacy reproduction remains available). The full 3.481M-parameter Arm-C model trained across prior, high-effect and latest pilot cohorts. Test access is prohibited in this experiment. See [alignment evidence and protocol](D:/.CODEX_Projects/OpenNR-VR/docs/ALIGNED_GUIDE_MULTICOHORT_TRAINING_20260907.md). Results and visual comparisons are under `E:\OpenNR_Training\alignment_multicohort_20260907`.

## Latest completed update — 2026-09-07 afternoon

The newly collected renderer-conditioning clips have now been validated and used for a completed local training pilot. Eleven of twelve 64-frame clips passed; one clip is preserved/excluded after two GPU-query failures. An isolated aligned cache contains 704 stereo frames, split six/two/three sequences for training/validation/test. All six renderer stages are decoded; existing caches and runtime/public builds are unchanged.

A frozen Arm-C parent plus a 62,016-parameter refiner was trained for 1,000 steps per arm. Test MAE: parent **0.021267248**, control without renderer features **0.018983047**, conditioned refiner **0.021005986**. The conditioned model won validation but lost test to the control, so this recipe is not promoted. The control's 10.74% same-session test improvement is useful offline evidence, not a claim of general MAE 0.011, old-cohort improvement, or VR readiness. Both arms slightly worsen temporal-delta error. Direct causal validation replay verified the saved results.

Training is complete and the GPU is idle. No cloud resource was rented; no more capture is required to complete this pilot. See [the complete pilot protocol, results, caveats and artifact paths](D:/.CODEX_Projects/OpenNR-VR/docs/RENDERER_CONDITIONED_TRAINING_PILOT_20260907.md). The historical pending-capture sections below describe the earlier state and are superseded by this update.

## Historical decision before the latest capture and training

The latest width/depth and local loss/conditioning-free pilots do not show that
the model simply needs more capacity. The strongest justified next step is to
collect and validate renderer-owned conditioning data from the isolated Open
Shaders profile. Runpod is idle until that data produces a defensible,
two-cohort candidate.

The acceptance rule remains strict: a candidate must improve both the prior
held-out cohort and the newer held-out cohort under the same independent
streaming evaluator. A new-cohort-only gain is useful evidence, but it is not
a promotion.

## Runpod safety checkpoint

On the latest live Runpod recheck, `list_pods` returned zero resources and
`list_network_volumes` returned zero volumes. There is therefore no running
pod or persistent network volume currently draining credit, and no stop/delete
action was required.

The latest billing query covered `2026-09-07T10:00:00Z` through
`2026-09-07T14:00:00Z`, returned three completed hourly records, and reported
`$2.520465` for that query window (`$2.470697` GPU and `$0.049769` pod disk).
This is historical usage for the selected window, not the remaining wallet
balance and not evidence of a currently running resource. The earlier
01:00–13:00Z query reported `$6.347845`; the two numbers are different query
windows and must not be added together.

No new cloud rental is justified until a renderer-conditioned capture is
available or a local experiment clears the two-cohort gate. When cloud work is
eventually justified, target a measured transfer rate near 2 Gbit/s where
available, but treat catalog/network labels as unverified until a short pod
throughput test succeeds. Keep the run bounded by the remaining budget.

## Width and replication evidence

The completed same-recipe Arm-C width experiment used seed 337, 1,000 steps,
and the following capacity variants:

| Candidate | Capacity | Parameters | Prior MAE | New MAE |
|---|---:|---:|---:|---:|
| v65 | `128/6 + 64/3` | 2.936M | 0.019805003 | 0.019977055 |
| Arm A | `128/6 + 64/3` | 2.936M | 0.019705133 | 0.019378331 |
| Arm B | `160/6 + 80/3` | 3.188M | 0.019696995 | 0.019372930 |
| Arm C | `192/6 + 96/3` | 3.481M | 0.019690728 | 0.019369167 |

All three arms beat v65 on both cohorts; Arm C was selected. On the frozen
merged test, Arm C measured `0.0213287980` versus v65 `0.0214273864`, a
`0.0000985884` (`0.460%`) MAE reduction and approximately `+0.0975 dB` PSNR.
The temporal delta was slightly worse, so this is a modest capacity result,
not proof that width is the main path to `0.011`.

The independent seed-338 Arm-C confirmation measured `0.019714982` prior and
`0.019330343` new. It improved the new cohort relative to seed 337 but was
slightly worse on the prior cohort, so it did not clear the stronger
replication gate and was not promoted.

## Local pilots after Arm C

All of the following were run locally on the RTX 5070 Ti or evaluated locally;
none changed production or the MO2 installation:

| Pilot | Independent prior MAE | Independent new MAE | Decision |
|---|---:|---:|---|
| Effect-frequency emphasis | 0.019691297 | 0.019351878 | Reject: prior regressed marginally |
| Micro-identity weighting | 0.019690728 | 0.019369167 | Reject: no improvement |
| Conservative continuation | 0.019719600 | 0.019374900 | Reject: both worse |
| Style/context modulation | 0.019704359 | 0.019328705 | Reject: prior regressed |
| Parent-preserving depth expansion `192/8 + 96/4` | 0.019810200 | 0.019321325 | Reject: new-only gain |

The depth expansion was zero-initialized for its new residual blocks, reproduced
Arm C exactly at step 0, completed 400 steps without OOM or non-finite loss,
and still regressed the prior cohort. Its evidence remains at
`E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907`.

An offline scalar residual-gain calibration also failed as a universal fix:
the prior validation cohort preferred approximately `alpha=0.980`, while the
new cohort preferred approximately `alpha=1.030`. The train-fitted global
alpha was `1.03907`; it improved the new cohort by about `0.000009` but hurt
the prior cohort by about `0.000026`. The opposite cohort optima support a
missing-context hypothesis rather than a single global strength knob.

## Pending renderer-conditioned capture

The active isolated profile is:

`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`

The verified capture settings are:

- renderer conditionings enabled;
- depth, motion vectors, raw teacher, pre-NR, and post-NR enabled;
- both eyes enabled;
- eight-frame bursts;
- one `512x512` crop;
- full-frame capture disabled to keep the pilot manageable;
- output root `C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`.

At the time of this status save, that capture root did not exist and contained
zero files. The next handoff is therefore user capture, followed by a strict
validation of all six expected renderer-conditioning stages, eye/crop/source
rectangle alignment, raw sizes/formats, finite nonempty values, and frame
ordering/drop state. No training cache or cloud pod should be started before
that validation passes.

## Preserved artifacts and boundaries

- Width evidence: `docs/RUNPOD_LATEST_CACHE_WIDTH_ABLATION_0.5.5_20260907.md`.
- Fresh-data/model decision log: `docs/FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260907.md`.
- Renderer-conditioning probe: `docs/RENDERER_DERIVED_CONDITIONING_PROBE_0.5.5_20260907.md`.
- Depth pilot: `docs/LOCAL_ARM_C_DEPTH_EXPANSION_PILOT_0.5.5_20260907.md`.
- No frozen-test rerun, production checkpoint replacement, MO2 change, or
  public package change was made as part of these rejected pilots.

This document is a checkpoint, not a claim of live VR acceptance. Training
MAE, renderer capture validity, runtime delivery, headset quality, and VR
frame-time acceptance remain separate gates.

## Later update: fresh 21:14 session intake

The earlier empty-root/eight-frame snapshot above is historical. The new session
contains27 complete64-frame stereo clips (1728 frames,3456 eye examples), all of
which passed structural, reset/continuity and decoded renderer-content checks.
No clips were excluded or deleted. Representative aligned visual sheets were
reviewed separately from numerical integrity checks.

See [fresh-session intake and training plan](FRESH_SESSION_INTAKE_20260907_2114.md)
for authoritative progress. The separate cache is being built at
`E:/OpenNR_TrainingInputs/RendererConditioningFreshSession_20260907_2114`, with
16train/5validation/6frozen-test sequences. Existing cohort splits remain fixed.
The prepared continuation starts at verified broad U-Net5600 and adds this fourth
cohort at25% of updates; old cohorts retain75% in their existing relative mix.
Training has not yet launched as of this cache-build update. This does not
promote a runtime model, enable two-pass teacher training, or modify any public build.

Subsequent update: fresh cache completed successfully and passed independent loader
hash/sequence verification. Local continuation launched at
`E:/OpenNR_Training/stable_unet_fresh_session_20260907_2114` (session58365).
Startup provenance and baseline replay precede optimizer updates; launch alone
does not establish training progress or improved model quality.

**Superseding user direction: paused for additional collection; data preparation
only.** Session58365 stopped during initial step0 prior validation, before any
optimizer updates. Exit and absence of matching processes verified. Prepared
cache is preserved. No training restart without explicit user authorization.

## Superseding authorization: joint one-pass/two-pass training

User subsequently explicitly authorized training and optimization toward MAE0.011.
Both new caches are complete and independently hash-verified:27one-pass clips plus
10accepted two-pass clips,37total/4736eye examples. Two raw two-pass clips remain
preserved exclusions (one single frame; one constant left-eye vertex-AO mask pending
semantic review). See TWOPASS_DATA_INTEGRATION_20260907.md for exact provenance.

Joint session65149/output E:/OpenNR_Training/stable_unet_joint_teacher_20260907
passed original-cohort baseline replay and reached50successful optimizer updates,
including8fresh-one-pass and7two-pass draws. New validation baseline MAE .01624963
and .04391099 respectively. No post-training validation gain or goal achievement
is established. Earlier pause/run-preparation entries are historical; original
stopped session58365 was not resumed. No Runpod/public-build/runtime changes.

Latest joint result: session65149 completed1200updates, no all-cohort eligible
checkpoint; starting5600head remains the reference. Final prior/high/old renderer/
fresh1x/2x MAE .01953432/.01788321/.01483325/.01615908/.04393235. The earlier2x
gain at800did not persist. Independent final replay, mode-labeled galleries and
ordinary full-training fit are running sequentially in session31950 before the
next optimization decision. Goal0.011 remains unachieved; no model promotion.

## Superseding September 8 endpoint update

The status above is historical where it says diagnostics are running. They have now
completed, followed by the next controlled renderer-input experiment.

The stronger multi-layer run
`E:/OpenNR_Training/stable_unet_joint_teacher_multilayer6000_20260908` completed
6,000 updates. Its final validation MAE was
`0.0205285050 / 0.0173715550 / 0.0150178303 / 0.0161182648 / 0.0458451717`
for prior, high-effect, renderer-pilot, fresh one-pass and two-pass. The checkpoint
replayed exactly across all five validation cohorts, and its full training-fit,
response/precision diagnostic and fixed galleries completed. It did not satisfy the
all-five promotion rule.

The next justified conditioning arm
`E:/OpenNR_Training/stable_unet_renderer_conditioned1200_20260908_retry2` exposed
the 17 hash-verified renderer channels at the stable U-Net stem. It copied the
original 19 input weights and zero-initialized the 17 new slices, so its direct
zero-input functional smoke test was exactly identical to the original head. It
used the fresh 1,200-step control
`E:/OpenNR_Training/stable_unet_joint_teacher_20260907`, not the unrelated
6,000-step continuation, with the same seed, optimizer initialization, cohort
draws, loss, holdouts and sample schedule.

Final renderer-input MAE was
`0.0195801011 / 0.0177046111 / 0.0148462412 / 0.0162566698 / 0.0440758521`.
Only high-effect improved against the matched control; temporal delta improved on
four cohorts and worsened on two-pass. Independent final replay, full training
replay, renderer-stem utilization measurement and fixed visual sheets completed;
`test_used=false` throughout. The renderer branch learned nonzero weights and a
measurable actual-versus-zero response, but the student stayed darker and less
teacher-like on face/skin/color samples. No promotion, test evaluation, runtime
change, public build change, native Feature 18 change or Runpod rental followed.

The target remains unmet. The two controlled conditioning hypotheses are now
closed for this data/parent line; further safe progress requires new paired
renderer-conditioned temporal data or a validated teacher/state distillation
design, not blind continuation or width scaling. Full evidence is in
[RENDERER_CONTEXT_CONDITIONING_20260908.md](RENDERER_CONTEXT_CONDITIONING_20260908.md).
