# OpenNR-VR guided-path repair result — 2026-09-04

Status: complete offline repair and 600-step comparison on the existing crop
dataset. No new full-resolution capture was started.

## Problem found

The first scale-aware smoke preview used only `--models guided`. Its preview
helper filled the missing `rgb_only` column with the teacher image, so that
column was not a model result. The guided model also received unbounded guide
values. Some native R16G16 motion readbacks contained non-finite values or
finite half-float outliers such as `65504`; applying the recorded MVecScaleX/Y
values directly could create features around 109 million while RGB remained in
the 0–1 range.

## Repair

The native raw guide files remain unchanged. The exploratory guided student now
uses `bounded_scaled_pixels_v1`:

1. remove non-finite motion values and raw values above `0.25`;
2. apply the recorded per-eye MVecScaleX/Y values;
3. clip the resulting displacement to ±128 pixels;
4. normalize the motion channels to roughly [-1, 1].

The preview helper now displays an explicit `RGB model not run` tile when an RGB
checkpoint is not present, rather than substituting the teacher.

## 600-step result

The run used the same sequence-held-out split, 128×128 crop target, batch size
32, learning rate 0.001, seed 42, and RTX 5070 Ti for both models.

| Test model | MAE | PSNR | Improvement vs identity | p95 pair MAE |
| --- | ---: | ---: | ---: | ---: |
| Identity RGB | 0.038100 | 25.075 | 0.00% | 0.071004 |
| Guided RGB + bounded depth/MV | 0.030418 | 26.837 | 20.16% | 0.056487 |
| RGB-only control | 0.029038 | 27.026 | 23.78% | 0.054799 |

The guided model is now stable and no longer produces the blue failure mode.
RGB-only remains slightly better on this dataset and model size, so it remains
the control and current preferred model.

## Artifacts

- `out/opennr_poc_guidedfix_600/metrics.json`
- `out/opennr_poc_guidedfix_600/qualitative_preview.png`
- `out/opennr_poc_guidedfix_600/model_guided_best.pt`
- `out/opennr_poc_guidedfix_600/model_rgb_best.pt`
- `out/opennr_poc_guidedfix_600/threeway_guided_labeled/`

These are offline crop/teacher-agreement results. They do not establish live
Feature 18 replacement, temporal behavior, stereo consistency, headset quality,
or real-time VR frame time.
