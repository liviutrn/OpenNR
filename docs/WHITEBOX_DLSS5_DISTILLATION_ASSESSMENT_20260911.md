# White-box DLSS5 distillation assessment — 2026-09-11

## Decision

The recovered white-box route is **not ready to be used as a DLSS5 teacher for
OpenNR-VR**.  The best available first-frame/control contract improved the
captured source baseline on this six-sequence validation sample, but the
recovered output remains far outside the direct Gate-A parity target.

I therefore stopped before building a teacher-feature cache, adding projection
heads or losses, and starting the paired 2,400-step Control versus White-box
experiment.  That is intentional: training against a graph that has not first
been shown to reproduce the native target would mix teacher-contract error with
student-learning error and would not answer the causal question in the supplied
objective.

The route is retained as a research-only, inspectable 71-block graph.  It is
currently useful for implementation inspection and as a weak RGB enhancement
prior, but not as a faithful internal-supervision teacher for the current
Feature-18 OpenNR corpus.

## Baseline freeze and protected boundaries

The requested code tag was created:

```text
baseline_pre_whitebox_distill
```

It points to code commit `b71f8313250b70af5bf4513d91596dbebae0bff8`.  The
working tree was already dirty (439 status entries at freeze time), so the tag
is deliberately only a code reference; no checkout, reset, cleanup, or
overwrite was performed.

The quality baseline is the separately protected checkpoint:

```text
C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt
SHA256 40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756
architecture semantic_joint_parent_v1
step 800
```

The checkpoint remains unchanged.  Its embedded parent state is still
available through the recovery copy at
`C:\OpenNR\Training\recovery\semantic_full_eye_state_short_20260910\recovered_parent.pt`;
the original external parent path recorded by the older run is absent, but
that absence did not require altering the protected student.

No OpenNR capture label, cache, native DLL, active Skyrim runtime, student
architecture, optimizer, sampler, or student checkpoint was changed.  The
first arbitrary-random-feature backend probe was discarded because it did not
respect the recovered model's 16-channel input contract; all measurements
reported below use a real packed Skyrim crop or the source test suite.

## Phase 1 — isolated recovered implementation

The local artifact is the separate `MLX-DLSS` recovery, not the earlier
12.7k-parameter portable approximation and not the rejected RGB-only static
ONNX graph.  The recovered package describes a stateless first-frame neural
rendering transformer with 649 logical tensors and a 16-channel NHWC input.
The logical weight file used here is:

```text
C:\OpenNR\research\mlx_dlss_feature_distill_20260911\private\weights\dll_E16BCF15\dlssnr-weights-logical.safetensors
SHA256 D64261D8F0173F9266C250F6B6348406EDAE0C8F7297DD6122B30EC5AD5C476C
```

The current source clone is commit
`0ca2deab092fe6f3e331bf4f616271dbc64521d0`, with the older comparison clone
at `4549ce6d99837e4fb182c38a028d8e96bc28c0df`.  The native DLL used only as
the already-captured-label provenance reference is:

```text
E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll
SHA256 E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E
```

The source's Torch reference unit suite ran successfully:

```text
26 tests ran, 1 skipped, 0 failures
```

On one real 512×512 Skyrim crop prepared with the recovered input contract,
the CPU reference and CUDA reference both produced finite 512×512×4 heads.
At the final composed RGB image level, the cross-backend differences were:

| Comparison | Network time | Image MAE | Image RMSE | Image max abs |
|---|---:|---:|---:|---:|
| CPU reference vs CUDA reference | 2.49 s vs 1.25 s | 0.001230 | 0.001843 | 0.03009 |
| CUDA reference vs CUDA fast | 1.25 s vs 1.61 s | 0.001972 | 0.002870 | 0.03418 |

The raw four-channel heads differ more (`0.04364` MAE for CPU versus CUDA
reference and `0.05200` for CUDA reference versus fast CUDA), so the composed
RGB numbers must not be described as bit identity.  The valid CUDA probe used
about 1.38 GiB peak allocation for reference precision and 1.46 GiB for fast
precision on the RTX 5070 Ti, with Python 3.12.10, Torch 2.7.1+cu128 and CUDA
12.8.

There is **no TileLang implementation** in the local recovered source or
workspace.  Consequently the requested three-way Torch/CUDA/TileLang parity
check cannot be completed.  The available Torch/CUDA path is runnable and
deterministic enough for isolated research, but it is not an independently
reproduced three-backend reference.

## Reconciling the upstream accuracy claim

The upstream README does claim neural-rendering error of `0.004–0.005` MAE
against NVIDIA, but its stated scope is five private `1152–1408` pixel
game-face crops with DLL goldens.  The same documentation calls the project an
experimental port rather than a game integration, and the recovery notes say
that the private weights/captures remain outside the repository.  The recovery
notes also list end-to-end style, ControlMask, display-codec, postprocessing,
jitter, disocclusion and temporal-history parity as remaining falsifiers.

Our Gate-A result therefore does **not** prove that the upstream private
benchmark was fabricated or that the recovered graph can never reach that
number.  It proves that the currently available package and wrapper have not
reproduced the native Skyrim Feature-18 target under our test contract.  The
comparison is not identical to the published benchmark: our cache contains
`512×512` crops from larger `2496×2688` Skyrim renders; the native labels record
intensity/tone/structure `2`, while the empirically best recovered arm used
those controls at `1`; and the recovered arm was the stateless first-frame
path, without a demonstrated native history/depth/motion equivalence.

The DLL itself is the documented `310.8.0.0` build, and running the matching
older `4549ce6` source/weight lineage on the same Skyrim cache produced the same
`0.019943` MAE.  This makes a simple checkout-version explanation less likely.
An apples-to-apples reproduction of the private `1152–1408` golden bundle would
still be valuable, but the separate full-frame Skyrim rescue test below has now
been completed with the exact native first-frame capture contract.

## Phase 1b — full-frame Skyrim first-frame rescue test

Before declaring the recovered weights unusable or spending more training data,
the first frame of the newest retained full-eye master sequence was replayed
through the recovered graph.  This did not collect new data and did not modify
Skyrim, the active MO2 profile, the native DLL, the capture, or the weights.

The source sequence was:

```text
C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910\seq-1789071762719-5
```

The normal capture validator reports 16 complete frames, 16 full-frame/master
frames, 448 artifacts, zero missing files, zero duplicate IDs/hashes, zero
all-zero tensors, and no warnings.  Frame 1 is a clean first-frame contract:

- both eyes, `feature18_stereo`, one Feature 18 pass, model resolution 100%;
- full color `2496×2688`, native depth/motion guides `1664×1792`;
- exact native bound motion resources are present for both eyes;
- `history_reset=[true,true]`;
- native recorded controls are style `0`, intensity/tone/structure `2`, skin
  `-1`, automatic mask enabled, UI correction disabled.

The replay reads the raw full-frame `R8G8B8A8_UNORM` bytes for the input and
teacher, not the accompanying 512×512 crop.  It verifies and fingerprints the
full-frame depth and motion resources as part of the contract, then runs the
recovered first-frame graph with `frame_index=0`.  This is the correct scope for
the recovered graph: its first-frame network accepts RGB plus scalar controls;
the captured native guides are retained as proof of the Skyrim call boundary,
not silently replaced with optical flow or invented tensors.

### Full-frame result

| Replay arm, both eyes | Source → native teacher | Recovered → native teacher | Change vs source |
|---|---:|---:|---:|
| Native recorded scalar controls `2/2/2`, auto mask mapped to scalar `2` | `0.01807120` | `0.02756559` | `+0.00949439` worse |
| Recovered package's documented/default `1/1/1` mapping, auto mask on | `0.01807120` | `0.01350228` | `-0.00456891` better |
| Same `1/1/1` diagnostic with recovered auto-mask channels disabled | `0.01807120` | `0.01324642` | `-0.00482478` better |

The first row is the literal native-control replay and is the primary exact
contract result.  It fails the upstream-style `MAE≤0.007` reference and is
worse than the unprocessed Skyrim input.  The second row is a diagnostic, not a
renaming of the native contract: the upstream package documents strength `1`
as its default, and the earlier crop sweep also found `1/1/1` empirically best.
It improves the source but still misses `0.007` by almost 2×.  Disabling the
recovered automatic-mask channels changes the result only slightly, so the
missing mask mapping is not the whole explanation.

The replay outputs are preserved here:

- [`literal native-control result`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/fullframe_reproduction_skyrim_seq5_frame1_reference_20260911/fullframe_reproduction.json)
- [`best recovered-control result`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/fullframe_reproduction_skyrim_seq5_frame1_recovered_best_controls_20260911/fullframe_reproduction.json)
- [`best-control eye 0 contact sheet`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/fullframe_reproduction_skyrim_seq5_frame1_recovered_best_controls_20260911/eye0_contact_sheet.png)
- [`best-control eye 1 contact sheet`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/fullframe_reproduction_skyrim_seq5_frame1_recovered_best_controls_20260911/eye1_contact_sheet.png)
- [`reproducible evaluator`](D:/.CODEX_Projects/OpenNR-VR/tools/evaluate_mlx_dlss_fullframe.py)

### What this proves and does not prove

This closes the biggest crop-context loophole: the graph was run on the whole
Skyrim eye image, so the native teacher was not produced from a full frame and
then compared only against a student that saw a small crop.  Full-frame context
does not rescue the current package.  The contact sheets show substantial
localized hue/skin/detail errors even where the whole-image MAE looks moderate.

It still does not prove that the underlying recovered tensors are intrinsically
wrong.  The native DLL's internal first-frame treatment, automatic-mask content,
and final post-composition are opaque; the portable graph only has a scalar
approximation for those pieces.  Therefore the defensible conclusion is narrower:

> The current recovered weights plus current MLX-DLSS preprocessing/composition
> have not reproduced a real Skyrim native Feature 18 frame at full resolution.
> They remain a research/alternate-RGB lineage, not a native-teacher replacement
> and not a reason to start another training run.

The next high-value evidence is a private upstream golden bundle or a native
first-frame capture whose control/post-composition mapping is independently
verified against the recovered package.  More ordinary Skyrim crops are not the
next step; they would add examples without resolving this already-demonstrated
full-frame compatibility gap.

### Zero-data style and settings matrix

The same fixed frame was then replayed nine times with the input, native target,
weights, resolution, and `frame_index=0` held constant.  Only the recovered
style/control settings changed.  This was a diagnostic matrix; it did not
collect data, change labels, or start training.

| Recovered arm | Mean recovered → native teacher MAE | Change vs source |
|---|---:|---:|
| Default style `0`, `1/1/1`, automatic mask off | **0.01324642** | `0.00482478` better |
| Default style `0`, intensity `0.75`, otherwise `1/1/1`, mask off | `0.01325355` | `0.00481765` better |
| Default style `0`, `1/1/1`, automatic mask on | `0.01350228` | `0.00456891` better |
| Default style `0`, detail/colour `0.5/0.5` | `0.01419076` | `0.00388044` better |
| Default style `0`, intensity `0.5` | `0.01419076` | `0.00388044` better |
| Natural style `1`, otherwise `1/1/1`, mask off | `0.01420563` | `0.00386556` better |
| Cinematic style `2`, otherwise `1/1/1`, mask off | `0.01543814` | `0.00263306` better |
| Default style `0`, local tone/structure `2/2` | `0.01676686` | `0.00130434` better |
| Default style `0`, detail/colour `2/2` | `0.01990605` | `0.00183485` worse |

This confirms the visual impression that the recovered graph has a real neural
style response.  It does **not** support relabeling the result as cinematic or
natural: the native target is style `0`, and style `0` remained the closest arm.
It also shows that conservative composition and the absence of the recovered
automatic-mask approximation are more useful than increasing the effect
strength.  None of the arms reaches the permissive `0.007` parity reference.

The complete matrix, per-eye metrics, and contact sheets are saved in
[`fullframe_control_matrix.json`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/fullframe_control_matrix_skyrim_seq5_frame1_20260911/fullframe_control_matrix.json).

## Phase 2 — Gate A against our captured NVIDIA labels

The decisive run used the immutable packed validation cache:

```text
D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908
rows.json SHA256 73B0086F192277ED206BCC2165D0A8BB45779E320B5D61CC42B391D9E3FE479C
```

Selection was six held-out validation sequences, frame IDs 1/16/32/48/64, and
both eyes: 60 eye rows total.  This is a bounded validation gate, not a new
training corpus.  The best tested contract was the recovered package's
standard profile with all scalar controls at 1, automatic masking enabled,
skin structure `-1`, and automatic-mask structure `1`.

For each row:

```text
A = captured NVIDIA DLL teacher target
B = recovered MLX-DLSS composed RGB output
```

| Measurement over 60 eye rows | MAE | PSNR | max abs |
|---|---:|---:|---:|
| Captured source → A | 0.02141584 | 30.7666 dB | 0.24732 |
| Recovered B → A | 0.01994314 | 31.7269 dB | 0.20213 |

The recovered output is 0.00147270 MAE below the captured source baseline,
which is a 6.8767% relative improvement on this sample.  It was better than
the source on 44 of 60 rows.  That is evidence that the graph is doing useful
RGB work; it is **not** evidence of DLSS5 parity.

Gate A's direct target is approximately `MAE <= 0.005–0.007`.  The best
recovered result is `0.01994314`, or 2.85 times the permissive `0.007` limit,
so Gate A fails decisively.  The SqueezeNet1_1 diagnostic feature distance was
`0.10944720` mean, `0.10880316` median and `0.18928561` maximum.  This is a
training-only normalized diagnostic, not LPIPS and not a VR acceptance metric.
The repeated output was deterministic at max absolute difference `0.0`.

Per-sequence means show why the small RGB improvement should not be promoted
as broad teacher fidelity:

| Validation sequence | Source → A | Recovered B → A | Better rows |
|---|---:|---:|---:|
| `seq-1788876383803-25` | 0.01229718 | 0.01249137 | 6/10 |
| `seq-1788876392977-26` | 0.03236590 | 0.03061959 | 8/10 |
| `seq-1788876403467-27` | 0.02564996 | 0.02384662 | 10/10 |
| `seq-1788876412276-28` | 0.01688732 | 0.01702482 | 3/10 |
| `seq-1788876466148-29` | 0.01752418 | 0.01471119 | 9/10 |
| `seq-1788876473658-30` | 0.02377051 | 0.02096527 | 8/10 |

A small predeclared control check supports the interpretation that the
recovered graph's control contract is not the native Feature-18 contract:

| Arm | Rows | Recovered → A | Source → A | Notes |
|---|---:|---:|---:|---|
| Standard, all controls 1, auto mask on | 60 | **0.01994314** | 0.02141584 | Best tested arm |
| Standard, all controls 1, auto mask on | 20 | 0.02155548 | 0.02233154 | First two sequences only |
| Native-looking scalar controls 2, auto mask on | 60 | 0.02451224 | 0.02141584 | Full six-sequence run; worse than the standard arm |
| Scalar controls 2, auto mask off | 30 | 0.02505782 | 0.02343768 | Existing earlier smoke run |

The 20- and 30-row arms are not direct substitutes for the 60-row result, but none
approaches the Gate-A range.  The full best-arm evidence is saved in
[`gate_a.json`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/gate_a_validation_six_standard_feature/gate_a.json)
and the side-by-side contact sheet is
[`gate_a_contact_sheet.png`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/gate_a_validation_six_standard_feature_gallery_fixed_best/gallery/gate_a_contact_sheet.png).

As a separate generalization check, the same best control contract was run on
the surviving `RendererPairsStrict_20260908` validation cohort: 30 eye rows,
three held-out sequences and the same five frame IDs.  Source→A MAE was
`0.04672921`; recovered B→A MAE was `0.03288951`, a 29.6168% reduction from
the source baseline, with SqueezeNet distance `0.09963329`.  This confirms a
stronger weak-RGB effect on that cohort, but it is still 4.70 times above the
permissive `0.007` Gate-A limit.  It strengthens the conclusion that the graph
can be useful as an alternate RGB enhancer while failing the more important
requirement of being a close native DLSS5 teacher.

## Phase 3/4 — internal stage map and diagnostics

The recovered graph has procedural operations rather than named module stages,
so I mirrored the reviewed forward order in a separate trace tool.  The trace
head matched the normal model head at max absolute difference `0.0` on the
first checked source and teacher inputs.

The five traced locations below are exact shapes for a 512×512 crop under fast
precision.  The source→teacher response is the mean absolute change when the
stateless recovered graph receives the captured source image versus the
captured teacher image as its RGB input.  It is not a comparison to native
DLSS5 internal tensors, which were not captured.

| Stage | Semantic location | Shape NHWC | dtype | mean / std | min … max | FP16 size | source→teacher mean abs | relative |
|---|---|---|---|---:|---:|---:|---:|---:|
| F1 | encoder blocks 1–3 | `[1,256,256,32]` | fp16 | 0.0871 / 1.0771 | -12 … 10 | 4.00 MiB | 0.18995 | 0.2808 |
| F2 | encoder transition block 8 | `[1,64,64,128]` | fp16 | 0.0301 / 2.3708 | -12 … 14 | 1.00 MiB | 0.60278 | 0.3457 |
| F3 | global blocks 31–38 | `[1,8,8,1024]` | fp16 | -0.0045 / 0.9070 | -4.5 … 3.75 | 128 KiB | 0.40987 | 0.5469 |
| F4 | decoder blocks 49–55 | `[1,32,32,256]` | fp16 | 0.0702 / 1.5667 | -7.5 … 8 | 512 KiB | 0.72608 | 0.5329 |
| F5 | pre-output block 70 | `[1,512,512,32]` | fp16 | -0.7566 / 2.6663 | -11.0859 … 10.1719 | 16.00 MiB | 0.48714 | 0.2498 |

The selected research candidates would be F2/F3/F4 because they span an
intermediate encoder, the global representation and an intermediate decoder.
That selection is only a map for a possible future experiment.  It is not a
promotion decision: the trace also showed large left/right and sparse-frame
responses, and this first-frame graph has no learned native motion/depth/
history input.

The full trace, including stereo and sparse-frame diagnostics, is saved in
[`stage_trace.json`](C:/OpenNR/research/mlx_dlss_feature_distill_20260911/results/stage_trace_validation_2_v2/stage_trace.json).
The reproducible diagnostic tools are
[`evaluate_mlx_dlss_gate_a.py`](D:/.CODEX_Projects/OpenNR-VR/tools/evaluate_mlx_dlss_gate_a.py)
and
[`trace_mlx_dlss_stages.py`](D:/.CODEX_Projects/OpenNR-VR/tools/trace_mlx_dlss_stages.py).

## Phases 5–10 — intentionally not started

The following artifacts were **not** created or run:

- no `cache_dlss5_features.py` output or bulk FP16 teacher feature cache;
- no training-only student projection heads;
- no residual or feature loss was added;
- no Control/White-box 2,400-step pair was launched;
- no 0/400/800/1200/1600/2000/2400 checkpoint table was generated;
- no white-box checkpoint was promoted.

This preserves the clean causal interpretation required by the objective.  A
student can sometimes learn from a weak or mismatched teacher, but that would
be a different experiment from testing whether recovered DLSS5 internal
supervision improves the current OpenNR student.

## Do we need more old raw training data?

Not for this decision.  The current packed validation cache was sufficient to
run a 60-eye Gate-A test, and the existing training caches remain available as
separate lineages.  Collecting more ordinary Skyrim crops from the same
Feature-18 contract would not be the next useful action: it would increase
sample count without repairing the observed teacher-contract/parity gap.

To reopen this route, the missing inputs are compatibility evidence rather than
a large replacement corpus:

1. The TileLang implementation and exact commit, if three-backend parity is a
   requirement rather than an optional implementation detail.
2. A native first-frame/no-history golden path from the same DLL build, with
   the exact preprocessor/control mapping used by the recovered 16-channel
   graph.  Ideally this includes a small set of native intermediate tensors or
   a vendor-compatible golden bundle.
3. A definitive mapping for how native Feature-18 depth, motion, jitter,
   history/reset and post-composition correspond to the tested stateless
   RGB/control input and to the source tree's separate temporal wrapper.  The
   base neural graph does not consume depth or motion directly; the wrapper
   converts motion/depth/history into additional 16-channel history features,
   but that wrapper path was not proven equivalent to the native Feature-18
   path used for these labels.
4. After that mapping is proven, a fresh 20–50-crop compatibility suite with
   fixed faces/skin/foliage/armor/interiors, lighting/effect strata, both eyes,
   and reset-qualified temporal anchors.

Until those are available, the correct next action is to preserve this
research copy and continue the established OpenNR path, not spend another
large training run or delete/replace the surviving caches.
