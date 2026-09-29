# Residual target and FP8 study — 2026-09-11

## Outcome

The target-residual formulation was implemented and evaluated as a paired,
validation-controlled research arm. It did not beat the unchanged direct
current-best model. The best available-corpus candidate remains the direct
step-0 replay of the protected checkpoint. The residual 0.75x and 0.5x
resolution branches were therefore not run, because they were explicitly
conditioned on a residual win.

The precision study found that BF16 is the best quality reference in this
replay. Native FP16 is almost identical, while fake E4M3 is finite but slightly
worse and materially more expensive in this unoptimized PyTorch hook
benchmark. Both the original broad-hook diagnostic and a compliant selective
clamp-E4M3 QAT arm were completed for 1,200 updates; neither produced a
promotable winner. No model, active Skyrim profile, Feature-18 route, public
package, or runtime binary was changed.

This is not a full reconstruction of the older six-cohort acceptance corpus:
the prior, high-effect, and old renderer-pilot RGB sources referenced by the
protected run are unavailable. The study uses four intact sources and labels
that boundary explicitly below.

## Reproducible artifacts

The new research tools are:

- [`build_residual_target_view.py`](../tools/build_residual_target_view.py) — preflight, exact byte residual statistics, and immutable view builder.
- [`train_residual_target_pair.py`](../tools/train_residual_target_pair.py) — matched direct/R target training and multi-metric validation.
- [`evaluate_residual_pair.py`](../tools/evaluate_residual_pair.py) — frozen test evaluation and fixed validation galleries.
- [`instrument_fp8_activation_pair.py`](../tools/instrument_fp8_activation_pair.py) — BF16/FP16/fake-E4M3 activation instrumentation.
- [`train_fp8_qat.py`](../tools/train_fp8_qat.py) — short clamp-E4M3 straight-through QAT arm.
- [`benchmark_residual_precision_latency.py`](../tools/benchmark_residual_precision_latency.py) — local PyTorch latency reference.

The output roots are outside the repository so the dirty worktree and known-
good installation remain untouched:

```text
C:\OpenNR\Training\residual_target_view_available_v1_20260911
C:\OpenNR\Training\residual_target_pair_available_v1_20260911
C:\OpenNR\Training\residual_target_pair_available_v1_20260911\postselection
C:\OpenNR\Training\residual_target_pair_available_v1_20260911\fp8_instrumentation
C:\OpenNR\Training\residual_target_pair_available_v1_20260911\qat_clamp448
C:\OpenNR\Training\residual_target_pair_available_v1_20260911\qat_clamp448_selective_v2
C:\OpenNR\Training\residual_target_pair_available_v1_20260911\latency
```

Important manifests and reports:

- `residual_target_view...\manifest.json` — source roots, source hashes,
  exact split counts, row identity, target definition, and residual-file hash.
- `residual_target_view...\residual_stats.json` — statistics written before
  `residual_i16.npy` was materialized.
- `residual_target_pair...\experiment_identity.json` and
  `paired_schedule.json` — protected-checkpoint identity and the shared
  direct/residual schedule.
- `residual_target_pair...\direct\history.json` and
  `residual\history.json` — every 0/400/800/1,200 validation checkpoint,
  including per-source metrics.
- `postselection\test_evaluation.json` — the frozen post-selection test pass.
- `postselection\fixed_gallery_manifest.json` — 40 shared validation sheets.
- `fp8_instrumentation\results.json` — full validation metrics, difficult-case
  heuristics, and 165 mutable-path activation-point statistics for all four
  precision modes.
- `qat_clamp448\history.json` — original broad-hook QAT diagnostic history.
- `qat_clamp448_selective_v2\run.json` — explicit 214-candidate/120-selected
  QAT scope and exclusion decisions.
- `qat_clamp448_selective_v2\history.json` — compliant selective QAT
  0/400/800/1,200 validation history.
- `latency\latency.json` — local 5070 Ti timing reference.

Key integrity identifiers are:

```text
protected checkpoint SHA256       40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756
recovered clone SHA256             5D929D2976250D370AF4AD45C248E44F7F75C4ADA8CF3B3EE130D9C1AB583D8B
residual view manifest SHA256      AC2C3D700C046355BCC54D2627F97D773E3C12D0F4671F1798D767EDC851794A
residual view residual SHA256      B7FD175011ABD2228677ADCDF9A163E6F5F0A64BB1A53E08FD4A5569A6083B4B
paired schedule digest             CC340DD2AFC5AD17F748FAAA20DA649E456A8810054D479EA61EEDC945891F79
direct step-0 checkpoint SHA256    35CF80163F4A02704C3DD3D5AE6E0187036676A88678AA0F3433D171FD737F03
residual step-1200 checkpoint SHA256 1E6947FA9C713C8AFC82D9EFD6B8915DB5FC43B627C6691063EF7915C2A2A87A
selective QAT step-0 checkpoint SHA256 D73002BB3D13CE210722B821BF1F3974C602DB20A99CA9A88D60BA3014884802
selective QAT step-1200 checkpoint SHA256 F93DE3D5223C3FFBD25E8E3EA0DB76A0C6AD8D744AAC577B0F3F657765E4E67F
```

The recovered clone was checked by independent head and parent tensor
digests before training; the original protected file and recovered clone have
different container bytes but identical 385-key head and 304-key parent
tensor sets.

## Corpus and split contract

Each source was read-only audited for RGB `[N,2,3,512,512]` uint8, five guide
channels, eight context channels, two eyes, contiguous 64-frame streams, and
an initial history reset. The fresh-session source does not carry the same
strict flags in its `complete.json`, so the view builder independently checked
the row-level stream contract before including it.

| source label | source sequences | train sequences / eye rows | validation sequences / eye rows | test sequences / eye rows | source role |
|---|---:|---:|---:|---:|---|
| `latest_crop` | 18 | 11 / 1,408 | 3 / 384 | 4 / 512 | latest every-frame crop temporal cache |
| `fresh_session` | 27 | 16 / 2,048 | 5 / 640 | 6 / 768 | renderer-conditioning fresh session |
| `renderer_state` | 37 | 23 / 2,944 | 6 / 768 | 8 / 1,024 | renderer-state distillation cache |
| `new_pairs` | 19 | 12 / 1,536 | 3 / 384 | 4 / 512 | strict renderer-pair cache |
| **total** | **101** | **62 / 7,936** | **17 / 2,176** | **22 / 2,816** | **12,928 eye rows** |

The four source labels are the cohort labels in the residual view. The view
preserves every original row, including guides, context, stereo eye, frame ID,
reset, route, teacher settings, motion scale, and source paths, and adds
`cohort_label`, `face_label`, and `high_effect_label` fields. All four intact
sources had zero face/high-effect fields, so those values remain null and are
reported as unavailable. No detector, target-dependent filter, or invented
semantic label was applied.

The protected run's old `prior`, `high_effect`, and `renderer_pilot` RGB roots
are missing. Their old corrected guide overlays cannot reconstruct RGB. Thus
the four-source result below is an available-corpus ablation, not a six-cohort
promotion gate.

The protected checkpoint's own run manifest is explicit about the original
cohort order and mixture: `prior`, `high_effect`, `renderer_pilot`,
`fresh_session`, `renderer_state`, and `new_pairs`, with source probabilities
`[0.40, 0.15, 0.10, 0.15, 0.10, 0.10]`. The residual study could only use
`fresh_session`, `renderer_state`, and `new_pairs` from that list plus the
separately labeled intact `latest_crop` source. It therefore used equal
`0.25` probabilities over four sources. `latest_crop` is not a substitute
identity for `prior`, and the four-source training/validation/test split must
not be described as the protected six-cohort split.

## Recovery audit — 2026-09-11

A final read-only search was made across the mounted local volumes before
closing the no-recapture branch. It found one additional intact capture, but
not a recoverable copy of the missing six-cohort RGB corpus:

- `C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910` contains 14
  sequences and 224 frames. All 224 frames are complete, have contiguous
  16-frame streams, initial `[true, true]` resets, no mid-sequence resets,
  full-frame validation, and all six renderer-conditioning resources. Its
  sequence metadata identifies it as a
  `full_resolution_master_sequence` at 2,496x2,688 color and 1,664x1,792
  guide resolution. It has no split field and zero sequence-ID overlap with
  the 101-sequence residual view, so it remains separate capture/validation
  evidence rather than being mixed into the same-split train/validation/test
  comparison. Its metadata also exposes no object/material semantic labels.
- `G:\OpenNR_Captures_VariedHighEffect_0.5.5_20260906` exists as an empty
  directory. `G:\OpenNR_Capture_Setup_Backups` contains only one DLL and three
  settings snapshots. `C:\OpenNR_Captures_FullRes_Pilot_20260904` is a
  junction to `H:\OpenNR-ColdStorage\RawCaptures\OpenNR_Captures_FullRes_Pilot_20260904`,
  but H: is not mounted and the target is unavailable.
- The old face detector output at
  `E:\OpenNR_FaceAudit_Merged_20260905\result.json` covers 5,360 rows with
  rows hash `d1a699d0...` across 135 sequence IDs, while this study's exact
  12,928-row view has rows hash `06e4d483...` across 101 different sequence
  IDs. Because there is zero sequence-ID overlap, those face detections cannot
  be attached to this study. The current sources therefore retain
  `face_label=null` and `high_effect_label=null`.

The referenced missing RGB roots on E:, the corresponding G: cold-storage
path, and the H: junction target were all absent or inaccessible in this
local audit. No mounted network mappings were present. Recovering the old
RGB plus its split/category manifests, or recapturing them, is still required
to reopen the original six-cohort gate; no data was moved, deleted, or
rewritten during this audit.

## Requirement closure

| requested item | current evidence | disposition |
|---|---|---|
| 1. Residual view, exact normalization, preserved guides/temporal/stereo metadata | materialized four-source view, int16 residual, hashes, p99/p99.9 statistics | complete for recoverable sources; original missing RGB remains a hard scope boundary |
| 2. Matched direct versus residual training | shared schedule, seed, optimizer, windows, checkpoints, and frozen test pass | complete; residual rejected |
| 3. Multi-metric checkpoint evaluation and galleries | aggregate/per-source histories, temporal/warp/stereo/residual metrics, 40 fixed galleries | complete for available labels; face/high-effect/category partitions unavailable and not fabricated |
| 4. Residual 1.0x/0.75x/0.5x resolution and latency | residual 1.0x prerequisite failed | correctly gated; lower-resolution branches not run |
| 5. BF16/FP16/E4M3 instrumentation and difficult-case checks | 165-point instrumentation, finite/saturation counters, bright/clipped/large-residual diagnostics | complete for available corpus; validated fire/magic/HDR manifests unavailable |
| 6. Selective saturated-E4M3 QAT | compliant 214-candidate/120-selected scope, 1,200 updates, cohort guardrail audit | complete; QAT rejected |
| 7. Combined winner | no residual or QAT winner passed the prerequisite gates | correctly not run; no combined model promoted |

## Exact residual target and tail audit

The target is explicitly:

```text
B = source rgb.npy[:, 0] / 255       # captured pre-DLSS5/base RGB
T = source rgb.npy[:, 1] / 255       # captured Feature-18 teacher RGB
R = T - B
```

`residual_i16.npy` stores the exact uint8 difference `rgb[:,1]-rgb[:,0]` in
int16 form, so the view does not introduce a float16 target-rounding step.
There is no clipping, tone mapping, HDR conversion, or teacher recomputation.

The statistics pass completed before residual materialization. Global exact
discrete order statistics in normalized RGB units were:

| distribution | p50 | p99 | p99.9 |
|---|---:|---:|---:|
| absolute `|R|` | 0.019608 | 0.152941 | 0.239216 |
| signed `R` | 0.007843 | 0.121569 | 0.184314 |

Absolute p99 by source was `latest_crop 0.164706`, `fresh_session 0.149020`,
`renderer_state 0.145098`, and `new_pairs 0.164706`. The exact histograms and
per-channel values are in `residual_stats.json`.

## Matched direct versus residual training

Both arms consumed the same serialized schedule (`cc340dd2...891f79`), with
seed 911, equal source probabilities, batch 1, eight-frame windows, two-frame
burn-in, AdamW, head LR `1e-4`, parent LR `1e-5`, weight decay `1e-4`, and the
same linear warm-up/cosine factor. The direct arm optimized `P-T`. The
residual arm optimized `R_hat-R` and delivered `clamp(B+R_hat,0,1)`; its new
three-channel output was zero initialized. Only that new output trained for
the first 200 updates, then the copied head body and parent were unfrozen.

Validation metrics are weighted over all validation pixels in the four
available sources. `warp` is a diagnostic proxy using the existing audited
positive-sign Feature-18 motion convention, border padding, and current-frame
motion-valid channel; it is not a calibrated reprojection claim.

| arm / step | MAE | PSNR (dB) | temporal delta MAE | warp proxy MAE | stereo disagreement MAE |
|---|---:|---:|---:|---:|---:|
| direct 0 | **0.018492544** | **30.91061** | **0.007076019** | **0.020235348** | **0.027771651** |
| direct 400 | 0.019516541 | 30.61792 | 0.007140510 | 0.021221285 | 0.028428975 |
| direct 800 | 0.019144703 | 30.61188 | 0.007131664 | 0.020826754 | 0.028473555 |
| direct 1,200 | 0.018707354 | 30.73547 | 0.007138352 | 0.020423204 | 0.027832003 |
| residual 0 (raw B identity) | 0.024931051 | 28.03603 | 0.007956540 | 0.026485467 | 0.034914090 |
| residual 400 | 0.024922355 | 28.97329 | 0.008698172 | 0.026470605 | 0.033780134 |
| residual 800 | 0.023156718 | 29.36894 | 0.008720697 | 0.024736173 | 0.032830902 |
| residual 1,200 | **0.021912984** | **29.74859** | **0.008649760** | **0.023501993** | **0.031859231** |

Residual step 1,200 is better than raw B, but it is still 18.5% higher MAE
than direct step 0 and loses the direct step-0 primary/guardrail comparison.
The direct arm's post-step-0 adaptation also regressed its available-corpus
validation MAE, so its unchanged step-0 candidate was retained.

The residual-target error `|R_hat-R|` at the residual checkpoints was
`0.024931051 / 0.025001968 / 0.023302204 / 0.022034341` for steps
`0 / 400 / 800 / 1,200`, respectively. It is not applicable to the direct
arm's evaluator because that arm predicts RGB directly; the direct arm's
primary metric remains `|P-T|`.

## Frozen test result

Only after the validation choice was frozen were test rows loaded. The selected
direct step-0 and residual step-1,200 candidates were evaluated on all 22
available-corpus test sequences.

| candidate | MAE | PSNR (dB) | temporal delta MAE | warp proxy MAE | stereo disagreement MAE | improvement over raw B |
|---|---:|---:|---:|---:|---:|---:|
| direct step 0 | **0.021417020** | **30.10596** | **0.007676988** | **0.024295284** | **0.029501052** | **26.346%** |
| residual step 1,200 | 0.025235125 | 28.78091 | 0.009436644 | 0.028110592 | 0.035306065 | 13.216% |

Residual minus direct on test is `+0.003818105` MAE, `-1.32505 dB` PSNR,
`+0.001759656` temporal-delta MAE, `+0.003815308` warp-proxy MAE, and
`+0.005805012` stereo-disagreement MAE.

The gallery contains 40 shared validation sheets (four sources, five fixed
frame IDs `1,16,32,48,64`, two eyes), with B, T, direct output, residual output,
and four-times absolute errors. It is visual context, not a replacement for
the numeric gates. A visual sample review showed the direct output following
the teacher's tonal lift more closely; the residual output remained visibly
closer to B.

This is not a labeled scene-category gallery. The intact rows contain no
validated face, foliage, armor, shadow, fire, highlight, magic, or HDR labels
or masks. The fixed sheets are therefore preserved as an unlabeled A/B gallery;
bright, clipped-channel, large-residual, and motion/temporal measurements are
reported as explicit heuristics or contracts below, not relabeled as those
scene categories.

## BF16, FP16, and fake E4M3 instrumentation

The selected direct step-0 model was run over the complete available-corpus
validation split in four modes. Fake E4M3 was inserted at 165 parent/head
Conv2d and Linear outputs; the frozen DINO encoder was excluded.

| mode | MAE | PSNR (dB) | temporal delta MAE | warp proxy MAE | stereo disagreement MAE | nonfinite output |
|---|---:|---:|---:|---:|---:|---:|
| BF16 autocast | **0.018492544** | **30.91061** | 0.007076019 | **0.020235348** | 0.027771651 | 0 |
| FP16 autocast | 0.018506640 | 30.90369 | **0.007071917** | 0.020248962 | 0.027796147 | 0 |
| unsaturated fake E4M3 | 0.018523702 | 30.90938 | 0.007321986 | 0.020257610 | **0.027747871** | 0 |
| clamp(-448,448)+fake E4M3 | 0.018523702 | 30.90938 | 0.007321986 | 0.020257610 | **0.027747871** | 0 |

No mutable-path activation exceeded ±448: the largest observed absolute
activation was about 212 (212.5 in FP16). Consequently, the unclamped and
clamped E4M3 outputs were identical in this corpus. The top fake-E4M3 mean
finite quantization errors were approximately `0.1058` at
`head.up.0.0`, `0.1040` at `head.up.1.0`, and `0.0896` at
`head.bottleneck.1.layers.3`; these are activation-scale diagnostics, not
output-MAE values.

Difficult-case partitions were measured as predeclared heuristics, not labels:

- bright: any frame eye with teacher luma at least 0.8;
- clipped RGB: any teacher channel at least `254.5/255`, called HDR-like only
  as a diagnostic, not as an HDR capture claim;
- large residual: any pixel with `|R|` at least the global residual p99;
- face, foliage, armor, shadow, fire, and magic: unavailable because no
  validated category/mask manifests are present in the intact sources;
  clipped-channel remains only an SDR diagnostic heuristic, not HDR data.

For BF16, the bright heuristic MAE was `0.0979161` versus raw-B identity
`0.0911302`; clipped-RGB heuristic MAE was `0.1095412` versus identity
`0.1055425`; large-residual-tail MAE was `0.0813971` versus identity
`0.1501715`. Fake E4M3 raised those three values to `0.0991187`, `0.1100503`,
and `0.0816874`, respectively. These partitions are diagnostic-only and do
not establish fire or HDR acceptance.

## QAT result

The first QAT pass was an intentionally broad diagnostic: a straight-through
fake quantizer was attached to 165 parent/head Conv2d and Linear outputs,
excluding the frozen DINO encoder. It started from direct step 0 and replayed
the same 1,200 windows:

| QAT step | MAE | PSNR (dB) | temporal delta MAE | warp proxy MAE | stereo disagreement MAE |
|---:|---:|---:|---:|---:|---:|
| 0 | **0.018523702** | **30.90938** | **0.007321986** | **0.020257611** | **0.027747871** |
| 400 | 0.018891368 | 30.79451 | 0.007380819 | 0.020615264 | 0.027989780 |
| 800 | 0.018923027 | 30.72311 | 0.007366039 | 0.020614474 | 0.028165115 |
| 1,200 | 0.018748838 | 30.77503 | 0.007382037 | 0.020459625 | 0.027850385 |

That broad diagnostic never recovered its step-0 fake-quant baseline. It is
rejected as an adapted winner; its step-0 fake-E4M3 replay remains an
experiment record only.

The required selective QAT arm was then run separately from the same direct
step-0 checkpoint, same seed (`911`), same source probabilities, same serialized
1,200-window schedule, and FP16 autocast. Its fake-quant scope was recorded
before training: 214 Conv/Linear candidates, 120 selected points, and 94
explicit exclusions. The selected points cover expensive spatial convolutions,
the trainable semantic projection, and the frozen encoder's 48 attention
QKV/attention-projection/FFN linears. The exclusions leave the five temporal
modules, the affine/final and native gate outputs, normalization-boundary
reducers, the 51 GroupNorm-adjacent head convolutions, the encoder stem, and
23 tiny operations in the surrounding FP16/BF16 compute path.

| selective QAT step | MAE | PSNR (dB) | temporal delta MAE | warp proxy MAE | stereo disagreement MAE |
|---:|---:|---:|---:|---:|---:|
| 0 | **0.018499167** | **30.90742** | **0.007182709** | **0.020240311** | **0.027869474** |
| 400 | 0.018911026 | 30.74223 | 0.007235892 | 0.020642320 | 0.028315480 |
| 800 | 0.018906806 | 30.67097 | 0.007201593 | 0.020616782 | 0.028562339 |
| 1,200 | 0.018809939 | 30.67619 | 0.007213903 | 0.020522164 | 0.028451327 |

The FP16 no-fake-quant reference on the same available validation corpus is
MAE `0.018506640`, temporal-delta MAE `0.007071917`, warp proxy MAE
`0.020248962`, and stereo disagreement MAE `0.027796147`. Selective step 0 is
within `-0.04%` MAE of that reference, but its temporal delta is `+1.57%`
worse and its stereo disagreement is `+0.26%` worse. After adaptation, step
1,200 is `+1.64%` MAE, `+2.01%` temporal delta, `+1.35%` warp, and `+2.36%`
stereo versus FP16. The per-source MAE changes at step 1,200 are `-0.061%`
(fresh session), `-1.765%` (latest crop), `+8.300%` (new pairs), and `+0.012%`
(renderer state); new-pairs stereo disagreement is also `+8.413%`. That
exceeds the requested per-cohort guardrail and there is no materially better
validated runtime measurement. The selective arm is therefore rejected as
well, and no QAT or combined winner is promoted.

## Local timing reference

The benchmark used an NVIDIA GeForce RTX 5070 Ti, one fixed validation stereo
sequence, 64 frames per pass, and PyTorch autocast. It is not an optimized
TensorRT/FP8 engine measurement and not live Skyrim VR frame-time, headset, or
VR-budget acceptance.

| variant | mean ms/frame | mean FPS |
|---|---:|---:|
| BF16 | 29.435 | 33.97 |
| FP16 | **28.697** | **34.85** |
| fake clamped E4M3 hook | 43.609 | 22.93 |

The fake-E4M3 timing includes Python forward-hook/dequantization overhead and
must not be used as a hardware FP8 speed claim.

## Decisions and remaining blockers

1. Keep the protected direct step-0 model as the current quality candidate;
   use BF16 as the quality reference and FP16 only where its small measured
   arithmetic difference is useful. Do not promote the residual model.
2. Do not run residual 0.75x/0.5x or a residual/FP8 combined branch from this
   study: the residual 1x prerequisite failed, and neither broad nor selective
   QAT produced a winner.
3. Do not call fake E4M3 deployment-ready. It is finite and below the ±448
   saturation range in this corpus, but it is slightly worse than BF16 and has
   no optimized runtime evidence.
4. Do not call any result live-accepted. Source/config/package health,
   validation/test image quality, motion-warp diagnostics, runtime ownership,
   headset quality, audible/UI state, deployment, temporal readiness, and VR
   budget remain separate acceptance axes.
5. To reopen the original broad gate, recover or recapture the missing RGB
   sources for prior/high-effect/old renderer-pilot, add validated face and
   high-effect/fire/HDR manifests, and rerun the same immutable paired design
   without altering the protected Feature-18 teacher path.
