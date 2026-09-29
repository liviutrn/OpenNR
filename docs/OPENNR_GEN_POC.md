# OpenNR-GEN proof of concept — current state

This is an isolated research path and does not alter the Feature18-bound
OpenNR runtime. The authoritative final record is
[`OPENNR_GEN_FINAL_REPORT_20260910.md`](OPENNR_GEN_FINAL_REPORT_20260910.md).

## Current decision

No deployable OpenNR-GEN image enhancer or student checkpoint was produced.
The visually pleasing full-face SDXL example was generated from the DLSS5
teacher, not from the vanilla input. It is therefore an offline look/control
result and is not eligible as a runtime target.

The corrected deployable graph is:

```text
vanilla input ──► offline enhancer ──► improved output
vanilla input ──► DLSS5 teacher ──► offline reference / metric only
```

The SDXL generator now makes that distinction explicit with:

```text
--input-role raw_input|dlss5_teacher
```

The direct raw-input face probe at strength `0.08` remained near the vanilla
image and had target-to-teacher MAE `0.05646643` versus raw-to-teacher MAE
`0.05065818`. The maximum tested raw-input strength `0.60` produced visible
psychedelic texture and facial distortion. No route passed the complete static
target gate, so student training remains blocked.

## Evidence boundary

The source is the read-only cache:

```text
C:\OpenNR_Cache_StrictAllCohortsVariedHighEffect_0.5.5_20260907
```

The selected static tranche is 20 sequence-disjoint stereo moments / 40 eyes,
with 28 train eyes, 12 validation eyes, completed coverage review, and
`source_test_used_for_tuning=false`. Raw/pre-NR input and original DLSS5 teacher
images remain paired in the immutable manifest.

All target routes are incomplete, rejected, unaccepted, teacher-conditioned, or
otherwise invalid for the deployable objective. Every target audit retains
`student_training_allowed=false`. Offline PNG generation, a clean hash audit,
or a pleasing single-eye gallery does not establish realism, geometry safety,
temporal quality, stereo quality, live runtime behavior, headset quality, or
VR-budget acceptance.

## Preserved artifacts

The route records and galleries remain under:

```text
C:\OpenNR_GEN_Static_20260910
```

The final report contains the full route ledger, exact face metrics, model
provenance, acceptance gates, cleanup actions, and the retained-artifact index.
The older detailed probe log remains at
[`OPENNR_GEN_TARGET_PROBE_20260910.md`](OPENNR_GEN_TARGET_PROBE_20260910.md),
but its earlier “next probe” language is historical and is superseded by the
final report.
