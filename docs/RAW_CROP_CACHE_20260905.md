# Raw-only crop cache bridge — 2026-09-05

The 0.5.3 no-preview capture keeps exact raw color, depth, and motion-vector
crop tensors while omitting color PNG previews. The historical full-resolution
cache builder selected `png_path` for input and teacher colors, so it could not
consume this capture contract directly. The new
`tools/build_raw_crop_cache.py` path keeps the capture immutable and emits the
same cache files consumed by `tools/train_student.py` and
`tools/train_long_student.py`.

## Source and output

Source candidate manifest:

```text
D:\.CODEX_Projects\OpenNR-VR\out\latest_capture_training_candidate_manifest_20260905.json
```

Source capture root:

```text
C:\OpenNR_Captures_Temporal_Crops_0.5.3_NoPreview_20260905
```

Built cache:

```text
E:\OpenNR_RawCropCache_0.5.3_20260905
```

The cache contains 6,870 stereo eye rows from 3,435 frames and 111 selected
sequences. The frozen chronological sequence split is:

| split | sequences | eye rows |
| --- | ---: | ---: |
| train | 70 | 4,396 |
| validation | 18 | 1,108 |
| test | 23 | 1,366 |

The test split is recorded for final evaluation and must not be used for tuning.

## Conversion contract

- Raw `R8G8B8A8_UNORM` color is read with its recorded row pitch and alpha is
  stripped to RGB8.
- Raw `R32_FLOAT` depth and `R16G16_FLOAT` motion are read with their recorded
  row pitches.
- The 512×512 crop is already spatially paired, so one cache item is produced
  per committed frame and eye; no PNG round-trip is performed.
- Guides are downsampled to the existing five-channel 128×128 representation:
  depth, two motion channels, depth-valid mask, and motion-valid mask.
- Context is the existing eight-channel 96×96 representation: RGB plus the
  same five guide channels.
- Motion conversion uses the full source dimensions (2496×2688 color and
  1664×1792 guide), even though the raw guide file is a 512×512 crop. This
  preserves the existing color-pixel displacement convention instead of
  incorrectly scaling by 512/512.
- Nonfinite or native motion components outside ±0.25 are masked and replaced
  with zero before interpolation. The build counted 645,524 invalid motion
  pixels across all rows and zero invalid depth pixels; the resulting cache
  tensors contain no nonfinite values.

## Reproduce

Use the project training environment:

```powershell
E:\OpenNR-VR-Poc-Venv\Scripts\python.exe `
  tools\build_raw_crop_cache.py `
  --candidate-manifest out\latest_capture_training_candidate_manifest_20260905.json `
  --output E:\OpenNR_RawCropCache_0.5.3_20260905 `
  --workers 3
```

The builder refuses to reuse a nonempty output directory. It writes
`complete.json` only after all arrays are flushed. `rows.json`, `patches.json`,
`split.json`, and `provenance.json` preserve the source identity and split.

The metadata-only validation path is useful before allocating the cache:

```powershell
E:\OpenNR-VR-Poc-Venv\Scripts\python.exe `
  tools\build_raw_crop_cache.py `
  --candidate-manifest out\latest_capture_training_candidate_manifest_20260905.json `
  --output E:\OpenNR_RawCropCache_0.5.3_20260905 `
  --metadata-only
```

## Validation

The helper tests pass with:

```powershell
E:\OpenNR-VR-Poc-Venv\Scripts\python.exe tools\test_raw_crop_cache.py
```

The built arrays have these shapes and dtypes:

```text
rgb.npy     (6870, 2, 3, 512, 512)   uint8
guides.npy  (6870, 5, 128, 128)      float16
context.npy (6870, 8, 96, 96)       float16
```

`CachedPatches` compatibility was checked for all three splits. A two-item
batch returns RGB and teacher tensors of `(2,3,512,512)`, guide tensors of
`(2,5,128,128)`, and context tensors of `(2,8,96,96)` with finite values.

A one-batch CUDA forward/backward/optimizer smoke also passed on the RTX 5070
Ti with the guided `OpenNRStudent` path: finite loss `0.0483543`, finite clipped
gradient `1.16319`, output shape `(2,3,512,512)`, and peak allocation about
0.292 GiB.

The current `ContextStudent` v3 architecture also passed a one-item CUDA
forward/backward/optimizer smoke: finite L1 loss `0.0400153`, finite clipped
gradient `0.338971`, output shape `(1,3,512,512)`, and peak allocation about
0.149 GiB.

The cache remains conditional for recurrent temporal training because the
source sequences do not begin with `[true,true]` history resets. It is ready as
the frozen raw-backed input for the current spatial/feed-forward experiments;
the next temporal capture should supply a reset-qualified anchor.

The first full continuation completed from the selected context checkpoint in
`E:\OpenNR_Training\context_raw_crop_v1_20260905`. It ran 12,000 steps with
batch 4, BF16 autocast on the RTX 5070 Ti, VGG appearance weight `0.05`, and
SqueezeNet feature weight `0.05`. Validation-only selection reached MAE
`0.0198681` at step 10,000 and feature distance `0.0755031` at step 11,000.
The held-out test split was evaluated only after training: the step-10,000
best-MAE checkpoint reached MAE `0.0231885` and the step-11,000
best-feature checkpoint reached MAE `0.0231750`. These are crop-space
metrics; they do not establish native temporal or headset acceptance. See
`docs/RAW_CROP_TRAINING_RESULT_20260905.md` for hashes, the full test table,
and the next runtime/visual gates.

## Initialization safety

Existing long-training checkpoints carry the identity of the cache they were
trained on. `tools/train_long_student.py` continues to reject a mismatched
cache on resume. For an intentional new-data initialization, the new explicit
override is limited to `--initialize` and resets the optimizer:

```powershell
E:\OpenNR-VR-Poc-Venv\Scripts\python.exe `
  tools\train_long_student.py `
  --cache E:\OpenNR_RawCropCache_0.5.3_20260905 `
  --output E:\OpenNR_Training\context_raw_crop_20260905 `
  --initialize D:\.CODEX_Projects\OpenNR-VR\out\quality_phase_20260905\OpenNR_ContextFaceVGGFaceLoss_v4_best_mae.pt `
  --allow-new-cache
```

Do not use `--allow-new-cache` with `--resume`; resume identity checks remain
strict. The completed continuation and its frozen-test result are documented in
`docs/RAW_CROP_TRAINING_RESULT_20260905.md`.
