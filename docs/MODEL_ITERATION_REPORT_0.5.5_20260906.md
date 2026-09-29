# Distilled-model realism iteration report — 0.5.5 — 2026-09-06

> This file is the historical v9-v43/v42-v43 iteration record. The current
> fresh-capture audit and v45-v65 model lineage supersede its outcome and
> recommendation sections; use
> [FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260906.md](D:/.CODEX_Projects/OpenNR-VR/docs/FRESH_CAPTURE_AUDIT_AND_MODEL_ITERATION_0.5.5_20260906.md)
> for the current v61 candidate and data-quality evidence.

## Current superseding outcome

The latest organized corpus contains 126 strict temporal-safe fresh sequences,
5 spatial-only quarantined fresh sequences, and 73 historical strict sequences.
The current practical all-non-test candidate is the v65 best-MAE checkpoint at
`E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt`.
It measures `0.014935002` fresh MAE, `0.025628855` historical MAE, and
`0.018847388` combined across the two held-out cohorts. The requested `0.011`
target remains open, and these are crop-space offline streaming results rather
than live SkyrimVR/headset/runtime acceptance. The v65 change is a small
full-resolution auxiliary-sampling refinement; v61 remains its parent.

The latest controlled line added zero-initialized residual/final gates, signed
effect power loss, micro-identity loss, a modest base/temporal learning-rate
increase, and a bounded full-resolution auxiliary oversampling probe. The v54
width expansion was infeasible on the available GPU; v62 improved fresh-only
error but regressed the historical cohort and was not promoted; v63 and v64
did not produce meaningful gains. The v65 result is retained but does not
change the next high-value step: new independent strict teacher coverage
and auditable renderer-derived conditioning (albedo, normals, lighting,
material/object masks, artistic controls, and carried history where exposed),
not unbounded tuning of the same crop corpus.

## Historical outcome (superseded)

The current distilled model is materially closer to the Feature 18 teacher than
the input, but it is not a teacher match and it does not meet the requested
MAE 0.011 target. The strongest frozen crop-space test result in this
continuation is now MAE **0.02611644**, from the v42 fixed final fit over all
non-test strict streams and spatial patches. The last independently
validation-selected checkpoint remains v33 at **0.02614121**; v32 reaches
**0.02615651**, v31 reaches **0.02618508**, v29 reaches **0.02623039**, and
v28 reaches **0.02624429**. All improve on the previous v16 numerical leader
at **0.02631037**. The v40-to-v42 transfer gain is real but very small: the
last two half/quarter-rate cooldowns improve MAE by only about `0.00001229`
from v40 to v42. The target has not been reached.
Because v41 and v42 followed earlier frozen-test measurements, this is the
best observed final-fit score, not a clean holdout-selected result; v33 is the
unbiased validation-selected comparison point.

Visual A/B review remains decisive: the students preserve the character,
geometry and hair structure, but the teacher still has warmer/redder skin,
stronger facial shadow and local contrast, and richer material detail. The
attention and motion variants do not visibly close that gap in the inspected
close-ups.

## Data and evidence boundary

The relevant OpenNR-bearing roots and manifests were rechecked, including the
strict temporal capture, merged spatial cache, older full-resolution cache,
new non-strict temporal crops, project reports, previous model outputs and
related Codex task history. The old full-resolution cache is not silently
missing from the merged training source: its manifest is listed as
`fullres_20260904` in `E:\OpenNR_MergedSpatialCache_20260905`, alongside the
0.5.3 raw-crop source. The current merged cache adds the 0.5.5 raw-crop source.

The strict temporal cache remains the clean temporal source:

| Check | Result |
|---|---:|
| Strict source sequences | 73 |
| Complete frames | 4,672 |
| Eye rows / 512-pixel patches | 9,344 |
| Sequence split | 46 train / 12 validation / 15 test |
| Tensor shapes | RGB `(9344, 2, 3, 512, 512)`, guides `(9344, 5, 128, 128)`, context `(9344, 8, 96, 96)` |
| Initial reset | 146 of 146 eye streams begin with `[true, true]` |
| Complete-row identity | `253f974ddbec54c43a3921a4f379b1907c36708422dfa23bddc683c733290fb3` |
| NaN / Inf / range failures | None found |
| Merged spatial source | 20,334 patches / 11,864 rows; `test_used_for_tuning=false` |

The continuation also built and audited an all-source spatial cache at
`E:\OpenNR_MergedSpatialCache_AllSpatialSources_0.5.5_20260906`: 21,950 patches
and 12,584 rows, with 15,772 train patches, 2,100 validation patches and 4,078
test patches. It combines the previous merged/raw sources plus the selected
spatial-only rows from the four zero-motion-vector eye anomalies and the
full-resolution master capture. The auxiliary rows are explicitly marked
`temporal_training_allowed=false`; they were used only for static appearance
regularization. Its row identity is
`c29c86dd0ced84ea16364742de76c23c853fc88acf98731b2c8a95e3b66bdbd7`.

After the recipe was fixed, v40, v41 and v42 used the 46 training plus 12
validation strict sequences as a single 116-stream final-fit pool and admitted
the 15,772 train plus 2,100 validation spatial patches. The 4,078 spatial test
patches and 15 strict test sequences were never loaded for training, but each
final-fit pass was subsequently measured on that frozen test. Because the
original validation sequences were included in these fits, v40-v42 have no
independent validation score. Also, v41 and v42 were launched after observing
earlier frozen-test results, so their ranking is test-informed and should not be
treated as an unbiased holdout selection; v33 remains the proper
validation-selected research checkpoint.

The extra full-resolution master audit found 71 complete records in three
sequence directories, zero invalid frames in the main 64-frame sequence and
19 orphan files. Only the complete, auditable 64-frame sequence was admitted
as a spatial-only source. This is additional data coverage, not proof that the
master capture is safe for recurrent training.

The four eye-specific zero-motion-vector anomalies remain excluded from
temporal supervision, as required by the capture audit. Their paired RGB and
teacher data may still be relevant to future static-only work, but admitting
their invalid motion into a recurrent loss would corrupt the temporal
experiment. The incomplete final sequence is also not admitted.

The target-change audit shows why a single global color correction is not a
safe solution. The sampled mean teacher-minus-input RGB shift is approximately
`[+0.0156,+0.0166,+0.0182]` on validation but `[-0.0075,-0.0033,+0.0011]` on
test. The residual is conditional on scene, lighting and content. On v9,
validation low-frequency error is about `0.01990` against a teacher effect of
`0.03328`; test is `0.02438` against `0.03877`. The remaining gap is therefore
mostly broad, structured appearance rather than a missing scalar brightness
boost.

## Controlled model iterations

All candidates below were initialized from known-good weights or explicitly
zero-initialized branches. For v9-v39, test selection stayed frozen and no test
rows were used for tuning. v40-v42 are a separate final-fit lineage after the
recipe was fixed: they used the former validation split for training and made
one frozen-test measurement per pass. The final-fit sweep did not train on test
rows, but v41/v42 were informed by earlier frozen-test measurements, so v42 is
reported as the best observed final-fit artifact rather than as a clean
holdout-selected checkpoint.

| Candidate | Main intervention | Validation MAE | Frozen test MAE | Decision |
|---|---|---:|---:|---|
| v9 temporal control | 2.30M params; strict temporal plus merged spatial training; 4,000 steps | 0.02253512 | 0.02633853 | Strong control; retain |
| v11 capacity-temporal | 2.77M params; width-128/6-block appearance branch, tone loss, merged spatial mix | 0.02249698 | 0.02638563 | Validation-only gain; test regressed |
| v14 detail | Native-detail branch at downsample 2 | 0.02253365 | 0.02633851 | No meaningful gain |
| v15 motion warp | Exact captured MV used to warp history | 0.02252976 | 0.02633236 | Small numerical gain; no visible match |
| v16 warp blend | Full-resolution warped-history blend gate | 0.02250661 | **0.02631037** | Numerical leader; gate diagnostic says effect is near zero, so treat gain cautiously |
| v18 local attention | 2.49M params; zero-init 1/4-grid non-shifted local attention | 0.02251370 | 0.02633606 | Tiny validation gain; no visual gain |
| v19 base tune | Attention held at zero; higher spatial base learning rate | 0.02251589 | 0.02633492 | Early improvement, then overstepped |
| v20 effect-weighted target | Target-change loss scale 8 instead of default 3 | 0.02253522 at best usable point | Not promoted | Worse whole-frame validation despite better feature distance |
| v21 shifted attention | Alternating 8×8 shifted windows with Swin-style mask | 0.02251913 | 0.02632335 | Best new architecture probe; still a small effect and visually unchanged |
| v22 shifted + merged mix | v21 architecture with merged spatial cache mixed at 25% | 0.02253512 at initialization | Not promoted | Mixed distribution did not recover |
| v23 history warmup | Prefix history was warmed without gradient before the supervised window | 0.02252016 | 0.02634442 | Rejected; no test gain |
| v24 excluded auxiliary rows | v16-style warp blend with invalid-motion/incomplete rows admitted only as spatial regularization | 0.02252095 | 0.02635344 | Rejected; spatial-only admission was safe but not useful |
| v26 multiscale shifted attention | Medium/coarse context-token cross-attention; strict temporal cache only | 0.02253512 at initialization | 0.02631475 at best feature | Small feature improvement, no visual match |
| v27 all-source multiscale attention | v26 plus all audited spatial sources, including the full-resolution master | 0.02251255 | 0.02629978 | Small numerical gain; no visible teacher closure |
| v28 all-source static refit | 4,000-step static refit of the v8 spatial base on the all-source cache | 0.02235891 | **0.02624429** | Promoted as the stronger appearance base |
| v29 static-base temporal | v28 base followed by a 2,000-step strict temporal phase with all-source spatial mix | **0.02233029** | **0.02623039** | Promoted temporal base; still not a teacher match |
| v30 pooled-tone loss | v28 base refit with an additional 16-pixel pooled RGB tone term | 0.02234349 | 0.02626055 | Rejected; mixed-validation gain did not transfer to strict test |
| v31 capacity-temporal | v29 feature-selected checkpoint; width-128/6-block capacity branch with stronger VGG/tone supervision | 0.02231067 | 0.02618508 | Promoted research candidate; small frozen-test gain |
| v32 capacity continuation | v31 best-feature checkpoint; 1,500 lower-learning-rate continuation with the same width-128/6-block branch | **0.02224460** | **0.02615651** | Current offline numerical leader; feature-selected checkpoint stayed at the v31 parent |
| v33 capacity cooldown | v32 MAE checkpoint; half-rate continuation, early-stopped after 1,025/2,500 steps when validation regressed after step 250 | **0.02223920** | **0.02614121** | Current offline numerical leader; small transfer gain, retain as research artifact |
| v34 extra capacity branch | v33 MAE checkpoint plus a second zero-initialized width-128/6-block residual branch; early-stopped at 500/1,500 steps | 0.02223920 at initialization | Not promoted | Rejected; step 250/500 validation regressed, so no frozen-test spend |
| v35 paired-eye conditioning | v33 MAE checkpoint plus a zero-initialized opposite-eye RGB branch; synchronized left/right temporal training | 0.02227445 at step 500 | 0.02614878 at feature step 500 | Rejected; perceptual validation gain did not transfer and MAE checkpoint stayed at step 0 |
| v36 long-window full model | v33 MAE checkpoint; 32-frame windows with 8-frame burn-in and all parameters trainable | Not reached | Not evaluated | Stopped after the first temporal update failed to complete in the observed GPU-saturated interval; no learned checkpoint promoted |
| v37 long-window temporal-only | v33 MAE checkpoint; 32-frame windows with 8-frame burn-in, inherited base/capacity frozen | 0.02224188 at step 128; 0.02224277 at step 256 | Not evaluated | Rejected; the longer horizon did not improve validation and temporal-delta stayed essentially unchanged |
| v38 extra-only adapter | v33 MAE checkpoint; inherited parent frozen, only the optional zero-initialized extra width-128/6-block branch trainable | 0.02226012 at step 250 | Not evaluated | Rejected; the isolated capacity adapter regressed validation, so no frozen-test spend |
| v39 effect high-frequency loss | v33 MAE checkpoint; opt-in loss on high-frequency `(student - input)` versus `(teacher - input)` residuals, weight 0.15 | 0.02226668 at step 250 | Not evaluated | Rejected at the first validation checkpoint; both MAE and feature distance worsened |
| v40 all-nontest final fit | v33 recipe fixed; 500 steps over all 116 non-test strict eye streams plus 17,872 non-test all-source spatial patches, with no validation selection | Not applicable; validation was included in fit | **0.02612873** | Previous frozen-test leader; final-fit transfer gain is small, no live/runtime promotion |
| v41 all-nontest cooldown | v40 last checkpoint; same 116 strict streams and 17,872 non-test spatial patches; 500 half-rate cooldown steps, no validation selection | Not applicable; validation was included in fit | **0.02612051** | Small frozen-test improvement; visually unchanged, retain |
| v42 all-nontest cooldown | v41 last checkpoint; same fixed non-test pool; 500 quarter-rate cooldown steps, no validation selection | Not applicable; validation was included in fit | **0.02611644** | Best observed final-fit test score; test-informed ranking, no teacher-match breakthrough |
| v43 context style modulation | v33 MAE checkpoint plus an opt-in zero-initialized global context-FiLM affine around the capacity blocks; train-only strict/spatial mix | **0.02223920** at initialization; 0.02226672 at step 250 | Not evaluated | Rejected at first validation checkpoint; feature distance also worsened, so no frozen-test spend |

The v29 test value above is from the feature-selected checkpoint (step 1,000);
the MAE-selected checkpoint (step 1,500) measured **0.02626743** on the same
frozen test. For v31, the MAE-selected and feature-selected frozen-test
checkpoints both measured **0.02618508**. For v32, the MAE-selected checkpoint
at step 1,500 measured **0.02615651**, while the feature-selected checkpoint
selected step 0 and retained the v31 parent result (**0.02618508**). Both
selection policies are retained and reported separately rather than collapsing
validation MAE and perceptual selection into one score. The v32 MAE-selected
checkpoint SHA-256 is
`c43bc5938f2d69f7d6d7a82cd3f554e733c0df846753e0fdd2505952a560ef58`.
The v33 run was intentionally early-stopped after step 1,025: validation
peaked at step 250 and later checkpoints regressed. Its MAE-selected step-250
checkpoint measured **0.02614121** on the frozen test and has SHA-256
`eaf1550ab4e0a2f203a5b7e1409155c161b2167a767f12ba6707438e109cce67`.
The v33 feature-selected checkpoint selected step 1,000 but measured
**0.02616812** on the frozen test, so it is not the promoted selection.
The v35 paired-eye feature checkpoint improved validation feature distance to
**0.07853858**, but measured **0.02614878** on the frozen test. Its MAE
checkpoint remained at step 0 and measured **0.02614106**, which is the same
parent function within the small numerical difference caused by paired versus
single-eye batching. Stereo conditioning is therefore not promoted from this
corpus.

The v36-v38 probes further narrow the useful search space. v36 made the full
model's 32-frame/8-frame-burn-in experiment computationally impractical before
the first learned temporal update completed, so it produced no candidate. v37
isolated the same long-horizon question by freezing all inherited appearance
and capacity parameters; validation remained slightly worse than the exact
v33 initialization (`0.02223944` in that run) at both measured checkpoints,
and its temporal-delta metric stayed at approximately `0.01004168`. v38 then
isolated newly added capacity with the v33 parent frozen; its validation MAE
was **0.02226012** at step 250 and its feature distance was **0.07854003**.
None of these runs earned a frozen-test evaluation or a promotion.

The v39 diagnostic explains why the loss was not carried forward. The v33
static branch fits the training sample at MAE **0.01354728** and
changed-region MAE **0.02337279**, while the unchanged validation split measures
MAE **0.02218878** and changed-region MAE **0.03685862**. Effect residual RMS
ratio/cosine fall from `0.9506 / 0.9264` on training to `0.8974 / 0.7710` on
validation. A current frequency audit gives the validation effect bands as
`0.8071 / 0.8972 / 0.8231` for coarse energy/RMS/cosine,
`0.0959 / 0.8715 / 0.7937` for the next band,
`0.0511 / 0.7759 / 0.8195` for the mid-high band, and
`0.0459 / 0.5324 / 0.6446` for the finest band. The finest band is visibly
weakest, but it is too small and too poorly generalized for a strong isolated
loss to improve the whole validation objective; v39 confirmed that tradeoff.
The fit and frequency artifacts are preserved at
`E:\OpenNR_Training\v33_fit_diagnostic_0.5.5_20260906\result.json` and
`E:\OpenNR_Training\v33_frequency_diagnostic_0.5.5_20260906\result.json`.
The v39 run and its explicit early-stop status are preserved at
`E:\OpenNR_Training\effect_highfreq_v39_0.5.5_20260906`.

The v40 fixed-fit checkpoint and its single frozen-test evaluation are
preserved at `E:\OpenNR_Training\final_fit_v40_all_nontest_0.5.5_20260906\last.pt`
and `E:\OpenNR_Training\final_fit_v40_all_nontest_frozen_test_0.5.5_20260906\result.json`.
The v40 checkpoint SHA-256 is
`121bedcf66573f04ef8d9ef01d510c3b32e94c0dc0ac840186b5471364717a4c`.
The v41 fixed-fit checkpoint and frozen-test evaluation are preserved at
`E:\OpenNR_Training\final_fit_v41_all_nontest_cooldown_0.5.5_20260906\last.pt`
and
`E:\OpenNR_Training\final_fit_v41_all_nontest_cooldown_frozen_test_0.5.5_20260906\result.json`.
The v41 checkpoint SHA-256 is
`f5d8775c6779f3eddde0971a74ef1c3843883d084db32cf8b95692c9239c9018`.
The v42 fixed-fit checkpoint and frozen-test evaluation are preserved at
`E:\OpenNR_Training\final_fit_v42_all_nontest_cooldown_0.5.5_20260906\last.pt`
and
`E:\OpenNR_Training\final_fit_v42_all_nontest_cooldown_frozen_test_0.5.5_20260906\result.json`.
The v42 checkpoint SHA-256 is
`6b8f103382258e9d8a5481cab7ceeb8e08cb77f6293404e9585cb585d43ad39e`.
Its frozen-test evaluation covers 15 sequences, 30 eye streams and 1,920
frames; MAE is `0.02611644057970908`, PSNR is `28.120939716816984`, identity
MAE is `0.04008371030083961`, and temporal-delta MAE is
`0.011159014851643294`. The result explicitly remains an offline crop-space
measurement with a reset at every eye stream. The v42 run retained the 2.767M
parameter base/capacity topology (`64/3` base, `128/6` capacity), used 8-frame
windows with 2-frame burn-in and batch 2, and used learning rates
`2.5e-8 / 2.5e-7 / 1.25e-6` for base/temporal/capacity parameters. Its parent
SHA is the v41 checkpoint SHA above, and `test_used=false` is recorded in the
run metadata.
The v43 style-modulation probe is preserved at
`E:\OpenNR_Training\style_modulation_v43_probe_0.5.5_20260906`, with its
early-stop status in `status.json`, validation history in `history.jsonl`, and
step-0/step-275 checkpoints. The zero-initialized branch exactly reproduced
the v33 parent at initialization (`0.022239204340924818` MAE and
`0.07861751566330592` first-frame feature distance). At step 250, validation
MAE rose to `0.022266716256530747` and feature distance to
`0.07862441490093867`; temporal-delta MAE also rose from `0.010041673306369172`
to `0.010043741565204276`. It was stopped before any test evaluation.

The exact motion-vector sign was independently checked before v15: an oracle
warp of the previous teacher frame reduced validation error from `0.02506935`
to `0.01568748` with the positive sign, while the negative sign increased it
to `0.02930410`. That confirms the native Feature 18 motion resource and sign
are useful. It does not imply that a warped previous *student* frame is a good
teacher substitute; fixed blends of the student history regressed, and the
v16 learned gate stayed effectively inactive.

## Visual samples

The following sheets are direct crop-space A/B evidence, not live VR proof:

- [Shifted-attention v21 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/shifted_attention_v21_gallery/seq-1788671399304-47_f01_e0.jpg)
- [Plain-attention v18 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/attention_temporal_v18_gallery/seq-1788671399304-47_f01_e0.jpg)
- [Detail v14 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/detail_temporal_v14_gallery/seq-1788671399304-47_f01_e0.jpg)
- [All-source v27 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/multiscale_all_spatial_v27_gallery/seq-1788671497693-63_f32_e0.jpg)
- [Current v29 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/temporal_from_all_spatial_static_v29_gallery/seq-1788671612549-70_f01_e0.jpg)
- [Current v32 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/capacity_v31_continuation_v32_gallery/seq-1788671497693-63_f32_e0.jpg)
- [Current v33 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/capacity_v32_continuation_v33_gallery/seq-1788671497693-63_f32_e0.jpg)
- [Current v40 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/final_fit_v40_gallery/seq-1788671497693-63_f32_e0.jpg)
- [Current v41 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/final_fit_v41_gallery/seq-1788671497693-63_f32_e0.jpg)
- [Current v42 A/B sample](D:/.CODEX_Projects/OpenNR-VR/out/final_fit_v42_gallery/seq-1788671497693-63_f32_e0.jpg)

The sheets place input, the spatial control, the candidate and the Feature 18
teacher side by side. The inspected frame shows the same persistent difference
across candidates: teacher facial tone and shadow structure are more
pronounced, while the student remains close to the inherited spatial output.
The v40, v41 and v42 sheets are consistent with that result: their small
frozen-test gains are not visibly distinguishable from v33 in the inspected
close-ups, so they are retained as numerical final-fit candidates rather than
claimed as visual breakthroughs.

The v43 style-modulation branch was not promoted and has no frozen-test sheet;
its validation regression is sufficient to reject the mechanism without
spending another test measurement.

## Research boundary

The latest public DLSS 5 material supports the direction of this work but does
not provide a portable recovered teacher. The [NVIDIA DLSS 5 research
description](https://research.nvidia.com/labs/adlr/DLSS5/) describes a causal,
deterministic one-step pixel-space diffusion/generative model conditioned on
the current rendered frame, engine motion, carried temporal state and artistic
direction, with renderer-derived consistency supervision and temporal
stability. Public reverse-engineering repositories such as the [Feature 18
probe findings](https://github.com/kibblerz/DLSS5-Reshade-AIO/blob/main/lab/PRIVATE-CONTRACT-FINDINGS.md)
and the [experimental raw NGX player](https://github.com/Zonnery/dlss5-nr-player)
expose useful guide/runtime-contract clues, but not a verified complete graph
and checkpoint that can be inserted into this project. The [DLSS webcam
demo](https://github.com/jpneagle/dlss5-webcam-demo) is a separate
research/demo code path, not Skyrim's native Feature 18 teacher.

The fresh public-source check adds concrete limits rather than a new teacher:
the Feature 18 lab note reports a 72-case style/preset/quality matrix that
evaluated successfully but wrote only the input-sized upper-left quadrant of a
larger allocation, and its optional-resource probes identify an effective
R-channel `ControlMask` with opposite polarity to the existing reliability
mask. The raw player documents a caller-validation shim and exact NGX
initialization as runtime prerequisites. The webcam demo reconstructs depth,
motion and a bias mask from camera history before calling the native path and
explicitly depends on separately supplied proprietary/community runtimes. These
are useful provenance-tagged research leads; none supplies a portable trainable
teacher for this Skyrim corpus.

The research leads were therefore used only to shape isolated experiments:
local/shifted attention, explicit temporal state, exact native motion vectors,
and separate guide/context conditioning. No closed proxy binary, unknown
checkpoint, AMD port, or replacement teacher path was installed or executed on
the known-good system.

## Historical recommendation (superseded)

Keep the v9 control, v16 numerical leader, v28 static base, v29 temporal base,
v31/v32/v33 capacity candidates, the v40-v42 final-fit lineage and the v43
style-modulation rejection preserved as research artifacts; do not replace the
production runtime or MGO profile. v42
is the best observed final-fit frozen-test score at **0.02611644**, but it has
no independent validation score and its ranking is test-informed because the
cooldown passes followed earlier frozen-test measurements. v33 remains the
preferred independently validation-selected continuation point and
initialization anchor. The v42 gain over v33 is only about `0.00002477` MAE,
and the v40-v42 visual sheets remain close to the spatial base. v43 provides a
controlled negative result for explicit global context-FiLM conditioning: the
parent-preserving mechanism did not improve either validation objective.

The v34 result is an explicit capacity saturation check: adding another
zero-initialized branch raised the model to 3.234M parameters but immediately
lost validation quality and was rejected before test evaluation. The v35
paired-eye probe raised the model to 3.238M parameters and supplied the
opposite-eye RGB crop, but its learned checkpoint also failed to transfer to
the frozen test. Together with the earlier wide scratch, attention, warp,
tone and history probes, and the v36-v38 isolation tests, this makes another
same-corpus architectural, horizon, or loss tweak low-value until the input
conditioning or teacher coverage changes. The new trainer controls are kept
for reproducibility: `--freeze-base-capacity` isolates temporal learning and
`--freeze-parent` isolates an optional extra capacity branch, while the
`--effect-high-frequency-weight` records the v39 residual-detail experiment;
`--fit-all-nontest` records the v40-v42 final-fit mode; the default recipe
remains unchanged. Since v40-v42 only produced a roughly `0.00001229` MAE
gain across three fixed-fit passes and no visible change, further learning-rate
cooldowns on this exact corpus are low-value.

The next high-value step is another capture/data phase, not unbounded tuning of
the same 73-sequence corpus: collect more independent lighting, material,
camera and motion conditions while retaining exact Feature 18 guides, reset
metadata and both-eye pairing. The active `OpenNR Capture` profile is already
configured for this strict contract, but SkyrimVR/MO2/SteamVR were not running
and the available computer-use surface exposed no native Windows application
to start the capture safely during this iteration; no new capture was claimed
or added. The inspected samples show that the remaining error is a conditional
appearance mapping, so a teacher-diverse corpus is more likely to close the
broad tone/shadow/material gap than another small residual branch. Once that
data exists, continue from the v28/v29 recipe with the v33 capacity checkpoint
as the initialization, direct pixel/low-frequency supervision and the existing
temporal-delta and perceptual checks, selected by validation first and then
rechecked on an untouched test split. The requested 0.011 MAE remains an open
target; current evidence does not support claiming that it is reachable from
this fixed corpus alone.

## Runtime boundary

These are offline PyTorch/crop-space model measurements. There is no claim here
of TensorRT parity for the new candidates, stereo delivery, headset image
quality, audible/UI correctness, sustained frame time, reprojection behavior,
or live Skyrim VR acceptance. Those remain separate gates after a model is
actually selected.
