# White-box recovered-look OpenNR student pilot — 2026-09-11

## Decision

The recovered white-box model is useful as an **offline appearance-proxy
target generator**. A separate, small OpenNR student can learn a meaningful
approximation of that recovered look from existing Skyrim full-eye captures.

This does **not** make the recovered model a native NVIDIA teacher. The proxy
inherits the recovered model's own color/detail mismatch, so a student trained
to imitate it is a compact approximation of an approximation. No runtime,
Feature 18 path, native cache, active Skyrim profile, or protected checkpoint
was changed.

The pilot is promising enough to retain the route as a research branch. It is
not enough to promote either student or to spend storage on a new capture
session yet.

## What was run

The pilot used the existing immutable full-eye capture root:

```text
C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910
```

It selected frame IDs `1`, `8`, and `16` from all 14 retained sequences. Each
sequence stayed entirely in one split:

| Split | Sequences | Eye rows | Crop patches |
|---|---:|---:|---:|
| Train | 8 | 48 | 384 |
| Validation | 3 | 18 | 72 |
| Frozen test | 3 | 18 | 72 |
| Total | 14 | 84 | 528 |

Every selected frame passed the full-eye Feature 18 contract checks:

- complete stereo frame;
- `feature18_stereo`, one pass, model resolution 100%;
- full color `2496x2688` and native guide `1664x1792` resources;
- exact Feature 18-bound motion-vector contract;
- the first frame of each sequence begins with `[true, true]` reset;
- stable native teacher settings across the selected corpus.

The recovered model was run on the **complete eye image first**. Only after
that inference was its RGB output cropped to 512x512. The target settings were
the conservative recovered-look arm that performed best in the earlier matrix:

```text
standard/default profile
local tone = 1
local structure = 1
intensity = 1
detail = 1
colour = 1
automatic-mask approximation = off
frame_index = 0
```

`frame_index=0` is deliberate for this first student: it prevents a
deterministic-noise/frame-index variation from becoming a target the stateless
student cannot explain. This pilot is therefore a static appearance study,
not temporal training.

## Proxy sanity check before student training

The raw input, native NVIDIA teacher, and white-box proxy were compared in the
new cache before any student was trained:

| Split | Raw → native NVIDIA MAE | White-box proxy → native MAE | Proxy improvement over raw |
|---|---:|---:|---:|
| Train | 0.03044847 | 0.02446451 | 19.7% |
| Validation | 0.02596278 | 0.01801006 | 30.6% |
| Frozen test | 0.02242135 | 0.01511366 | 32.6% |

This is the important feasibility result. The recovered output is not native,
but its look is structured and learnable; it is not just random noise or an
unusable artifact. The proxy target file is finite, `uint8`,
`528x3x512x512`, and hash-recorded.

## Student arms

Both arms use the existing `OpenNRStudent` architecture family, width 32 and
two gated blocks, trained for 2,000 steps with the same seed, batch size,
learning-rate schedule, augmentation, and validation policy.

| Arm | Inputs | Parameters | Best validation step | Best validation proxy MAE |
|---|---|---:|---:|---:|
| RGB-only | input RGB | 354,569 | 750 | 0.01342824 |
| Guided | input RGB + native depth/motion guide tensor | 358,009 | 500 | 0.01441933 |

The guided arm did not win validation. On the frozen test split it was slightly
better, but the margin is small:

| Frozen test metric | RGB-only | Guided |
|---|---:|---:|
| Student → white-box proxy MAE | 0.01501642 | **0.01496283** |
| Student → native NVIDIA MAE | 0.02063931 | **0.02015429** |
| Raw input → native NVIDIA MAE | 0.02242134 | 0.02242134 |
| Improvement over raw versus native | 7.95% | **10.11%** |
| Improvement over raw versus proxy | 16.14% | **16.43%** |

The validation/test ranking is mixed, and the guided advantage on test is not
large enough to call it a robust win. The most defensible current result is:

> Both compact students are viable research approximators of the recovered
> look. Keep both checkpoints; do not choose the guided arm as the production
> direction from this small pilot alone.

The held-out sequence breakdown also shows why more sequence coverage would be
useful if we continue. Test sequence
`seq-1789071762719-5` is materially harder for both arms than the other two
test sequences, and the right eye is harder than the left in both models. That
is a useful failure signal, not a reason to remove the sequence.

## Visual output

The frozen-test sheets contain four unenhanced panels: raw input, student,
white-box proxy, and native NVIDIA. One representative RGB-only sheet is:

![RGB-only frozen-test comparison](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/evaluation_rgb_test_v2/previews/sample_0032_patch_00488.jpg)

The corresponding guided sheet is:

![Guided frozen-test comparison](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/evaluation_guided_test_v2/previews/sample_0032_patch_00488.jpg)

The preview set visibly includes dark foliage/ground and hair/detail regions.
It is a representative inspection set, not an automatic semantic benchmark
for face, armor, foliage, interior, or exterior categories. Those categories
should be manually tagged or sampled explicitly before any visual promotion.

## Files and reproducibility

The source manifest, cache, target provenance, checkpoints, frozen-test metrics,
and comparison sheets are under:

```text
D:\.CODEX_Projects\OpenNR-VR\out\whitebox_proxy_pilot_20260911
```

Important artifacts:

- [`source_manifest.jsonl`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/source_manifest.jsonl)
- [`proxy_complete.json`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/cache/proxy_complete.json)
- [`RGB-only frozen-test evaluation`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/evaluation_rgb_test_v2/evaluation.json)
- [`guided frozen-test evaluation`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/evaluation_guided_test_v2/evaluation.json)
- [`RGB-only checkpoint`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/student_rgb_32x2/best.pt)
- [`guided checkpoint`](D:/.CODEX_Projects/OpenNR-VR/out/whitebox_proxy_pilot_20260911/student_guided_32x2/best.pt)

The new reusable tooling is:

- [`prepare_whitebox_proxy_manifest.py`](D:/.CODEX_Projects/OpenNR-VR/tools/prepare_whitebox_proxy_manifest.py)
- [`generate_whitebox_proxy_targets.py`](D:/.CODEX_Projects/OpenNR-VR/tools/generate_whitebox_proxy_targets.py)
- [`train_whitebox_proxy_student.py`](D:/.CODEX_Projects/OpenNR-VR/tools/train_whitebox_proxy_student.py)
- [`evaluate_whitebox_proxy_student.py`](D:/.CODEX_Projects/OpenNR-VR/tools/evaluate_whitebox_proxy_student.py)

The scripts compile successfully, the target generation completed without
contract errors, and both CUDA training runs completed successfully.

## What this means for more data

No new Skyrim capture is needed for the next decision. We still have 16-frame
full-eye sequences, while this pilot used only three frames per sequence. If
we want to strengthen generalization, the next data expansion should consume
the remaining frames from this same existing capture root first. It would be a
derived proxy-target expansion, not a new raw-capture request.

New captures become justified only if the existing 16-frame data cannot cover a
desired visual category or if the student fails on a deliberately held-out
scene. More data cannot repair the fundamental recovered-versus-native gap;
it can only help the small student approximate the recovered look over more
Skyrim content.

## Next decision gate

The sensible next offline step is one of these two, keeping the same immutable
test sequences:

1. Expand the proxy cache from frames `1,8,16` to all 16 existing frames and
   repeat the same RGB/guided comparison; or
2. Keep the current cache fixed and test a smaller `width=24` model to measure
   the quality/parameter tradeoff.

The first option is the better choice if the goal is a useful Skyrim-wide
look approximation. The second is useful if the priority is measuring how
small the model can become. Neither option authorizes live deployment. Any
runtime candidate would still require separate full-frame integration,
stereo/temporal behavior, frame-time measurement, headset inspection, and VR
budget acceptance.

`promotion=false` for this entire pilot.
