# OpenNR-VR POC result — 2026-09-04

Status: complete exploratory spatial distillation run.

## Result

The compact student learned a measurable held-out mapping from captured
pre-NR RGB to captured Feature 18 teacher RGB. The RGB-only control performed
better than the same-size model given RGB, depth, and motion-vector inputs in
this run.

| Test model | MAE | PSNR | Improvement vs identity | p95 pair MAE |
| --- | ---: | ---: | ---: | ---: |
| Identity RGB | 0.038100 | 25.075 | 0.00% | 0.071003 |
| Guided RGB + depth + MV | 0.033939 | 26.040 | 10.92% | 0.061609 |
| RGB-only control | 0.029038 | 27.026 | 23.78% | 0.054799 |

The guided model therefore shows that the expanded input path is trainable and
beats the identity baseline, but these measurements do not show a benefit from
the native depth/MV channels over RGB alone. That is a result for this compact
spatial model, preprocessing, step budget, and captured sample—not a claim that
the guides are intrinsically unhelpful.

## Dataset and split

- 33 sequences and 919 complete frame records.
- 7,352 square crop pair references: both eyes and four crops for each frame.
- 2,256 train pairs from 12 sequences, 440 validation pairs from 3 earlier
  sequences, and 4,656 test pairs from the separate latest capture session.
- Capture route was Full Eye, 100% model resolution, single-pass Feature 18,
  with depth and motion-vector capture enabled.

The split is sequence-level, so neighboring frames, eyes, and crops do not
cross the train/test boundary. The two capture sessions can still share game
content. The captured motion-vector tensors are represented using their raw
R16G16_FLOAT data with the recorded MVecScaleX/Y values applied; this follows
the documented Feature 18 capture contract but is still an offline modeling
representation.

## Reproduction and artifacts

The runner and method are documented in [OPENNR_POC.md](OPENNR_POC.md). The
run used 128x128 model inputs, batch size 32, 600 optimizer steps per model,
learning rate 0.001, seed 42, PyTorch 2.7.1+cu128, and an RTX 5070 Ti.

Generated artifacts are under
`D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc`:

- `dataset_audit.json`, `split_manifest.json`, and `run_config.json`
- `metrics.json` and `training_history.json`
- `model_guided_best.pt`, `model_rgb_best.pt`, plus last-step checkpoints
- `qualitative_preview.png` and `guide_preview.png`
- `labeled_examples/labeled_examples_sheet_01_of_03.png` through
  `labeled_examples_sheet_03_of_03.png`, each with explicit A/B/C/D labels

## Acceptance boundary

This is evidence of a learnable per-frame teacher signal, not proof of
perceptual superiority, temporal stability, reset-transition behavior, stereo
consistency, live Feature 18 equivalence, headset delivery, or real-time VR
frame time. The next meaningful modeling step is contiguous temporal training
with explicit reset/order/drop handling, followed by live stereo and frame-time
validation.
