# Local Arm-C depth-expansion pilot — 2026-09-07

## Question

Does adding depth to the selected Arm-C residual branches improve teacher
imitation on both held-out cohorts after preserving the entire Arm-C function
at step 0?

## Decision rule

The candidate is retained only if an independently evaluated checkpoint beats
the exact Arm-C reference on both the prior and new validation cohorts. A
one-cohort gain, any regression on the other cohort, non-finite values, or an
unfair initialization is a rejection. The frozen test split remains untouched
until a candidate passes both validation gates. No production or MO2 install
is part of this pilot.

## Parent and architecture

Parent checkpoint:

`E:\OpenNR_Training\runpod_latest_cache_width_ablation_0.5.5_20260907\arm_C\best_mae.pt`

Parent architecture: `context_v7_capacity_temporal`, Arm C capacity
`192/6 + 96/3`, 3,480,979 parameters. The proposed child is
`192/8 + 96/4`; only depth changes. Existing Arm-C tensors are loaded into the
matching first six and first three blocks. The added block residual scales are
zero-initialized, making the child an identity extension of the learned parent
at step 0. This avoids the unfair branch replacement seen in the earlier v73
probe.

## Fixed inputs and recipe

- old strict cache:
  `E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
- new strict cache:
  `E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907`
- spatial auxiliary cache:
  `C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907`
- window `8`, burn-in `2`, batch `1` on the RTX 5070 Ti;
- old/new temporal mixture `0.35` new-domain probability;
- spatial probability `0.25`;
- unchanged Arm-C objective: feature `0.05`, VGG `0.10`, tone `0.10`,
  effect-power `0.10` with power `4`, identity `0.75`, micro-identity `1.0`,
  delta `0.12`;
- base/temporal/capacity learning rates `1e-7 / 1e-6 / 2.5e-6`;
- 400 exploratory steps, validation every 100 steps, seed `339`;
- output:
  `E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907`.

## Result — rejected

The 400-step run completed on the local RTX 5070 Ti in `485.63 s` with no
OOM or non-finite loss. Peak allocated VRAM was approximately `6.22 GiB`.
The step-0 validation function matched Arm C exactly within the trainer's
streaming output and the zeroed-gamma contract test passed. The zeroed new
block keys were:

- `capacity_blocks.6.gamma`
- `capacity_blocks.7.gamma`
- `capacity_extra_blocks.3.gamma`

Trainer validation was:

| Step | Prior MAE | New MAE | Merged MAE | Decision |
| ---: | ---: | ---: | ---: | --- |
| 0 | `0.019690747` | `0.019369198` | `0.019659829` | exact Arm-C function |
| 100 | `0.019719531` | `0.019348730` | `0.019683877` | new gain, prior regression |
| 200 | `0.019786113` | `0.019392162` | `0.019748233` | rejected |
| 300 | `0.019805022` | `0.019357151` | `0.019761958` | rejected |
| 400 | `0.019810106` | `0.019321344` | `0.019763110` | rejected |

The step-400 `best_new_domain.pt` was independently evaluated with the same
two strict validation caches and measured `0.019810200` prior and
`0.019321325` new. It therefore improves only the new cohort and is rejected
under the two-cohort rule. The trainer's selected `best_mae.pt` remained the
step-0 child checkpoint; it is not a new research candidate. The independent
result files are under:

- `E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907\independent_eval\prior\result.json`
- `E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907\independent_eval\new\result.json`

The rejected artifacts remain at
`E:\OpenNR_Training\local_arm_C_depth_expansion_0.5.5_20260907`. No frozen
test evaluation or production/MO2 change was made. This result again points
to an information/conditioning limitation rather than a lack of capacity;
the next justified branch is live renderer-conditioning capture, not another
cloud width/depth run.
