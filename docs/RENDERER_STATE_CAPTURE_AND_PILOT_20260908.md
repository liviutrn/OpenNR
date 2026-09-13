# Renderer-state capture, pair readiness, and conditioning pilot — 2026-09-08

## Decision

The new capture tranche is useful renderer-conditioned temporal data, but it is
not state-distillation-ready. The strict capture and renderer-content gates
accepted 37 of 38 sequence folders. Exact reset/warm discovery then found zero
eligible same-current-frame pairs, so a state-pair loss or recurrent state arm
would be confounded and is not justified. A bounded renderer-conditioned pilot
was nevertheless run without a pair loss; it selected the unchanged step-zero
fallback for both control and conditioned arms and produced no quality gain.

The ordinary 1x MAE target of `<= 0.011` remains unmet. No checkpoint is
promoted, no runtime or public build is changed, and no Runpod credit is spent.
The next safe evidence-producing step is a deliberate paired reset/warm replay:
at least eight pair units (normally 16 valid 64-frame clips, one reset member
and one warm member per pair), with exact current-frame identity and fixed
inference-available guides/renderer inputs. The existing 37 accepted ordinary
clips remain preserved and should not be relabeled as paired evidence.

## Capture and strict temporal result

Raw capture root:

`C:\OpenNR_Captures_RendererStateDistillation_0.5.7_20260908`

Final strict temporal audit:

`E:\OpenNR_Training\renderer_state_capture_validate_final_20260908.json`

The root contains 38 sequence folders, each with 64 frame records. The strict
crop temporal gate accepted 37 sequences and excluded one:

| Quantity | Result |
|---|---:|
| Sequence folders | 38 |
| Strict temporal-ready sequences | 37 |
| Excluded sequences | 1 |
| Accepted stereo eye rows | 4,736 |
| Capture pass | one-pass, renderer-conditioned, native guides |
| Crop | 512x512 |
| Frames per sequence | 64 |

The excluded sequence is `seq-1788876151201-8`. It has a mid-clip history
reset at line 18 and a host-frame transition gap of 45. It is retained for
diagnosis and is not silently repaired or included in the aligned cache.

## Renderer-content audit

The decoded renderer-content audit was run at:

`E:\OpenNR_Training\renderer_state_conditioning_audit_20260908`

It accepted the same 37 sequences and excluded the one strict-temporal failure.
The accepted sequences passed the finite-value, renderer-stage content and
alignment checks under the existing audit contract; no accepted sequence
reported a renderer-content error.

The aligned cache was built separately from the immutable raw root:

`E:\OpenNR_TrainingInputs\RendererStateDistillation_20260908`

Its immutable completion record is `complete.json`, SHA-256
`c699bb6464001b1b4cd3798a0bd33680fb02a6f224769829dbeab40ce4ce7f3c`. It has
4,736 rows, 17 renderer-conditioning channels, and a deterministic chronological
sequence split of 23 train / 6 validation / 8 frozen test sequences. The test
split was registered but not used for tuning.

The cache preserved the mask-aware native-guide result rather than silently
discarding invalid pixels. The completion record reports
`invalid_native_guide_pixels = [0, 842672]` for depth and motion respectively.
The motion-mask count is a data-quality caveat for future state-pair promotion:
the paired replay must keep exact native guide validity and must not treat
masked or zero-filled motion as a valid identity match without recording the
mask.

Completion array hashes are:

```text
rgb:          385f0f95dcdfe30c9f2aa50d52184b0ef1e16404b294c3cf72c89382d1ad5125
guides:       333c1576008a7a7029448dbbf01a3d7ccb95228037fcd38b39907a3deeca7ed60
context:      099523cd09a34471c22dbd0023c7d1306d1eca5cca064b30f60a707f8c3390b11
conditioning: 4fc7f73e106461ec323a072e2041e15e97c7d4a9d22b22b5c6588e85545fe8bf
```

## Reset/warm pair discovery and formal audit

The read-only discovery tool is
`tools/discover_renderer_state_pairs.py`. It hashes only inference-available
current RGB, native guides, context and renderer conditioning. It does not read
teacher targets from the frozen test split.

Discovery output:

`E:\OpenNR_Training\renderer_state_pair_discovery_20260908\discovery.json`

The discovery pass hashed 3,712 non-test reset/warm rows and skipped 1,024 test
rows. It found zero exact-signature candidate pairs. The formal acceptance audit
was run at:

`E:\OpenNR_Training\renderer_state_pair_audit_renderer_state_20260908`

and reported `ready=false`, `ready_pair_count=0`, `minimum_pairs=8`, with
`test_used=false`. Therefore:

- no teacher-response contrast is identifiable in this tranche;
- no recurrent/state-pair-loss arm may be trained from it;
- the renderer-conditioned cache remains usable only for ordinary temporal
  conditioning experiments, subject to the motion-mask caveat above.

## Controlled renderer-conditioned pilot

Because the cache passed the ordinary renderer-content gates, a small pilot was
run without state-pair loss to test whether the new renderer inputs could move a
frozen parent at all. The run was deliberately stopped at the registered
400-step pilot boundary rather than extended to 1,200 after the null result.

Output:

`E:\OpenNR_Training\renderer_state_conditioning_pilot_400_20260908`

Parent:

`E:\OpenNR_Training\aligned_retention_20260907_seed352\best_all_cohorts.pt`

Parent SHA-256:

`2024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60`

The pilot used seed 347, a frozen parent, and a 62,016-parameter feed-forward
renderer refiner. The control bypassed renderer features; the conditioned arm
received the 17 channels. The objective was `L1 + 0.12 adjacent temporal delta + 0.10 pooled tone L1`.
Selection was validation MAE with step zero eligible;
the frozen test was read only after both arm selections.

| Arm | Selected step | Validation MAE | Validation temporal delta | Test MAE |
|---|---:|---:|---:|---:|
| Parent | — | 0.0201330753 | 0.0075875498 | 0.0250988306 |
| Control, no renderer features | 0 | 0.0201330753 | 0.0075875498 | 0.0250988306 |
| Conditioned, 17 renderer features | 0 | 0.0201330753 | 0.0075875498 | 0.0250988306 |

At step 400, both arms were worse than their step-zero validation selection:
the control was `0.0204447432` and the conditioned arm was `0.0201809178`.
The small apparent step-400 conditioned advantage was not used because the
pre-registered selection rule chose step zero, where the arms are identical.
The control and conditioned selected checkpoint files have the same SHA-256:

`3c63a9444a9578fcea074abaf10e6811a30a33eb62424ae0fd01f1c4e47f28c8`

The independent replay is
`direct_validation_verification.json`. It passed: validation MAE differed
from the batch evaluator by only `3.72e-11`, parent replay max pixel difference
was `0`, and the missing-feature bypass max difference was `0`. This is an
offline causal validation check, not game/runtime timing or VR acceptance.

The selected checkpoint is therefore a clean null for this small refiner and
cache. No new visual sheet was needed to establish a visual win: the selected
conditioned checkpoint is byte-identical to the control and parent path at
step zero, so it cannot supply a new teacher color/detail match.

## Strict temporal continuation on the full tranche — 2026-09-08

The strict raw crop cache was built separately on D: from the candidate
manifest, without changing the immutable raw capture root:

`D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`

Its `complete.json` SHA-256 is
`34ff59c2852d9ceb3af5bc6a330ee85c23eaa8a293155ce0922ec865d9094ca1` and its
`rows.json` SHA-256 is
`73b0086f192277ed206bcc2165d0a8bb45779e320b5d61cc42b391d9e3fe479c`. The
cache contains 37 strict sequences, 2,368 frames and 4,736 stereo eye rows,
with the 23/6/8 train/validation/frozen-test sequence split. It reports
`strict_initial_reset=true`, `temporal_training_allowed=true`, zero invalid
depth values and the same `842672` invalid motion values recorded by the
renderer audit. The cache is 8.33 GiB; the raw capture remains separate.

The existing selected parent was evaluated independently on the new validation
split before training:

`E:\OpenNR_Training\aligned_retention_20260907_seed352\best_all_cohorts.pt`

Parent SHA-256 is
`2024593e3ebacb576c2848d0176bc0d8a16bbc35e1250f0dda519937778c5f60`. Its
validation MAE was `0.0201341000`, temporal-delta MAE `0.0075894919`,
first-frame MAE `0.0201701969` and steady-frame MAE `0.0201335271`.

A single bounded continuation was then run at
`D:\OpenNR_Training\renderer_state_temporal_continuation_freeze_temporal_400_20260908`.
It used seed 347, 400 updates, 8-frame windows, 2-frame burn-in, no spatial
mixing, and `--freeze-base-capacity`, so only the inherited temporal branch was
trainable. This is an ordinary temporal continuation, not a renderer-state
pair-loss experiment; the pair audit still found zero valid pairs.

The independently replayed selected checkpoint is
`best_mae.pt`, SHA-256
`0866a25fd5b9dc8725ce91d843760e5114f7c9b5afc2e12ae5409ffbe756173b`. On the
same validation split it scored:

| Metric | Parent | Temporal continuation | Change |
|---|---:|---:|---:|
| MAE | 0.0201341000 | 0.0205482053 | +0.0004141053 |
| Temporal-delta MAE | 0.0075894919 | 0.0076733533 | +0.0000838614 |
| First-frame MAE | 0.0201701969 | 0.0211512248 | +0.0009810279 |
| Steady-frame MAE | 0.0201335271 | 0.0205386336 | +0.0004051065 |

The child therefore regressed on validation and was not evaluated on the
frozen test or promoted. The training process's in-process step-zero record
was `0.0207990652`, while the independent parent replay above was `0.0201341000`;
the independent evaluator is the authoritative comparison, and the final
checkpoint replay is reproducible. This discrepancy is retained as a
measurement caveat rather than silently treating the in-process value as the
baseline.

This closes the safe unpaired temporal-continuation line for this tranche.
The result does not approach ordinary 1x MAE `<=0.011`, does not establish a
visual/color win, and does not justify more steps, Runpod spending, runtime
changes or native Feature 18 changes. The next evidence-backed step remains
the deliberate reset/warm paired replay described below.

## Next controlled capture

The next capture should be a paired replay, not another training continuation
on this same cache:

1. Preserve the current 37 accepted ordinary sequences and all audit/cache
   hashes.
2. Capture at least eight deliberate reset/warm pair units. Each unit should
   have a reset member beginning with `[true, true]` and a warm member beginning
   with `[false, false]`, with both histories converging to the same current
   frame.
3. In practical capture terms, use at least 16 valid 64-frame sequences if
   each pair member is a separate sequence. Keep each pair in one split and
   record the pair manifest at capture time.
4. Require byte-identical current RGB/native guides/renderer conditioning and
   identical route, pass, settings and runtime metadata. Teacher outputs may
   differ; that difference is the measured state response.
5. Reject any pair with a mid-clip reset, host gap, guide-validity mismatch or
   ambiguous crop mapping. Preserve rejected material with its reason.
6. Run the formal pair audit before training. Only if at least eight pairs pass
   and the teacher response is measurable should the state-loss arm be added to
   the matched no-state controls.

The next capture root is now prepared and empty:

`C:\OpenNR_Captures_RendererStatePairs_0.5.7_20260908`

Only the live `OpenNR Capture.output_directory` was changed. A pre-edit backup
of the settings is at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-pairs-output-root-20260908\SettingsUser.json`
with SHA-256
`a9a0cfc4e4152586df500f92fe03edc9fac93e28eb109c8c04b8b21d8abcd777`.
Capture remains enabled at 64 samples with the existing native-guide and
renderer-conditioning contract; the game and runtime are stopped. The prior
37-sequence root remains immutable and separate.

No Runpod rental is justified yet. The local pilot supplied no evidence that
more VRAM or blind continuation would fix the current generalization and visual
gap, and the exact-path transfer gate has not been needed.

## Public-source refresh — 2026-09-08

The current NVIDIA ADLR DLSS 5 description is consistent with the evidence
plan above: it describes inference conditioning on the current rendered frame,
engine motion vectors, carried temporal state and artistic-direction values,
with renderer-derived consistency supervision during training. It also
describes the model as causal, deterministic and trained for frame-to-frame
temporal stability. See the [NVIDIA ADLR DLSS 5 overview](https://research.nvidia.com/labs/adlr/DLSS5/).

The latest public GitHub material found in this refresh is useful for runtime
integration boundaries, not for copying a training recipe. The
[dlss5-video-player architecture](https://github.com/2600th/dlss5-video-player/blob/main/docs/ARCHITECTURE.md)
uses reconstructed approximate guides for video, explicitly because ordinary
video lacks engine depth and motion vectors; that is not a substitute for this
project's native Feature 18 guides. The
[DLSS5-Toolkit](https://github.com/daniel-madrid-07/DLSS5-Toolkit) describes an
OptiScaler-based interception path and warns that it installs DLLs next to game
executables; it does not expose a verified student-training loss, hidden-state
export or teacher dataset.

This refresh found no public, primary, reproducible DLSS 5 teacher/student
distillation recipe or hash-verifiable teacher-state interface that would
supersede the local paired replay. Unofficial ports, second-GPU experiments,
AMD/older-GPU adaptations and social-media visual claims remain research-only;
they do not establish Skyrim VR quality, temporal stability or a safe native
Feature 18 replacement. The new public evidence therefore strengthens the
priority of measuring carried-state response with exact native guides rather
than adding more unpaired renderer channels.
