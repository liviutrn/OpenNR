# OpenNR-GEN target probe — 2026-09-10 (historical log)

> Superseded by [`OPENNR_GEN_FINAL_REPORT_20260910.md`](OPENNR_GEN_FINAL_REPORT_20260910.md).
> This log was written before the raw-input correction and before the later
> face probes. In particular, its “next probe” language is no longer current;
> teacher-conditioned outputs are not deployable student targets.

## Historical decision (superseded)

Both bounded SDXL + Canny ControlNet recipes are rejected as target recipes,
and the FLUX.1 Kontext public conversion is rejected after two isolated
one-eye loader probes. A stricter SDXL `strength=0.05` stereo pair was
coherent and structurally consistent, but both eyes were rejected as
retention-only because neither was visibly preferable to the DLSS5 teacher.
At the time of this historical snapshot, a fresh `strength=0.08` route was
prepared for the next bounded probe and had not yet run. It was later superseded
by the corrected raw-input probes recorded in the final report.
The initial smoke generated four eyes from two stereo pairs, and the
conservative follow-up regenerated the same four eyes after shortening the
prompt and lowering img2img strength. Neither was structure-preserving enough
for training:

- the face/interior pair changed the local scene tone and background and
  introduced strong blue/purple changes in the hair/shield area;
- the fire/stone pair changed stone texture and ground appearance and added
  conspicuous synthetic color/texture structure;
- the initial run's long positive prompt exceeded SDXL's 77-token CLIP limit,
  so its tail was truncated during inference;
- the lower-strength follow-up still changed visible materials and lighting:
  shield/hair appearance in `scene-000`, fire/stone/vegetation in the second
  eye, wall/stone texture and brazier/courtyard lighting in `scene-006-eye0`,
  and cobblestone/grass color in `scene-006-eye1`.

The rejected outputs are preserved under:

`C:\OpenNR_GEN_Static_20260910\rejected_strength_028_smoke`

The active static target root retains the corresponding raw and teacher images
and the four lower-strength smoke outputs. The earlier `.28` outputs remain
under the separate rejected-evidence directory. The lower review records four
`reject` decisions and 36 `pending` decisions because the remaining eyes were
intentionally not generated. They are not accepted targets and are not
eligible for student training.

## Probe configuration and evidence

The probe used:

- `stabilityai/stable-diffusion-xl-base-1.0`, revision
  `462165984030d82259a11f4367a4eed129e94a7b`;
- `diffusers/controlnet-canny-sdxl-1.0`, revision
  `eb115a19a10d14909256db740ed109532ab1483c`;
- 20 inference steps, img2img strength `0.28`, ControlNet scale `0.80`,
  guidance scale `5.0`, seeds `91010`–`91013`;
- DLSS5-NR teacher RGB as the image-edit input, with a derived Canny map;
- two eyes for `scene-000` and `scene-006`.

The advisory numeric summary is:

| Quantity | Mean over four smoke eyes |
| --- | ---: |
| raw -> DLSS5 teacher MAE | `0.05000348` |
| target -> DLSS5 teacher MAE | `0.05089271` |
| target -> teacher edge MAE | `0.04001913` |
| target -> raw edge MAE | `0.03565859` |
| target luma mean delta vs teacher | `+0.00146544` |
| target luma std delta vs teacher | `-0.00219053` |

These scores are advisory only. They do not establish realism, identity, or
material fidelity; the visual rejection above is the actual gate result.
The full machine-readable result is
`C:\OpenNR_GEN_Static_20260910\pilot_v1\target_scores_smoke.json` and the
three-way sheet is
`C:\OpenNR_GEN_Static_20260910\pilot_v1\threeway_smoke_gallery.png`.

## Conservative follow-up

The follow-up used the same pinned local weights and teacher inputs with the
shortened prompt and:

- 20 inference steps, img2img strength `0.16`, ControlNet scale `1.0`,
  guidance scale `3.5`, seed base `91110`;
- the same two stereo pairs (`scene-000` and `scene-006`), four eyes total;
- no test-split data and no student or runtime work.

Its advisory numeric summary is:

| Quantity | Mean over four follow-up eyes |
| --- | ---: |
| raw -> DLSS5 teacher MAE | `0.05000348` |
| target -> DLSS5 teacher MAE | `0.04395911` |
| target -> raw MAE | `0.06451303` |
| target -> teacher edge MAE | `0.03782811` |
| target -> raw edge MAE | `0.03299170` |
| target luma mean delta vs teacher | `-0.00119954` |
| target luma std delta vs teacher | `-0.00523584` |
| target clipped fraction | `0.00027307` |

The lower-strength target is numerically closer to the teacher on this tiny
probe, but visual review rejects all four eyes. The machine-readable results
are `C:\OpenNR_GEN_Static_20260910\pilot_v1\target_scores_lower_smoke.json`,
`target_audit_lower_smoke_reviewed.json`, and
`target_review_lower_smoke.json`; the reviewed three-way sheet is
`threeway_lower_smoke_reviewed_gallery.png`. The final audit has zero hash
mismatches, four rejected eyes, 36 ungenerated/pending eyes, and
`student_training_allowed: false`.

## Alternate FLUX.1 Kontext probe

The alternate route used a separate cloned manifest and did not modify the
SDXL route or its evidence. The official
[FLUX.1 Kontext-dev card](https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev)
was not loadable in the observed local environment because it is gated. The
probe therefore used the public research conversion
[AlekseyCalvin/Flux_Kontext_Dev_fp8_scaled_diffusers](https://huggingface.co/AlekseyCalvin/Flux_Kontext_Dev_fp8_scaled_diffusers),
pinned at revision `652a3172b715103503a27193c3fed5d9cb5bc29c`, whose card
declares the official FLUX.1-Kontext-dev lineage. This must not be described as
the official gated checkpoint.

The probe used:

- the local conversion at `C:\OpenNR\Models\flux_kontext_fp8_scaled_diffusers_20260910`;
- the DLSS5 teacher as the image context, retaining raw and teacher inputs;
- 12 inference steps, guidance scale `2.5`, seed `92110`, and a 512x512 output;
- only `scene-000-eye0`, with the other 39 eyes intentionally unrun;
- the isolated generator `tools/opennr_gen/generate_flux_kontext_targets.py`.

Pipeline load, denoising, PNG save, and hash recording all completed. Direct
inspection then rejected the output: it was a repeating cyan/black grid, not a
scene-preserving enhancement. The raw and teacher inputs remained coherent.
The advisory score for the single eye was:

| Quantity | FLUX eye |
| --- | ---: |
| raw -> DLSS5 teacher MAE | `0.03241087` |
| target -> DLSS5 teacher MAE | `0.16685283` |
| target -> raw MAE | `0.17391771` |
| target -> teacher edge MAE | `0.11760441` |
| target clipped fraction | `0.44944509` |

The machine-readable evidence is under
`C:\OpenNR_GEN_Static_20260910\flux_kontext_probe_v1`:

- `manifest.json` — route manifest SHA-256
  `6fae07153503f44222368ab8fb3cde15693897b203e1b20cedd9baf3d276e3e8`;
- `target_records.json` — one generated eye with conversion provenance and hash;
- `scores.json` — advisory numeric score above;
- `target_review.json` — one `reject`, 39 `pending` decisions;
- `target_audit_reviewed.json` — zero hash mismatches and
  `student_training_allowed: false`;
- `samples/scene-000-eye0/enhanced_target.png` — preserved invalid output.

Because the local run used a public FP8 conversion and the result was
structurally invalid, this is recorded as a conversion/runtime probe failure.

A fresh isolated Diffusers-main stack (`0.41.0.dev0` with Transformers
`5.17.0` and the matching Hub development package) was then used for a
four-step compatibility rerun in
`C:\OpenNR_GEN_Static_20260910\flux_kontext_mainstack_probe_v1`. It generated
only the same `scene-000-eye0` sample. The output again was a repeating
cyan/black grid. Its advisory score was:

| Quantity | Diffusers-main FLUX eye |
| --- | ---: |
| raw -> DLSS5 teacher MAE | `0.03241087` |
| target -> DLSS5 teacher MAE | `0.16721691` |
| target -> raw MAE | `0.17434399` |
| target -> teacher edge MAE | `0.11815435` |
| target clipped fraction | `0.44104640` |

The second audit records one `reject`, 39 missing/unrun eyes, zero hash
mismatches, and `student_training_allowed: false`. This compatibility rerun
rules out the earlier pipeline helper mismatch as the sole cause, but it does
not establish whether the public FP8 conversion itself or another low-level
compatibility issue is responsible. No full 12-step expansion or target
training was authorized by the evidence.

The downloaded FLUX license adds an independent restriction: §4(b) prohibits
using the model, derivatives, or outputs to train, fine-tune, or distill a
model competitive with FLUX. The FLUX outputs are consequently research-only
probe artifacts and are not eligible GEN student targets, regardless of the
visual rejection.

## SDXL strength 0.05 boundary probe

After the `.28` and `.16` probes failed visual review, a new isolated SDXL
route tested both eyes of `scene-000` with the same pinned base and Canny
ControlNet, 20 configured steps, img2img strength `0.05`, ControlNet scale
`1.0`, guidance scale `2.5`, and seed base `91210`. The scheduler used one
effective denoising step at that strength. Direct inspection found both images
coherent, with the same camera, objects, materials, lighting direction, and
stereo relationship as the teacher; there was no hallucinated geometry or grid
artifact.

That structural success was not enough for the target gate. The pair is a
near-retention result rather than a visibly preferable photorealism
enhancement, so both eyes are recorded as `reject` with
`teacher_preference: fail` and the other structural checks passing.

The route is
`C:\OpenNR_GEN_Static_20260910\sdxl_strength005_probe_v1`. Its advisory
two-eye mean is:

| Quantity | Mean over `scene-000` stereo pair |
| --- | ---: |
| raw -> DLSS5 teacher MAE | `0.05353691` |
| target -> DLSS5 teacher MAE | `0.01668496` |
| target -> raw MAE | `0.05595800` |
| target -> teacher edge MAE | `0.01832353` |
| target clipped fraction | `0.00006676` |

The target audit reports two generated/reviewed eyes, two rejected eyes, 38
missing/unrun eyes, zero hash mismatches, and `student_training_allowed:
false`. The numeric closeness is useful for retention checking only; it does
not establish photorealism or target preference.

## Historical SDXL strength 0.08 setup (superseded)

A fresh route was prepared from the immutable `pilot_v1` source at
`C:\OpenNR_GEN_Static_20260910\sdxl_strength008_probe_v1`. Its manifest
SHA-256 is
`6f36f6299c8925fb84f738913dadd3442762c978fcf59fa9befdde191d86ff3d`, with
parent manifest SHA-256
`60438f20d66eee83083a23b1a4506a2c828bcbab213181022a9541d53308aaaa`. It
contains 40 copied raw/teacher eyes and no generated targets. The intended
first probe is the `scene-000` stereo pair at strength `0.08`, 20 steps,
ControlNet scale `1.0`, guidance `2.5`, and seed base `91210`; inference is
held until the concurrent student GPU workload exits.

## Historical staged photorealistic SDXL candidate (superseded)

The base SDXL checkpoint passed the `.05` structural check but failed teacher
preference because it was effectively retention-only. A separate
[RunDiffusion/Juggernaut-XL-v9](https://huggingface.co/RunDiffusion/Juggernaut-XL-v9)
SDXL fine-tune was therefore staged at Hub revision
`cf419233522daa0b9ea36c3aff98fa2cab1fb0fb`. The model card labels it a
photorealistic SDXL checkpoint under CreativeML Open RAIL-M and states a
personal/creative-use boundary; this run is local research only, with no game
runtime or paid API use.

The isolated fp16 Diffusers tree is
`C:\OpenNR\Models\juggernaut_xl_v9_fp16_20260910` and totals 6.464 GiB. The
source/teacher route is
`C:\OpenNR_GEN_Static_20260910\juggernaut_v9_probe_v1`, manifest SHA-256
`44638e524f0a5a942caac09284a5fa0f10cff80ec0298fab03f7e815917e8775`, with
the original pilot manifest as parent. Only the `scene-000` stereo pair is
planned for the first probe. No target has been generated from this candidate
yet because the concurrent student GPU workload is still live.

## Historical next-probe note (superseded)

The prompt is now within the SDXL CLIP limit and the generator defaults are
the conservative follow-up, but that follow-up also failed the visual gate.
The separate FLUX probes failed their direct structural check. The `.05` pair
was coherent but failed teacher preference, so it is not a target route. At the
time of that historical snapshot, the `.08` route was the next bounded
experiment and had no generated targets yet. That statement is superseded by
the later raw-input and teacher-conditioned face probes.
All routes remain before GEN student training: the review files remain
unaccepted, and the explicit trainer dry-run was refused with `target review
status is not accepted`.

## Superseding addendum

The later run corrected the experiment's most important provenance issue. The
SDXL generator now accepts `--input-role raw_input|dlss5_teacher` and records
the selected input per sample.

The corrected raw-input routes are:

- `C:\OpenNR_GEN_Static_20260910\sdxl_raw_input_face_probe_v1` — one
  `scene-019-eye0` eye at strength `0.08`; conservative/near raw, with
  target-to-teacher MAE `0.05646643` versus raw-to-teacher `0.05065818`;
- `C:\OpenNR_GEN_Static_20260910\sdxl_raw_input_strength060_face_probe_v1`
  — one eye at the maximum tested strength `0.60`; psychedelic texture and
  facial distortion, with target-to-teacher MAE `0.07644924`.

The visually pleasing full-face route is
`C:\OpenNR_GEN_Static_20260910\sdxl_strength008_face_probe_v1`, but its
recorded `input_role` is `dlss5_teacher`. It is therefore an offline visual
control, not a deployable target. The interrupted full route generated 12 eyes
from the same teacher-conditioned graph before being stopped and is preserved
for provenance only.

See [`OPENNR_GEN_FINAL_REPORT_20260910.md`](OPENNR_GEN_FINAL_REPORT_20260910.md)
for the complete route ledger, face galleries, scores, gate state, and cleanup
disposition.
