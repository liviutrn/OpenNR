# OpenNR 2.20.1-v01 — Technical README

> **Status:** successfully transformed, compiled, packaged, hashed, and uploaded by GitHub Actions. The code/build pipeline is validated; experimental VR behavior still requires in-headset testing, especially stereo-atlas performance/quality and the broader adaptive controller.

This README is the authoritative technical record for the custom **OpenNR 2.20.1-v01** line in `liviutrn/OpenNR`.

It records the exact baseline, transformation order, gaze-history rules, sequential Feature18 architecture, reduced Pass-2 implementation, stereo-atlas design, history isolation, safety behavior, UI/settings status, known limitations, build environment, artifact identity, and the invariants that later versions must preserve.

The earlier [`docs/2.20.1-v01-IMPLEMENTATION.md`](../../2.20.1-v01-IMPLEMENTATION.md) remains as the original pre-implementation contract. This document describes what the final built v01 actually contains.

---

## 1. Exact repository and baseline

Repository:

`https://github.com/liviutrn/OpenNR`

Official upstream:

`https://github.com/olekspa/OpenNR`

OpenNR version:

`2.20.1`

Exact upstream source commit:

`9b6340870f3910d81917f167245885b50216654f`

v01 branch:

`build/2.20.1-v01`

Pre-v01 base commit:

`5e5e672cfa729f2b0afcfc43fb11ccdc01bf61cd`

Final successfully built v01 code baseline:

`9b5e9ccffa931e3394044091be1a5c82e2486669`

That v01 baseline is 32 commits ahead of the pre-v01 base.

Later versions should start from this known-good v01 code baseline instead of reconstructing v01 manually from upstream.

---

## 2. Important architecture: v01 is built through deterministic transforms

The checked-in `runtime/open-shaders` tree is not by itself the complete v01 implementation.

CI starts from the clean 2.20.1 source and applies a deterministic PowerShell transformation chain before compilation.

The effective source is:

```text
clean OpenNR 2.20.1 source
    ↓
reconstruct v00 gaze-history fix
    ↓
apply v01 settings/runtime contracts
    ↓
apply gaze stabilization + gaze/adaptive/sequential route
    ↓
apply reduced sequential Pass-2 renderer
    ↓
apply independent Pass-2 composite
    ↓
apply stereo-atlas renderer
    ↓
apply atlas temporal/fallback safety
    ↓
apply v01 UI
    ↓
permit carrier-excluded public package
    ↓
CMake configure/package
```

Do not inspect only raw `Renderer.cpp`, `FoveatedRender.cpp`, `Runtime.h`, etc. and conclude v01 logic is absent. The workflow is the authority on the compiled source state.

---

## 3. v00 gaze-history fix preserved

v01 is built over the working v00 gaze-history compensation fix.

Base patch:

`patches/2.20.1-v00-gaze-history.patch`

Reconstruction script:

`scripts/v01/apply-v00-base.ps1`

Important behavior preserved:

- CropMotion history slots:
  - SR left/right: 0/1
  - NR left/right: 2/3
- ordinary crop-origin motion is compensated through motion vectors instead of forcing Feature18 recreation;
- history advances only after successful reconstruction;
- ordinary eye-tracked movement retains temporal history;
- frame discontinuities, invalid/changed scale, crop-extent changes, and sufficiently large jumps still invalidate history;
- large-jump protection remains approximately 25% of crop extent;
- SR and NR histories stay independent;
- NR crop history is committed only after successful stereo reconstruction.

This behavior was the basis of the working eye-tracked gaze-flicker fix and is a do-not-regress invariant.

---

## 4. Continuous gaze stabilization

Pre-v01 gaze behavior had two major problems:

1. smoothing effectively stopped once movement exceeded only a few pixels;
2. crop origin used a comparatively large UV-derived dead zone that could correspond to tens of pixels at VR resolutions.

v01 replaces this with a continuous response:

- tiny tracker noise is suppressed;
- normal movement remains smoothly tracked;
- larger intentional gaze movement receives a distance-dependent response boost;
- the large hard dead zone is replaced with a much smaller soft pixel-scale response;
- quantization remains without becoming a large snap threshold;
- normal gaze movement does not recreate Feature18.

Main transform:

`scripts/v01/apply-gaze-sequential.ps1`

Validated wrapper used by CI:

`scripts/v01/apply-gaze-sequential-fixed3.ps1`

Older `fixed` and `fixed2` wrappers are historical CI-repair files; the workflow's `fixed3` entry is authoritative.

---

## 5. Eye tracking and adaptive crop coexist

Before v01, adaptive crop treated eye tracking as a hard ownership conflict.

v01 changes ownership to:

- **gaze owns crop center/origin**;
- **adaptive performance control owns crop size only**.

Adaptive control therefore scales the dimensions around the live gaze center instead of replacing gaze geometry with its own static crop geometry.

Conceptual example:

```text
base gaze crop: 50% linear extent
adaptive factor: 100% → 90% → 80%
result:          50% → 45% → 40%
center:          always the current gaze point
```

Do not restore the old `eye tracking => adaptive crop disabled` behavior.

---

## 6. 2× sequential Feature18 now works on cropped/gaze routes

v01 enables sequential Feature18 while NR uses:

- fixed crop;
- adaptive crop;
- eye-tracked crop.

Before v01, cropped/foveated routes explicitly forced `multiPass = 0`.

v01 removes that restriction.

Pipeline:

```text
game image
    ↓
SR
    ↓
Feature18 Pass 1
    ↓
Feature18 Pass 2
    ↓
final composition
```

PRE-SR sequential NR is intentionally not part of v01.

---

## 7. Pass 2 is relative to the live Pass-1 crop

Supported relative linear sizes:

- 100%
- 90%
- 80%
- 70%
- 60%
- 50%

The percentage is relative to the **current live P1 crop**, not the full eye.

Example:

```text
P1 = 50% of eye
P2 = 70% of P1
P2 ≈ 35% full-eye linear extent
```

If adaptive P1 changes:

```text
P1: 60 → 55 → 50
P2 ratio: 70%
P2: 42 → 38.5 → 35
```

P2 therefore never keeps a stale absolute crop.

Both passes use the same stabilized gaze center.

---

## 8. Compact reduced Pass-2 resources

Main transform:

`scripts/v01/apply-sequential-renderer.ps1`

Validated wrapper:

`scripts/v01/apply-sequential-renderer-fixed2.ps1`

The renderer adds:

`TierResources::secondPassOutput`

For reduced P2 coverage, the resource is physically smaller.

This is a performance feature rather than merely a mask. For example, 50% linear P2 coverage is approximately 25% of the P1 pixel count.

`ExecuteCascade()` is transformed so that:

- P1 processes the complete live P1 region;
- P2 reads a centered subregion of the P1 result;
- depth and MV guides use corresponding centered offsets;
- reduced P2 writes into the compact `secondPassOutput`;
- the result is later composited over P1;
- each sequential stage keeps its own native Feature18 history.

Separate histories were intentionally retained instead of attempting unsafe shared sequential history.

---

## 9. Reduced P2 and 3× sequential

If P2 coverage is below 100%, v01 caps the active cascade at two passes.

This avoids feeding a third pass from incomplete P2 geometry.

Therefore:

- reduced P2 => maximum 2 active passes;
- 3× remains possible only where P2 is full coverage and legacy geometry remains valid.

Reduced-region Pass 3 requires its own deliberate future architecture.

---

## 10. Independent Pass-2 controls

Settings/runtime plumbing is added by:

`scripts/v01/apply-settings.ps1`

v01 introduces `SequentialPassSettings` / `SequentialPassTuning` fields for:

- coverage;
- model-resolution field;
- preset field;
- intensity;
- local tone;
- local structure;
- skin structure;
- style;
- AutoMask;
- UI correction;
- resolve mode;
- result shaping;
- stabilization;
- blend mode;
- mask mode;
- feather width;
- falloff curve;
- dither strength;
- sharpening enable/strength/placement.

### Definitely independently applied to native P2 Feature18 in v01

- intensity
- local tone
- local structure
- skin structure
- style
- AutoMask
- UI correction

### Important limitation

Independent P2 model resolution is **not complete** in v01.

The setting exists, but both sequential native evaluations currently remain on the same model-resolution tier. The renderer explicitly leaves independent P2 model resolution for a later per-pass resource/resolve stage.

Some P2 result-shaping, stabilization, and sharpening fields similarly exist as configuration plumbing without every field having a finished independent execution path.

Do not equate a serialized setting with completed renderer behavior.

---

## 11. Independent Pass-2 edge composite

Shader:

`runtime/open-shaders/features/Upscaling/Shaders/Upscaling/NeuralRendering/SequentialCompositeCS.hlsl`

Transform:

`scripts/v01/apply-pass2-composite.ps1`

Implemented blend modes:

- Hard Copy
- Feather
- Dither

Implemented masks:

- Rectangle
- Oval

Independent P2 edge controls include:

- blend mode;
- mask mode;
- feather width;
- falloff curve;
- dither strength.

The compact P2 result is blended over P1 without turning P2 back into a full-size evaluation.

---

## 12. Experimental stereo atlas

v01 adds an optional stereo-atlas mode.

Default:

`OFF`

Normal independent-eye stereo remains the baseline, A/B path, and fail-safe fallback.

Atlas layout:

```text
LEFT | GUARD | RIGHT
```

Normal stereo:

```text
LEFT  → Feature18
RIGHT → Feature18
```

Atlas:

```text
LEFT + guard + RIGHT → one Feature18 evaluation
```

The output is split back into the two real eye regions.

### Performance objective

Atlas targets Feature18's fixed per-invocation overhead.

It does **not** halve total neural cost because pixel-dependent work still covers approximately both eyes plus the guard.

For 2× sequential:

```text
normal: P1-L + P1-R + P2-L + P2-R = 4 native evaluations
atlas:  P1-atlas + P2-atlas             = 2 native evaluations
```

The actual frametime saving requires in-headset measurement.

---

## 13. Atlas guard

Default:

`50 px`

Configurable approximately:

`8–256 px`

The guard is not black/zero-filled.

The packing shaders replicate adjacent eye-edge pixels:

- left half of guard repeats the left-eye boundary;
- right half repeats the right-eye boundary.

The guard output is discarded after Feature18.

Color, depth, and motion vectors use corresponding atlas geometry, with guide guard sizes scaled to their own resolutions.

---

## 14. Atlas pack shaders

v01 adds:

- `StereoAtlasPackColorCS.hlsl`
- `StereoAtlasPackDepthCS.hlsl`
- `StereoAtlasPackMotionCS.hlsl`

All three must stay geometrically consistent.

Do not atlas only color while feeding per-eye depth or MV geometry.

---

## 15. Atlas Feature18 history isolation

Original native Feature18 slots:

```text
2 eyes × 9 tiers × 3 passes = 54 slots
```

v01 adds atlas-only slots:

```text
1 atlas × 9 tiers × 3 passes = 27 slots
```

Conceptually:

```text
normal stereo: 0–53
atlas:         54–80
```

Atlas and normal independent-eye histories must never share temporal state.

---

## 16. Atlas implementation and safety

Main transform:

`scripts/v01/apply-stereo-atlas.ps1`

Validated wrapper:

`scripts/v01/apply-stereo-atlas-fixed2.ps1`

Final safety layer:

`scripts/v01/apply-atlas-safety.ps1`

### Mode handoff safety

While atlas evaluates:

- normal per-eye reset flags remain armed;
- atlas uses its own reset state;
- stale normal-stereo flags do not reset atlas every frame;
- switching back to normal stereo resets the normal path rather than reviving stale history.

### GPU/native-handle safety

If atlas Feature18 evaluation fails after D3D12 submission, v01 waits for:

`interop.WaitForIdle()`

before resetting the failed atlas Feature18 slot.

This prevents immediate destruction of a possibly in-flight native handle.

---

## 17. Atlas fallback policy

Atlas is fail-closed.

On incompatible or unsafe conditions, v01 falls back to normal independent-eye stereo.

Examples include:

- asymmetric/incompatible eye geometry;
- unsupported pass count;
- invalid dimensions/bounds;
- resource incompatibility;
- atlas allocation/packing failure;
- native atlas Feature18 failure.

Normal stereo must remain available as the A/B and recovery route.

---

## 18. UI changes

UI transform:

`scripts/v01/apply-ui.ps1`

v01 exposes experimental controls for:

### Pass 2

- relative coverage;
- style;
- intensity;
- local tone;
- local structure;
- skin structure;
- AutoMask;
- UI correction;
- edge blend/mask;
- feather/falloff/dither.

### Stereo atlas

- enable/disable toggle;
- configurable guard width.

Stale UI text claiming sequential NR requires Full Eye or that eye tracking necessarily disables adaptive crop was removed/updated.

---

## 19. Adaptive controller status

v01 fixes important geometry/ownership problems but does **not** fully solve the broader FPS/frametime controller.

Historical problems included:

- oscillation;
- abrupt crop changes;
- seam/black-region artifacts;
- crop baselines unrelated to the user's actual gaze crop;
- large frametime jumps caused by P2;
- NR resolution not always following requested reductions.

v01 improves this by ensuring:

- gaze owns the center;
- adaptive control scales the live gaze crop;
- P2 is derived deterministically from live P1 geometry.

The settings contract adds:

`neuralRenderingAdaptiveSecondPassCostMs = 6.0f`

but the full adaptive decision logic does **not** yet use this as a completed P2 cost model.

A later version should explicitly budget estimated P2 cost before quality/crop upshifts and retain strong hysteresis/dwell to avoid oscillation.

---

## 20. Sharpening status

v01 adds P1/P2 sharpening configuration fields with intended before/after placement and strength up to approximately 5.

This is not yet a finished robust sharpening implementation.

Future work should explicitly implement and test:

- sharpening before NR;
- sharpening after NR;
- strength behavior;
- temporal stability/shimmer in VR.

---

## 21. Experiments deliberately excluded from v01

Do not accidentally reintroduce these without a new reason/test:

- PRE-SR sequential NR;
- motion-dependent P2 reduction;
- alternate-eye sequential NR;
- hidden Skyrim brightness/color preservation;
- >100% Feature18-resolution experiments.

Prior observations:

- PRE-SR reduced quality;
- motion-dependent P2 reduction flickered;
- alternate-eye sequential flickered/ghosted;
- hidden brightness correction was not desired;
- >100% NR resolution was less useful than sequential processing.

---

## 22. Known quality issues not solved by v01

### Dark-scene haze/grain

A gray haze/grain/mura-like appearance was observed in dark Skyrim scenes with Feature18 active. Testing indicated this came from Feature18 rather than the PSVR2 panel. v01 does not apply an arbitrary correction.

### Sequential temporal artifacts

2× sequential can produce very high perceived detail but can still show temporal lag, shimmer, warping, smearing, or ghosting depending on settings.

### Multipass brightness behavior

Earlier testing showed dimmer highlights unless tone values on both passes were sufficiently high. v01 exposes tuning rather than adding a hidden global brightness correction.

---

## 23. Final active transformation order

The successfully built workflow applies:

1. `scripts/v01/apply-v00-base.ps1`
2. `scripts/v01/apply-settings.ps1`
3. `scripts/v01/apply-gaze-sequential-fixed3.ps1`
4. `scripts/v01/apply-sequential-renderer-fixed2.ps1`
5. `scripts/v01/apply-pass2-composite.ps1`
6. `scripts/v01/apply-stereo-atlas-fixed2.ps1`
7. `scripts/v01/apply-atlas-safety.ps1`
8. `scripts/v01/apply-ui.ps1`
9. `scripts/v01/permit-carrier-excluded.ps1`
10. CMake configure/package

The workflow is authoritative if historical wrapper files differ.

---

## 24. Important files

Workflow:

`.github/workflows/build-v01.yml`

Original v01 design contract:

`docs/2.20.1-v01-IMPLEMENTATION.md`

Sequential/atlas shaders:

- `SequentialCompositeCS.hlsl`
- `StereoAtlasPackColorCS.hlsl`
- `StereoAtlasPackDepthCS.hlsl`
- `StereoAtlasPackMotionCS.hlsl`

Active scripts:

- `apply-v00-base.ps1`
- `apply-settings.ps1`
- `apply-gaze-sequential-fixed3.ps1`
- `apply-sequential-renderer-fixed2.ps1`
- `apply-pass2-composite.ps1`
- `apply-stereo-atlas-fixed2.ps1`
- `apply-atlas-safety.ps1`
- `apply-ui.ps1`
- `permit-carrier-excluded.ps1`

Historical intermediate `fixed` wrappers remain in the repository for recovery/history but are not the authoritative active chain unless referenced by the workflow.

---

## 25. Build/CI lessons from v01

Several failures during development were transformation issues rather than C++ architecture problems.

Rules to preserve:

- normalize transformed files to LF;
- assert exact expected match counts;
- fail loudly on missing or ambiguous anchors;
- use exact replacements where practical;
- use unique context around repeated source blocks;
- never silently replace multiple ambiguous matches;
- avoid fragile nested PowerShell here-string quoting;
- run `git diff --check` after transforms;
- retain `.gitattributes` LF rules;
- commit coherent stages separately.

---

## 26. Build environment

GitHub runner:

`windows-2025`

MSVC setup:

`ilammy/msvc-dev-cmd@v1`

CMake:

approximately `4.2`

vcpkg:

- clone Microsoft's vcpkg;
- read `builtin-baseline` from `runtime/open-shaders/vcpkg.json`;
- checkout that exact baseline;
- bootstrap;
- expose it through `VCPKG_ROOT`.

Package commands:

```powershell
cmake --preset OpenNR-Package "-DDIST_PATH=$dist"
cmake --build --preset Package --parallel
```

---

## 27. NVIDIA carrier policy

Public CI intentionally excludes:

`nvngx_dlssnr.dll`

The artifact is therefore labeled `carrier-excluded`.

Use a validated licensed carrier from a legitimate existing OpenNR installation.

Do not commit/distribute NVIDIA's private carrier through this public repository.

---

## 28. Final successful v01 build

Code baseline:

`9b5e9ccffa931e3394044091be1a5c82e2486669`

Successful GitHub Actions run:

`https://github.com/liviutrn/OpenNR/actions/runs/36716356725`

Artifact:

`OpenNR-2.20.1-v01-carrier-excluded`

Artifact ID:

`11097571421`

Artifact SHA-256:

`2cf53b1f7d60b54ec69d8cab03ff22cb7a47a23265bc3924c8572bbfa11ffb27`

The successful CI run completed source verification, v00 reconstruction, all active v01 transforms, full configure/package compilation, hashing, and artifact upload.

This proves build/package consistency. It does not substitute for headset validation of experimental behavior.

---

## 29. Do-not-regress invariants

Later versions should preserve these unless intentionally replacing them with a verified superior design:

1. v00 gaze-history crop-motion compensation;
2. no Feature18 recreation for ordinary gaze movement;
3. continuous gaze stabilization rather than a large hard dead zone;
4. gaze owns crop center/origin;
5. adaptive logic owns size only;
6. P2 geometry derives from the live P1 crop every frame;
7. P1 and P2 native Feature18 histories remain isolated;
8. reduced P2 uses compact resources;
9. independent P2 edge composite remains available;
10. atlas remains optional and OFF by default;
11. atlas and normal stereo use isolated Feature18 histories;
12. normal stereo remains a reliable fallback/A-B path;
13. failed in-flight atlas handles are retired only after safe GPU synchronization;
14. public CI remains carrier-excluded;
15. the complete build stays reproducible from committed scripts/workflow.

---

## 30. Recommended v02 starting procedure

Create:

`build/2.20.1-v02`

from the known-good v01 baseline/code branch state.

Keep `scripts/v01` immutable for normal v02 development.

Create:

`scripts/v02/`

for new v02 changes.

Duplicate `.github/workflows/build-v01.yml` as a v02 workflow, update branch/artifact names, keep the full validated v01 transform chain first, and apply v02 transforms after it.

Before adding major v02 features, perform one zero-functional-change v02 CI build. This verifies that the new branch starts from the known-good v01 architecture.

Recommended v02 priorities:

1. in-headset atlas instrumentation and benchmarking;
2. wire `adaptiveSecondPassCostMs` into robust frametime decisions;
3. finish true independent P2 model-resolution support;
4. audit/complete independent P2 shaping and stabilization;
5. implement/test robust before/after NR sharpening;
6. continue frequent commits and CI checkpoints.

---

## 31. Testing expectations

For every future test revision:

- provide exact commit SHA;
- provide exact GitHub Actions run;
- provide artifact link/name;
- state what changed from the previous test build;
- distinguish compile/package validation from actual VR validation;
- commit frequently so no substantial work exists only in chat or an uncommitted transform.

This README should be updated whenever a later v01 maintenance change materially alters the architecture or the known-good baseline.