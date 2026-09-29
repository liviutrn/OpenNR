# Retention-regularized renderer focus — preregistered plan — 2026-09-10

## Purpose

The scratch-v2 comparison established that learned initialization is valuable,
but the renderer-focused gain trades against broad cohorts and temporal
stability. This bounded pair tests one substantive change: keep the same
renderer-pilot exposure while adding a training-only retention objective that
anchors the trainable parameters to the protected overall-best model and adds
explicit broad/temporal error terms.

This is an offline research experiment. It is not a runtime, headset, visual
promotion, or capture-validity claim. The protected checkpoint, the 18-sequence
cache, all source cohorts, and every earlier checkpoint remain immutable.

## Immutable starting point and corpus

- Protected checkpoint:
  `C:\OpenNR\Training\semantic_pixel_l1_pair_20260909\joint\best_all_cohorts.pt`
- Required protected SHA-256:
  `40C214A9C0BC214C6E1366872E6D9270BFE7C00D63797AEFB6B3896865C15756`
- Exact current `context_v7_capacity_temporal` graph.
- Frozen pretrained DINOv2 encoder; trainable parent and semantic/tone head.
- The six protected old cohorts only: `prior`, `high_effect`,
  `renderer_pilot`, `fresh_session`, `renderer_state`, `new_pairs`.
- Sequence-disjoint train/validation membership; frozen-test rows are never
  loaded.

## Matched arms

Both arms start from the protected checkpoint with fresh AdamW state, use one
serialized window schedule, and are evaluated on all six validation cohorts.

| Arm | Reconstruction objective | Retention term |
|---|---|---|
| Focus control | Per-frame RGB L1 only | None |
| Retention focus | RGB L1 + `0.25` pooled-16 RGB L1 + `0.12` adjacent residual-delta L1 | `0.25 ×` normalized trainable-parameter drift from protected weights |

The retention arm relaxes the parameter anchor to `0.25` of its normal weight
for `renderer_pilot` training windows, allowing the target cohort to move while
the other cohorts receive the full anchor. The anchor uses only the protected
model parameters and never uses teacher output as an inference-time input.

## Schedule and optimizer

- Seed: `910`.
- Window: `8` frames; burn-in: `2`; batch: `1`.
- Primary length: `2,400` updates; calibration: `400` updates.
- Evaluation every `400` updates; status every `50`.
- Stage 1, updates 1–800: `[0.35, 0.15, 0.15, 0.15, 0.15, 0.05]`.
- Stage 2, updates 801–1,600: `[0.25, 0.15, 0.25, 0.15, 0.15, 0.05]`.
- Stage 3, updates 1,601–2,400: `[0.35, 0.15, 0.15, 0.15, 0.15, 0.05]`.
- Head/parent learning rates: `1e-4` / `1e-5`.
- AdamW weight decay: `1e-4`; gradient clipping: `1.0`.
- Learning rate: 200-update linear warmup from `0.20×`, then cosine decay
  to `0.20×` nominal.

The control is necessary to distinguish the retention objective from ordinary
renderer-focused exposure. No step count, test split, data membership, or
checkpoint selection rule will be changed after launch.

## Acceptance gates

The ordinary target is renderer-pilot validation MAE `<= 0.007`. A research
candidate also needs a broad MAE and broad temporal gate: every protected
cohort must be no worse than the immutable reference. A narrow MAE improvement
with a broad regression is retained as diagnostic evidence only. Teacher
visual/color resemblance, stereo behavior, live Skyrim behavior, and VR-budget
acceptance are separate gates and must not be inferred from offline MAE.

The first decision point is the 400-update calibration. Continue to the
primary pair only if both arms are finite, reproduce the protected step-zero
reference within evaluator tolerance, and the retention loss has a measurable
but bounded anchor response. No blind 50,000-step extension is preauthorized.

## Storage and concurrency

Write only to new roots:

- `C:\OpenNR\Training\semantic_retention_renderer_pair_20260910_calibration`
- `C:\OpenNR\Training\semantic_retention_renderer_pair_20260910`

Abort before any destructive cleanup if C: falls below `100 GiB` free. Keep
all prior data and checkpoints. Runpod is unnecessary unless local VRAM fails;
the previous exact graph used under `10 GiB` on the local GPU.

## Implementation

Runner: `tools/train_semantic_retention_renderer_pair.py`.

The runner records source/cohort/checkpoint hashes, the serialized schedule,
loss coefficients, parameter-anchor statistics, step-wise validation, and
`test_used = false`. Final checkpoints require independent replay before any
promotion decision.
