# Context-style spatial student phase — 2026-09-05

This phase adds a small whole-eye appearance branch to the measured
`context_v3` student and tests an optional low-frequency tone objective. It
uses only the audited merged Skyrim corpus and leaves the installed Open
Shaders runtime untouched.

## Implementation

`tools/student_v4.py` defines `StyleContextStudent` (`context_v4`). It inherits
the context-v3 local reconstruction and cross-attention path, then predicts a
smooth RGB residual from the complete 96x96 input/context grid. The final
style convolution is zero-initialized, and `initialize_v3()` requires that the
copied v3 state differ only by the new `style_grid.*` keys. The v4 smoke test
therefore verifies exact step-zero output identity, finite loss, and finite
gradients:

`tools/test_student_v4.py`

`tools/opennr_student.py` and `tools/train_long_student.py` load, train, and
export the new architecture. The branch is spatial only: it contains no
temporal state, history/reset handling, inferred optical flow, or replacement
for native Feature 18 resources.

The optional `--tone-weight` flag in `tools/train_long_student.py` adds a
16-pixel pooled RGB L1 term. Its default is zero, so prior objectives remain
reproducible.

## Data contract

- Cache: `E:\OpenNR_MergedSpatialCache_20260905`
- Row identity: `d1a699d0b6b1efad97f3b04d58775ddfe22fc9ffbe306f0caa5dc8816b9d8cca`
- Dynamic guides: `E:\OpenNR_DynamicGuides_Merged_20260905`
- Input-only training face audit: `E:\OpenNR_FaceAudit_Merged_20260905\result.json`
- Training/validation/test eye rows: 5,360 / 1,196 / 1,852
- Sources: 964 older full-resolution eyes and 4,396 new 0.5.3 raw-crop eyes

The v4 run used source-balanced dynamic native crops, two face-directed slots
per training eye, VGG appearance weight 0.05, face loss weight 0.25, batch 4,
learning rate 1e-5, and 8,000 steps. It initialized from the v3
source-balanced best-feature checkpoint at step 4,000.

Run directory:

`E:\OpenNR_Training\context_merged_style_v5_20260905`

The model has 2,005,139 parameters. The full checkpoints and portable
inference-only exports are preserved. No test row was used during training or
validation selection.

## Validation and frozen test

The validation evaluation uses all 1,460 fixed patches and 88 native eyes.
Lower is better for every error metric.

| Candidate | Step | Patch MAE | Native MAE | Changed-region MAE | LPIPS |
|---|---:|---:|---:|---:|---:|
| v3 source-balanced best-feature | 4,000 | 0.021649 | 0.021665 | 0.034206 | 0.063916 |
| v4 best-MAE | 1,500 | **0.021419** | **0.021432** | **0.033748** | 0.063063 |
| v4 best-feature | 5,500 | 0.021518 | 0.021576 | 0.034359 | **0.062695** |

The v4 best-feature checkpoint is the balanced appearance candidate. It is
slightly worse than v4 best-MAE on changed-region error, while its LPIPS and
frozen-test result are stronger. The visually inspected sheets are under
`E:\OpenNR_Training\context_merged_style_v5_20260905\validation_evaluation\comparison`.
They show a closer teacher-like face and lighting response, but the student
still misses some hair/skin microdetail and remains visibly different from the
teacher.

The frozen test was evaluated only after validation selection:

| Candidate | Combined MAE | Older full-resolution source | New 0.5.3 raw-crop source |
|---|---:|---:|---:|
| v3 source-balanced best-feature | 0.0235841 | 0.0242404 | 0.0226501 |
| v4 best-MAE, step 1,500 | 0.0235760 | 0.0242510 | 0.0226154 |
| **v4 best-feature, step 5,500** | **0.0234975** | **0.0241779** | **0.0225229** |

The v4 best-feature full checkpoint SHA-256 is
`0D0E968B6AD257F4FED7D5E0490FE5ABEBA42982D0B6ACF8AAEFE79E5803FB9F`.
The portable export is
`E:\OpenNR_Training\context_merged_style_v5_20260905\OpenNR_ContextStyle_v5_best_feature.pt`
with SHA-256
`BEAE3022A838051E216A22ACCB97CF4058FFC921B0800EB0176568CE153BB1E0`.
The v4 best-MAE portable export is retained alongside it with SHA-256
`0F7E4207676E9CEF22C18154A9F7D27780562B4D96F3ED2ECC857A9DA225F563`.

## Tone ablation

The tone run is preserved at
`E:\OpenNR_Training\context_merged_style_tone_v6_20260905`. It initialized from
v4 best-feature and used `--tone-weight 0.25`, learning rate 5e-6, and the same
data/objective otherwise. It was stopped after validation plateau, with its
best-feature checkpoint at step 1,000:

- validation feature distance: 0.077531;
- frozen test MAE: 0.0235197;
- older-source MAE: 0.0241573;
- new-source MAE: 0.0226124.

That is a useful ablation, but it does not beat the v4 best-feature combined
test result (0.0234975), so it is not promoted.

## Runtime build

The v4 best-feature export was converted through the existing fixed-shape
TensorRT path:

`E:\OpenNR_Training\context_merged_style_v5_20260905\trt_fp16_best_feature\student_fp16.engine`

- TensorRT 10.13.3.9, FP16 tactics with FP32 reduction preference, FP32 I/O;
  this is not an FP8/NVFP4 delivery.
- Engine SHA-256:
  `278A25AFC85282E6ABDB9896328DB921142D1A199E81FC195510D59CB93EEAB4`
- PyTorch parity: left mean `6.82e-05`, right mean `6.24e-05`; both maxima
  below `0.0019`; both checks passed.
- GPU-resident sequential stereo: 26.24 ms median in the TensorRT check.
- Actual D3D12 shared-resource replay: 27.56 ms wall median, 28.35 ms p95;
  all six input byte checks passed and packed output bytes matched exactly.
- Same-session teacher replay was 24.18 ms median wall; the student is slower
  in this offline bridge because of its larger context path. This excludes
  Skyrim rendering, compositor, headset, and temporal costs.

Visual replay evidence is in
`E:\OpenNR_Training\context_merged_style_v5_20260905\native_replay_best_feature\visual`.
The D3D12 path is an offline contract/timing check, not live-game acceptance.

## Decision and next gate

Keep v4 best-feature as the leading offline appearance candidate, keep v4
best-MAE and the v3 source-balanced checkpoint as fallbacks, and do not replace
the installed `CommunityShaders.dll`. The added style branch improves the
frozen spatial result but does not solve the teacher-equivalence or 90-Hz VR
budget problem; its bridge timing is approximately 8.6% slower than the prior
v3 control.

The next highest-value data step remains a short, clean contiguous native
temporal capture with an initial history reset, no frame gaps/backpressure, both
eyes, and exact Feature 18 depth/motion resources. The current spatial corpus
cannot train or validate carried history, reset handling, shimmer suppression,
or motion disocclusion.

