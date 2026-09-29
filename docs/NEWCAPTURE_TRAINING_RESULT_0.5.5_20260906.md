# OpenNR v7 new-capture training result — 2026-09-06

The new-capture run completed successfully on the merged spatial cache. It is a
candidate checkpoint for the owned student runtime; it has not been installed as
the live teacher or promoted to a headset/runtime acceptance result.

## Training input

- Cache: `E:\OpenNR_MergedSpatialCache_0.5.5_20260906`
- Cache schema: 3
- Patches: 20,334
- Rows: 11,864
- Row identity: `44f8c20ebc75fef97d9ff692d323830c3b1a3ce16e15310cb2c50a538a45289d`
- Sources: the existing merged spatial cache plus the 27-sequence raw crop set
- Raw crop contribution: 1,728 complete frames / 3,456 eye rows, with zero
  invalid depth or motion rows
- Dynamic guides: `E:\OpenNR_DynamicGuides_Merged_0.5.5_20260906`
- Test rows were not used for tuning

The new crop sequences are structurally complete and have exact cadence, but they
all predate the reset-on-sequence-start fix. Their first reset flags are therefore
`[false, false]`; they were used as spatial/raw-crop supervision and continuity
data, not claimed as strict temporal training evidence.

## Run and selection

- Output: `E:\OpenNR_Training\context_merged_style_v7_newcapture_0.5.5_20260906`
- Architecture: `context_v4` (64 width, 3 blocks, scale 4)
- Initialization: v5 `best_feature.pt`
- Steps: 12,000
- Batch: 4
- Learning rate: `2e-6` start, decayed to `2e-7`
- Feature weight: `0.05`
- VGG appearance weight: `0.05`
- Face/tone loss: disabled for this controlled continuation run
- Best checkpoint: `best_feature.pt`, recorded at the final selection metric
- Best validation MAE: `0.02196831`
- Best validation PSNR: `29.7571 dB`
- Best validation feature distance: `0.07550092`

Portable export:

`E:\OpenNR_Training\context_merged_style_v7_newcapture_0.5.5_20260906\OpenNR_ContextStyle_v7_newcapture_best_feature.pt`

Export SHA-256:
`c91caa49277904ba291467bc62368f91db654680e3b8a73f9a3da1f7ce6aa526`

## Frozen test

The held-out test was evaluated after training selection using the same cache
identity. Result artifact:

`E:\OpenNR_Training\context_merged_style_v7_newcapture_0.5.5_20260906_frozen_test_clean\result.json`

Overall test result:

- MAE: `0.02501005`
- PSNR: `28.9126 dB`
- Identity baseline MAE: `0.03853958`
- Identity baseline PSNR: `25.3235 dB`
- Improvement over identity: `35.11%`

Source breakdown:

| Source | MAE | PSNR |
| --- | ---: | ---: |
| Existing merged spatial | 0.02351206 | 29.3822 dB |
| New raw crops | 0.03146623 | 27.3238 dB |

For a controlled diagnostic, the previous v5 checkpoint was evaluated on the new
cache while deliberately bypassing the old cache-identity guard. v7 changes the
overall new-cache test MAE from `0.02507156` to `0.02501005`; the raw-crop subset
changes from `0.03185589` to `0.03146623`, while the prior spatial subset is
effectively unchanged. This is a small, real improvement, not evidence of a large
quality jump.

## Visual and acceptance boundary

The held-out gallery is at:

`E:\OpenNR_Training\context_merged_style_v7_newcapture_0.5.5_20260906\test_gallery`

The gallery shows the input, v7 output, and Feature 18 teacher for both eyes. The
student tracks the teacher closely on the sampled foliage, geometry, and dark-scene
patches, but these images do not prove temporal stability, stereo comfort, live
Feature 18 routing, headset delivery, or VR frame-time budget.

The next high-value step is a live strict temporal capture using the newly installed
reset-on-sequence-start DLL. Press the configured `\\` burst key once from an idle
capture state, let the finite 64-frame burst drain, and validate that the first
record is `history_reset: [true, true]`. Only those newly verified clips should be
used for a temporal fine-tune or a runtime promotion decision.
