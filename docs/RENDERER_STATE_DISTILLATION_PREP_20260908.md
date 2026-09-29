# Renderer-conditioned temporal data and teacher/state distillation preparation

## September8 follow-up correction: ordinary bursts are not exact replay pairs

The later `RendererStatePairs` folder now contains19 clips; all pass structural and decoded content audits, but the formal pair audit finds0 eligible pairs. All19 sequence manifests say `history_reset_policy: request_on_sequence_start`, and all first frames reset both eyes. Repeating the ordinary burst key therefore does not itself implement the reset/warm replay protocol below. Even unchanged camera pose does not guarantee byte-identical current RGB/native guides/renderer inputs across live frames.

An exact pair experiment requires an instrumented same-input replay or another explicitly validated mechanism to preserve the current frame while changing teacher history. Do not ask for more ordinary bursts solely to fill the exact-pair count. The19 clips remain useful ordinary temporal training data and are preserved in separate strict/aligned caches. The current broader training work and corrected temporal initialization are documented in [the exact-parent follow-up](EXACT_PARENT_CONTINUATION_20260908.md); the protocol below remains a design gate for a dedicated state-pair loss, not evidence that the ordinary capture hotkey produces such pairs.

Prepared September 8, 2026. This document is a design and readiness gate. It
does not start a SkyrimVR capture, modify the production MGO profile, alter
native Feature 18 resources, rent Runpod, or train a new student.

## Current readiness finding

The existing renderer-conditioned caches are valid paired input/teacher/
renderer temporal datasets, but they are not yet teacher-state distillation
datasets.

Existing accepted cache inventory:

| Cache | Source | Rows | Sequence split | Pass mode | Renderer channels |
| --- | --- | ---: | --- | ---: | ---: |
| Fresh one-pass | `C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907` | 3,456 | 16/5/6 | 1× | 17 |
| Two-pass | `C:\OpenNR_Captures_2xDLSSNR_0.5.7_20260907` | 1,280 | 6/2/2 | 2× | 17 |

They preserve exact Feature 18-bound native depth and motion vectors, six
renderer-owned stages, both eyes, 64-frame sequences, reset metadata and
teacher outputs. They do not contain a teacher hidden-state tensor, a teacher
state hash, or a clean pair in which the current rendered frame and all native
guides/renderer inputs are identical while only the teacher's prior history
differs. The current student therefore cannot be honestly described as
distilling teacher state.

The read-only readiness audit confirms this boundary on the existing fresh
cache: [renderer state-pair audit](<E:/OpenNR_Training/renderer_state_pair_audit_existing_fresh_20260908_final/result.json>)
reports `ready=false` with zero state pairs. This is an expected preparation
result, not a failure of the existing renderer-temporal cache.

The next phase must first establish that teacher history has an observable
response under a clean current-frame match. Only then should a recurrent
student or state-behavior distillation arm be trained.

## Live capture profile armed

The live profile is now pointed at the new empty raw-capture root
`C:\OpenNR_Captures_RendererStateDistillation_0.5.7_20260908`; the old
`C:\OpenNR_Captures_2xDLSSNR_0.5.7_20260907` root was not reused. The active
settings file is
`E:\MGO-RC3-fresh\overwrite\SKSE\Plugins\CommunityShaders\SettingsUser.json`.
The change preserved the existing capture contract: 64-frame bursts, both eyes,
pre/post NR, raw teacher, native depth, native motion vectors, one 512x512 crop,
and renderer conditionings enabled. The configured burst key remains virtual-key
220 (the keyboard backslash key `\\`), not forward slash.

Before the edit, the settings file was backed up and hash-verified at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-output-root-20260908\SettingsUser.json`.
The original settings hash is
`ba23dda38ac274864bcfa17ade761f8a447dab78966694de127cee8017d84c52`.
The new root was created empty; no capture or game process was running during
the change. This profile change does not by itself make a state pair: pair
membership still has to be recorded during deterministic reset/warm replays.

## Capture status after first tranche

The first live tranche currently contains 38 sequence folders and 2,432 frame
records. The final post-capture strict crop audit accepts 37 sequences and
excludes one sequence, `seq-1788876151201-8`, because it contains a mid-clip
history reset and a 45-frame host transition gap. The excluded sequence is
preserved; it is not repaired or deleted. The audit report is
[renderer state capture validation](<E:/OpenNR_Training/renderer_state_capture_validate_final_20260908.json>).

This exceeds the 24 accepted ordinary-sequence minimum. It does not yet prove
that eight clean reset/warm state pairs exist: pair membership and exact
current-frame identity still require a separate manifest/audit. No training
has started from this tranche.

## Track A — new paired renderer-conditioned temporal data

The capture contract is in
[renderer_state_capture_contract.example.json](../config/renderer_state_capture_contract.example.json).

### Minimum bounded tranche

Capture a new tranche with at least:

- 24 accepted ordinary 1× 64-frame sequences;
- 8 explicit state-response pairs;
- at least 6 scene/motion strata;
- both eyes for every frame;
- separate one-pass and two-pass labels, never mixed within a sequence;
- sequence-level train/validation/test assignment, with both members of every
  state pair kept in the same split;
- a frozen test that is registered but never read for tuning.

The 24 ordinary clips are a minimum preparation target, not a claim that they
will reach `MAE <= 0.011`. They should cover the failure modes visible in the
current galleries: face/skin, strong highlights, deep shadow, hair/fur,
foliage/specular motion, indoor timber and outdoor stone/terrain. At least two
strata should contain meaningful camera/object motion and occlusion; static
clips alone are not useful temporal evidence.

### Required frame contract

Every committed sequence must satisfy the existing strict temporal validator:

- exactly 64 contiguous committed frames;
- frame IDs and sample indices contiguous;
- both eyes on every frame;
- first frame `history_reset == [true, true]`;
- every later frame `history_reset == [false, false]`;
- no mid-sequence reset, dropped frame, partial record or inferred frame;
- `route == feature18_stereo` and `model_resolution_percent == 100`;
- exact Feature 18-bound native depth and motion-vector resources;
- six renderer stages for both eyes;
- no optical-flow substitution;
- teacher settings, runtime fingerprint and source hashes recorded per
  sequence and kept constant within each pre-registered tranche.

The current accepted settings should remain the baseline unless a separate
factor is explicitly registered: teacher intensity 2, local structure 2,
local tone 2, skin structure −1, style 0, automatic mask enabled and UI
correction disabled. A different teacher setting is a new cohort, not a silent
replacement.

### State-response pair contract

Each state pair contains two rows from two valid histories ending at the same
current frame:

```text
reset member: [true, true] history at the anchor
warm member:  [false, false] history at the anchor

current input RGB:       byte-identical
native depth/motion:     byte-identical
renderer conditioning:  byte-identical
route/pass/settings:    identical
teacher output:          allowed to differ; measure the response
```

The pair is useful only if the current input and all inference-available
conditioning are identical. If they differ, a teacher-output difference is
confounded by scene or guide change and must not be called state distillation.
An internal teacher-state export is optional and must be hash-verified if the
native runtime ever exposes one; it is not required for the student design.

The minimum response threshold is only a signal gate (`0.0001` normalized
RGB MAE), not a quality target. Pairs below it remain useful as null evidence,
but cannot justify a state-conditioning architecture.

### Capture metadata to preserve

For every sequence, retain immutable hashes for:

- native teacher DLL and runtime/profile identity;
- live capture settings and teacher settings;
- route, resolution, pass count and capture-tool version;
- frame manifest and all raw payloads;
- six renderer-stage slot/texture diagnostics;
- native guide scales and crop mappings;
- GPU, driver and relevant runtime identifiers;
- pair-membership manifest and sequence split.

The raw capture root remains immutable. Preparation writes only to a new audit
root and a new aligned-cache root.

## Track B — separately validated teacher/state distillation design

The design must distinguish actual teacher hidden-state distillation from
behavioral state distillation. The current runtime does not expose a validated
teacher hidden tensor, so the first candidate is behavioral and uses only
inference-available history.

### Candidate stateful student

Keep the current frozen causal parent and add an offline temporal residual
adapter with:

- current RGB, frozen-parent output, native depth/motion, and the 17 renderer
  channels as inputs;
- a small recurrent state at reduced spatial resolution;
- the previous student output or a learned recurrent feature, never the
  teacher output at inference;
- a bounded RGB residual or luminance/chroma residual output;
- explicit reset handling from the capture contract;
- sequence burn-in before loss, followed by free-running student rollout.

The first model should be deliberately small enough to profile locally. Do not
increase the 38M backbone or rent VRAM before a small recurrent adapter proves
that state response is measurable and useful.

### Loss and evaluation separation

The candidate should be evaluated in two modes:

1. **Teacher-forced diagnostic:** previous teacher output/history may be used
   only to measure an upper bound and state observability. This mode is never a
   deployment claim.
2. **Free-running student rollout:** after reset and burn-in, the student uses
   only its own state/output plus current frame/guides/renderer inputs. This is
   the real distillation measure.

The objective should retain the existing RGB L1 and pooled-RGB terms, add a
bounded temporal consistency term, and report any state-pair contrastive or
reset-consistency term separately. No loss term may consume teacher pixels as
an inference input.

### Required pre-training ablations

Before a full run, implement and verify these matched controls:

| Arm | Renderer features | Recurrent state | State-pair loss | Purpose |
| --- | --- | --- | --- | --- |
| A | no | no | no | current plain temporal control |
| B | yes | no | no | renderer-input effect only |
| C | no | yes | no | state capacity without renderer context |
| D | yes | yes | no | combined inference-available conditioning |
| E | yes | yes | yes, only if clean pairs pass | state-behavior distillation |

Arm E is not allowed to replace A–D. A positive result must be attributable
to state behavior rather than simply adding renderer features or changing the
backbone. Start with a bounded 400-step pilot and full validation replay; only
continue to 1,200 if the pilot passes the pre-registered data/gradient/replay
gates.

## Ordered execution plan

### Phase 0 — preparation already performed

- Existing raw captures and aligned caches identified.
- Existing native-guide and renderer-stage contracts preserved.
- State-pair schema and audit tool added.
- No production/runtime or raw-capture mutation performed.

### Phase 1 — capture and audit

1. Capture the 24 ordinary clips and eight state-response pairs in a new raw
   root.
2. Run structural and strict temporal validation before decoding.
3. Run renderer-content, finite-value, variation and alignment audits.
4. Register pair membership and sequence-level splits.
5. Stop if fewer than the minimum accepted sequences or clean pairs remain.

### Phase 2 — pair readiness

1. Build a new immutable aligned cache outside the raw root.
2. Run `audit_renderer_state_pairs.py` on the cache and pair manifest.
3. Inspect current-frame identity and teacher-response distributions.
4. Do not train if the pair audit reports guide/renderer mismatch or only
   trivial teacher response.

### Phase 3 — stateful pilot

1. CPU-test reset behavior, shape/state reload, gradient reachability and
   free-running rollout.
2. Run matched A–D 400-step pilots locally.
3. Replay step zero before any optimizer update.
4. Evaluate all ordinary cohorts, two-pass stress separately, temporal error,
   branch/state utilization and fixed stereo galleries.
5. Add E only if Phase 2 produces clean state pairs with a measurable response.

### Phase 4 — promotion decision

A candidate remains offline-only unless it has:

- independent checkpoint replay;
- no frozen-test tuning;
- broad ordinary 1× improvement under the existing all-cohort rule;
- ordinary MAE at or below the project target;
- stable reset/warm/steady temporal behavior;
- convincing eye-0/eye-1 teacher color, face, highlight, shadow and detail
  match;
- separate runtime, stereo, frame-time and VR-budget acceptance.

## Runpod boundary

Do not spend the remaining Runpod credit for capture preparation. The first
stateful adapter should be memory-profiled locally. Cloud use becomes
justified only after the cache and pilot are validated and a measured transfer
preflight to the exact Pod/data center reaches the established high-throughput
gate (approximately 2.5 Gbit/s or better). The cheapest suitable GPU should
then run a bounded matched ablation, not blind width scaling.

## Readiness command

After the new cache and pair manifest exist, the read-only gate will be:

```powershell
py -3.12 tools/audit_renderer_state_pairs.py `
  --cache E:\OpenNR_TrainingInputs\RendererStateDistillation_<date> `
  --pairs E:\OpenNR_TrainingInputs\RendererStateDistillation_<date>\state_pairs.json `
  --output E:\OpenNR_Training\renderer_state_pair_audit_<date>
```

The current accepted one-pass and two-pass caches should not be relabeled as
state-distillation-ready; they remain valid renderer-conditioned temporal data
and are preserved as prior cohorts.

## Completed first capture tranche — 2026-09-08

The live renderer/state tranche is now audited. The raw root
`C:\OpenNR_Captures_RendererStateDistillation_0.5.7_20260908` contains 38
64-frame sequence folders. The strict crop temporal audit accepted 37 and
preserved one exclusion, `seq-1788876151201-8`, because it contains a mid-clip
history reset and a host-frame gap of 45. The final audit is at
`E:\OpenNR_Training\renderer_state_capture_validate_final_20260908.json`.

All 37 accepted sequences passed the decoded renderer-content and alignment
audit. The new immutable aligned cache is
`E:\OpenNR_TrainingInputs\RendererStateDistillation_20260908`, with 4,736 rows,
17 conditioning channels and a 23/6/8 train/validation/test sequence split.
The frozen test was not used for tuning. Its completion SHA-256 is
`c699bb6464001b1b4cd3798a0bd33680fb02a6f224769829dbeab40ce4ce7f3c`. The cache
reports `[0, 842672]` invalid native depth/motion guide pixels; the existing
mask-aware builder retained that information, so the motion validity mask must
remain part of any future pair identity decision.

The exact-signature discovery pass hashed 3,712 non-test rows and skipped 1,024
test rows, but found zero reset/warm candidates. The formal
`audit_renderer_state_pairs.py` result is `ready=false`, `ready_pair_count=0`,
`minimum_pairs=8`, `test_used=false`. Consequently no state-pair loss or
recurrent state arm is justified from this tranche.

As the safe non-pair branch, a registered 400-step renderer-conditioned pilot
was run at
`E:\OpenNR_Training\renderer_state_conditioning_pilot_400_20260908`. Both the
control and 17-channel conditioned arm selected step zero with validation MAE
`0.0201330753`; test MAE was `0.0250988306` for both. Their selected checkpoint
hashes are identical, and independent validation replay passed with a
`3.72e-11` evaluator difference. The pilot is a null result and was not
extended to 1,200 steps.

The detailed evidence is in
[RENDERER_STATE_CAPTURE_AND_PILOT_20260908.md](RENDERER_STATE_CAPTURE_AND_PILOT_20260908.md).
The next step is a deliberate paired replay with at least eight pair units
(normally 16 valid clips), followed by the formal pair audit. No Runpod spend,
runtime change or production/public-build change is warranted by the current
result. The live profile is now armed to write only to the empty
`C:\OpenNR_Captures_RendererStatePairs_0.5.7_20260908` root. The pre-edit
settings backup is preserved at
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-renderer-state-pairs-output-root-20260908`.

## Follow-up status — strict temporal continuation and MLX parity — 2026-09-08

The 37 accepted sequences were also materialized into the strict raw crop
cache
`D:\OpenNR_TrainingInputs\RendererStateDistillationStrict_20260908`.
The cache contains 4,736 eye rows, reports `strict_initial_reset=true` and
`temporal_training_allowed=true`, and retains the `[0, 842672]` depth/motion
invalid-guide counts. Its `complete.json` SHA-256 is
`34ff59c2852d9ceb3af5bc6a330ee85c23eaa8a293155ce0922ec865d9094ca1`.

One 400-step temporal-only continuation from the selected parent was evaluated
with the base/capacity branches frozen. Independent validation replay changed
MAE from parent `0.0201341000` to child `0.0205482053` and temporal-delta MAE
from `0.0075894919` to `0.0076733533`; the child was rejected and the frozen
test was not read. This closes the safe unpaired continuation on this tranche.

An isolated MLX-DLSS graph recovered from the active unknown-build DLL was
also tested on 24 eye rows from three sequences. The calibrated replay only
changed recovered-to-native MAE from `0.0234133062` to `0.0233862410` overall,
with regressions on the validation and frozen sequences. It is not accepted as
a teacher or relabeling source. The next executable phase remains the paired
replay in the empty root above: at least eight exact reset/warm pairs, normally
16 valid 64-frame clips, then the formal pair audit before any state-loss arm.
