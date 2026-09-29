# OpenNR-GEN final findings — 2026-09-10

## Executive conclusion

The OpenNR-GEN experiment did not produce a deployable vanilla-input enhancer.
The visually pleasing full-face example was real, but it was generated from the
DLSS5 teacher image. That makes it a useful offline look/control result, not a
valid result for the in-game model, which will only receive the vanilla/raw
input.

The corrected raw-input probes answer the deployment question directly:

- At SDXL img2img strength `0.08`, the output stayed conservative and close to
  the vanilla input. Its target-to-teacher MAE was `0.05646643`, worse than the
  vanilla-to-teacher baseline of `0.05065818`.
- At the maximum tested strength `0.60`, the face and background became
  psychedelic and the facial structure was visibly unstable. Target-to-teacher
  MAE rose to `0.07644924`.
- No route generated, reviewed, and accepted the complete 40-eye static
  tranche. Every target audit reports `student_training_allowed=false`.
- No GEN student, checkpoint, temporal result, runtime integration, headset
  result, or VR-budget result should be promoted from this experiment.

The experiment is now cleaned up as evidence rather than erased. Source pairs,
manifests, galleries, scores, rejected outputs, and route provenance remain
available. Two stale records that were left as `running` after manual stopping
are now explicitly marked `stopped` with the reason preserved.

## The graph that matters

The deployable graph is:

```text
vanilla input ──► offline enhancer ──► improved output
      │
      └──────────► DLSS5 teacher ──► offline reference / metric only
```

The teacher is allowed during offline dataset construction as a reference and
scoring target. It must not be fed into the enhancer when the result is being
evaluated as a deployable raw-input improvement.

The SDXL generator was corrected to expose and record:

```text
--input-role raw_input|dlss5_teacher
```

The corrected face routes record `input_role=raw_input` in
`target_records.json`. Earlier teacher-conditioned outputs are preserved and
explicitly classified as invalid for deployment; they are not silently
relabeled.

## Evidence scope and data quality

The static source tranche is derived from the read-only cache:

```text
C:\OpenNR_Cache_StrictAllCohortsVariedHighEffect_0.5.5_20260907
```

The selected manifest is:

```text
C:\OpenNR_GEN_Static_20260910\pilot_v1\manifest.json
```

Its recorded SHA-256 is:

```text
60438f20d66eee83083a23b1a4506a2c828bcbab213181022a9541d53308aaaa
```

The selection contains 20 sequence-disjoint stereo moments / 40 eye images:

- 28 train eyes from 14 stereo pairs;
- 12 validation eyes from 6 stereo pairs;
- `source_test_used_for_tuning=false`;
- both raw/pre-NR input and original DLSS5 teacher images retained;
- coverage review completed for face, hair, skin, armor, stone, wood, foliage,
  interior, exterior, deep shadows, and highlights.

The most useful full-face selection is `scene-019-eye0`. Its paired eye is
mostly foliage/background, so the face comparison is a one-eye visual probe,
not a stereo acceptance result.

## Full-face comparison

Each ordered gallery is:

```text
1 vanilla input (no added effects) → 2 SDXL output → 3 DLSS5 teacher
```

The three directly viewable galleries are:

1. Correct raw-input route at strength `0.08`:

   ```text
   C:\OpenNR_GEN_Static_20260910\sdxl_raw_input_face_probe_v1\full_face_ordered_gallery.png
   ```

2. Correct raw-input route at maximum tested strength `0.60`:

   ```text
   C:\OpenNR_GEN_Static_20260910\sdxl_raw_input_strength060_face_probe_v1\full_face_ordered_gallery.png
   ```

3. Earlier pleasing but teacher-conditioned route:

   ```text
   C:\OpenNR_GEN_Static_20260910\sdxl_strength008_face_probe_v1\full_face_ordered_gallery.png
   ```

The third gallery is the one that looked more realistic than the vanilla input.
That visual observation is valid. The provenance observation is equally
important: the SDXL enhancer saw the teacher, so the result cannot demonstrate
that SDXL can create the same improvement from vanilla input.

## Matched face-probe metrics

These are image-space proxies for the same `scene-019-eye0` pair. MAE means
mean absolute error in normalized RGB space; lower means closer in pixels, not
necessarily more realistic or preferable. The visual gate remains authoritative
for identity, geometry, materials, lighting, and stereo behavior.

| Probe | Enhancer input | Strength | Raw → teacher MAE | Target → teacher MAE | Target → raw MAE | Target → teacher edge MAE | Clipped fraction | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Correct raw-input face | `raw_input` | 0.08 | 0.05065818 | 0.05646643 | 0.01428915 | 0.02793699 | 0.00006485 | Reject; near raw, no teacher-like gain |
| Correct raw-input maximum | `raw_input` | 0.60 | 0.05065818 | 0.07644924 | 0.05085242 | 0.03215286 | 0.00793584 | Reject; psychedelic texture and facial distortion |
| Pleasing earlier face | `dlss5_teacher` | 0.08 | 0.05065818 | 0.02068669 | 0.05316539 | 0.02372356 | 0.00263341 | Offline-only; invalid for deployment |

The result is the decisive comparison: the teacher-conditioned route moves close
to the teacher because it was given the teacher, while the raw-input route does
not. Increasing strength does not recover the teacher-like appearance; it
destroys image fidelity instead.

## Route ledger

| Route | Enhancer input | Generated | State / decision | Key finding | Student target? |
| --- | --- | ---: | --- | --- | --- |
| Initial SDXL smoke (`0.28`) | teacher | 4 | Rejected | Visible material, lighting, and texture changes; the long prompt exceeded the SDXL CLIP limit and its tail was truncated. | No |
| `pilot_v1` SDXL (`0.16`) | teacher | 4 | Rejected | Lower strength remained structurally unsafe; all four reviewed eyes were rejected. | No |
| SDXL `strength005_probe_v1` | teacher | 2 | Rejected | Coherent and stereo-consistent, but retention-only and not visibly preferable to the teacher. | No |
| SDXL `strength008_probe_v2` | teacher | 2 | Rejected | Coherent pair, but no independent realism gain; edge/high-frequency proxies were lower than the teacher. | No |
| SDXL face probe | teacher | 1 | Offline-only | Pleasing full-face output; invalid because the enhancer input was the teacher. | No |
| SDXL interrupted full route | teacher | 12 | Stopped / invalid | Stopped after 12 eyes when the input-role mistake was corrected; preserved for provenance only. | No |
| SDXL stale clone | teacher | 0 | Stopped / superseded | Manifest paths pointed at `C:\OpenNR_GEN_Static_20260910\samples` instead of the route-local sample directory. | No |
| Correct SDXL raw-input face | raw | 1 | Rejected | Correct graph, but conservative/near raw and worse on teacher MAE than vanilla. | No |
| Correct SDXL raw-input maximum | raw | 1 | Rejected | Maximum tested strength produced psychedelic texture and facial distortion. | No |
| Juggernaut-XL-v9 `0.08` | teacher | 2 | Rejected | Shield surface changed, visible fire was suppressed, and stone/material response changed. | No |
| Juggernaut-XL-v9 `0.05` | teacher | 2 | Unaccepted | Preserved research probe; no complete accepted review and still teacher-conditioned. | No |
| FLUX Kontext conversion probe | teacher context | 1 | Rejected | Repeating cyan/black grid artifact; not a scene-preserving target. | No |
| FLUX Kontext main-stack probe | teacher context | 1 | Rejected | The same grid artifact persisted in a second compatibility stack. | No |
| Raw-input smoke validation | raw | 0 | Dry-run | Validated the raw-input branch without creating targets or consuming a full run. | No |

The cleanup audit confirms the incompleteness directly: `pilot_v1` has 4/40
generated eyes with 36 missing and 4 rejected; the SDXL `.05` and `.08 v2`
routes each have 2/40 generated eyes with 38 missing and 2 rejected; each
correct raw-input face route has 1/40 generated eyes with 39 missing; the
interrupted teacher-conditioned route has 12/40 with 28 missing; and each FLUX
probe has 1/40 with 39 missing. The audited routes have zero hash mismatches,
but incomplete or unreviewed is still a failed training gate.

### SDXL probe numbers

The scores below are advisory and support the visual decisions; they are not
realism metrics:

| Route | Raw → teacher MAE | Target → teacher MAE | Target → raw MAE | Target → teacher edge MAE | Interpretation |
| --- | ---: | ---: | ---: | ---: | --- |
| Initial SDXL `0.28` smoke | 0.05000348 | 0.05089271 | 0.06972082 | 0.04001913 | Numerically near teacher, visually unsafe |
| SDXL `0.16` pilot | 0.05000348 | 0.04395911 | 0.06451303 | 0.03782811 | Numerically closer, still visually rejected |
| SDXL `0.05` teacher-conditioned pair | 0.05353691 | 0.01668496 | 0.05595800 | 0.01832353 | Stable retention, no preference gain |
| SDXL `0.08` teacher-conditioned pair | 0.05353691 | 0.01670983 | 0.05599560 | 0.01832934 | Stable retention, no preference gain |
| Juggernaut-XL-v9 `0.08` pair | 0.05353691 | 0.02431896 | 0.05803504 | 0.02162234 | More change, but geometry/material/lighting rejection |

The small-probe numerical improvements for teacher-conditioned targets do not
override their invalid input provenance or their visual rejection. A lower MAE
does not prove a better image.

## Findings by route family

### Plain SDXL + Canny ControlNet

The pinned SDXL base and Canny ControlNet stack was reproducible offline. The
initial `0.28` and conservative `0.16` routes changed visible materials,
lighting, and texture. The `0.05` and `0.08` teacher-conditioned boundary pairs
were much more coherent, but they were retention-like and failed the explicit
teacher-preference requirement. The face result then showed why input provenance
must be checked before visual enthusiasm: the attractive output was conditioned
on the teacher.

The direct raw-input `0.08` test is the only result in this family that answers
the deployment question. It did not improve the vanilla-to-teacher relationship.
The raw-input `0.60` test rules out “just use more strength” as a solution.

The local model provenance is:

- SDXL base: `stabilityai/stable-diffusion-xl-base-1.0`, pinned revision
  `462165984030d82259a11f4367a4eed129e94a7b`;
- Canny ControlNet: `diffusers/controlnet-canny-sdxl-1.0`, pinned revision
  `eb115a19a10d14909256db740ed109532ab1483c`;
- local model directories under `C:\OpenNR\Models\`.

The upstream cards are [SDXL base](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0),
[Canny ControlNet](https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0),
and the [SDXL ControlNet pipeline documentation](https://huggingface.co/docs/diffusers/main/api/pipelines/controlnet_sdxl).

### Juggernaut-XL-v9

The photorealistic SDXL fine-tune was useful as a bounded alternative, but its
teacher-conditioned outputs changed scene semantics: shield markings became a
new-looking pattern, visible fire was suppressed, and stone/material response
shifted. The route is retained as research evidence, not a target source.

The local checkpoint is pinned to Hub revision
`cf419233522daa0b9ea36c3aff98fa2cab1fb0fb` from
[RunDiffusion/Juggernaut-XL-v9](https://huggingface.co/RunDiffusion/Juggernaut-XL-v9).

### FLUX.1 Kontext conversion

The official gated FLUX.1 Kontext-dev checkpoint was not loaded in the observed
environment. The public FP8 conversion was tested in two isolated loader
stacks. Both produced a repeating cyan/black grid rather than a valid scene.
The conversion and its outputs remain research-only; they are not student
targets. The official [FLUX.1 Kontext-dev card](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev)
and the tested [FP8 conversion card](https://huggingface.co/AlekseyCalvin/Flux_Kontext_Dev_fp8_scaled_diffusers)
are kept in the provenance record. Their licensing and model-lineage details
are an additional reason not to use this route for competitive distillation.

## Acceptance gates

| Gate | State | Evidence | What it means |
| --- | --- | --- | --- |
| Immutable source pairing | Passed | 40 eyes from 20 sequence-disjoint moments; manifest SHA recorded. | Raw and DLSS5 teacher images are paired for offline comparison. |
| Source-test protection | Passed | `source_test_used_for_tuning=false`; 28 train eyes / 12 validation eyes. | The frozen source test split was not used for tuning. |
| Correct deployable input graph | Corrected | Generator records `raw_input` or `dlss5_teacher`; raw face routes record `raw_input`. | The student-facing branch can now be tested honestly. |
| Accepted 40-eye target tranche | Failed | No route has 40 generated, hash-valid, reviewed, accepted eyes. | There is no valid target set for GEN student training. |
| Static student training | Blocked | All target audits report `target_gate=pending_or_failed` and `student_training_allowed=false`. | No student/checkpoint should be promoted. |
| Temporal / stereo / runtime / VR acceptance | Untested | No accepted static route exists; no live Skyrim or headset claim follows from PNG generation. | These are separate future gates. |
| Cleanup | Completed | Stale running metadata was closed as stopped; invalid routes remain classified and preserved. | The workspace no longer implies that abandoned routes are active. |

The existing parallel retention experiment and its replay evidence are separate
from this GEN report. A successful offline replay or a clean package audit does
not establish that a new GEN image enhancer is visually preferable, temporally
stable, deployable, or acceptable in a headset.

## Cleanup performed

The cleanup was intentionally narrow:

1. Added explicit `--input-role raw_input|dlss5_teacher` handling to
   `tools/opennr_gen/generate_sdxl_targets.py`.
2. Added per-sample input provenance fields (`input_role`, `input_path`, and
   `input_sha256`) to new SDXL records.
3. Added the ordered face-triptych renderer at
   `tools/opennr_gen/render_face_triptych.py`.
4. Closed the stale metadata state in:

   ```text
   C:\OpenNR_GEN_Static_20260910\sdxl_strength008_full_v1\target_records.json
   C:\OpenNR_GEN_Static_20260910\sdxl_strength008_probe_v1\target_records.json
   ```

   The first is `stopped` after 12 teacher-conditioned eyes. The second is
   `stopped` with zero outputs because its sample paths were wrong and it was
   superseded by `probe_v2`.
5. Regenerated target audits for the raw face probes, maximum-strength probe,
   teacher-conditioned face probe, interrupted route, stale clone, and
   Juggernaut `0.05` route. None passes the student gate.
6. Created this final report and a reviewed-data snapshot for the local report
   app at:

   ```text
   docs\OPENNR_GEN_FINAL_REPORT_20260910.md
   docs\OPENNR_GEN_FINAL_REPORT_DATA.json
   _opennr_gen_final_report_app2\dist\index.html
   ```

No source cache, model weights, accepted checkpoint, provenance tree, or
unrelated dirty worktree content was deleted.

## Artifact disposition

### Kept as useful evidence

- `C:\OpenNR_Cache_StrictAllCohortsVariedHighEffect_0.5.5_20260907` source
  cache;
- `C:\OpenNR_GEN_Static_20260910\pilot_v1` manifest, selection gallery,
  coverage review, scores, and lower-strength review;
- correct raw-input face galleries and their route-local manifests/scores;
- the teacher-conditioned face gallery, explicitly marked offline-only;
- rejected SDXL, Juggernaut, and FLUX outputs for provenance and comparison;
- isolated generator, scorer, auditor, tests, and gallery tools under
  `tools\opennr_gen`.

### Explicitly not eligible for training

- any teacher-conditioned enhancer output;
- any route with missing eyes, pending review, rejected eyes, or incomplete
  stereo pairs;
- both FLUX conversion routes, regardless of visual status;
- the raw-input face routes, because the `0.08` output did not improve the
  teacher relationship and the `0.60` output was visibly broken.

## Final decision and stopping condition

Stop this generation approach at the current boundary. Do not train a GEN
student from these targets and do not promote a checkpoint based on the
pleasing teacher-conditioned face.

If the work is resumed, the first acceptable continuation is a new
raw-input-only route against the same immutable manifest and audit contract. It
must establish a visually preferable result without hallucinated geometry,
identity, material, lighting, or stereo errors across the complete 40-eye
tranche. Only after that static gate passes should temporal, runtime, headset,
and VR-budget work begin.

The definitive distinction is simple:

```text
vanilla input → SDXL output → teacher reference     [tested; not good enough]
vanilla input → teacher reference                  [offline comparison only]
teacher input → SDXL output → teacher reference    [pleasing, but invalid]
```
