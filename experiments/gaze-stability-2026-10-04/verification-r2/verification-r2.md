# v06-r2 quality and regression review

Reviewed build commit: `fc649f65666137047035c644fca010bfcaf05a6d`.
Review date: 2026-10-05.

**No new confirmed r2 regression was found in this review.** This is a
source, CPU-oracle, build-log and shipped-package review. It does not certify
visible stability, image quality, frame time, or native temporal behavior in
Skyrim. The runtime artifact is unchanged; no replacement build is needed
for these verification additions.

## Checks and evidence

- Replayed the final r2 patch from the exact r1 fixture. All 14 resulting
  runtime files match the reviewed source, including the qualified COM types.
- Reran controller, gaze, overlap, transition, native-guide-scale parity,
  zero-lag gaze and successful-frame-history tests with g++ warnings as errors.
- Reran six CPU/HLSL buffer-layout checks and compiled the extracted C++ layouts.
- Rechecked the successful Windows build's exact source commit and logs:
  MSVC policy tests, six FXC `/WX` shader checks, universal runtime compilation,
  and both AIO manifest gates passed.
- Read/decompressed every shipped archive entry again, verified the x64 DLL,
  matched reviewed shader bytes, checked ZIP CRCs and SHA256 digests.
- Package delta remains 634 versus 633 entries: zero removals, one added
  AlignGuidesCS shader; only the runtime DLL and three existing shaders changed.

The source review follows SR input cropping through output compositing,
guide alignment, model input and inverse resolve, atlas guide packing,
native evaluation, residual stabilization and writeback. Ordinary gaze
movement still excludes crop origins from the resource hash. Crop camera
history advances only after successful stereo SR. Strict atlas history
still uses its compatible native feature, per-eye overlap rejection and
successful native geometry. Genuine discontinuities retain their reset paths.

The FPS controller, zero-filter gaze policy and configuration source are
unchanged. The tuning builder and native evaluation call arguments retain
their prior tuning values and cascade behavior. The new physical motion
scale is used by host reprojection; native guide-scale conversion is retained.
Pre-SR was excluded by the user and is not part of this acceptance claim.

## Additional synthetic image and scene checks

`image-audit.py` calls the actual r2 CropGeometry helpers through
`grid-export.cpp`. CPU equivalents of the area downsample and bilinear
resolve are compared against a stationary full-scene signal. These checks
use float helper parameters and double CPU arithmetic; they do not execute
the HLSL or simulate the native network or FP16 storage.

| Check | Cases | Result |
| --- | ---: | --- |
| Overlapping moving crops, both eye offsets, 100/85/70% model grids | 210 | Max interior difference 7.08e-7 on a 0–1 signal |
| Same signal with unanchored local grid, diagnostic comparison | 210 | Max difference 0.36954; demonstrates sampling-phase sensitivity |
| Constant signal through area downsampling, including edges | Same sweep | Zero error; no loss of area weight |
| Flat nominal grid extent | 15 | Max float extent error 4.67e-5 pixels |
| Cropped camera reprojection with perspective, rotation, translation, rebasing and asymmetric frusta | 2,000 | Max NDC error 1.29e-7 against direct previous-frame projection |
| Both atlas eyes across crop, resolution, guard and scene-motion changes | 3,240 | 1,620 outside-history cases rejected; valid world correspondence error below 1.14e-13 pixels |

The image comparison deliberately excludes a four-pixel crop-edge strip.
Anchoring the model lattice can place its outer samples beyond valid crop
data; the shader clamps those loads. The tests prove constant preservation
there, but do not establish identical edge detail or seam visibility.
The atlas oracle checks geometry and rejection bounds, not proprietary
network sampling across its guard band.

## Scope and remaining acceptance

At exact Performance 2:1, display crop placement and render crop placement
are identical in physical coordinates, and the new color/guide alignment
maps are identity. There is no extra resampling pass on that path. Other
ratios use a color resampling map and nearest guide alignment and need
separate visual acceptance.

The anchored reduced grid is enabled for a configured moving crop on the
strict one-pass atlas route. Reduced-resolution legacy routes keep their
nominal local grid. The new test's unanchored comparison is a demonstrated
sampling sensitivity, not evidence of a newly introduced legacy regression
or a measurement of native DLSS/NR image output.

Same-pixel optional stabilization is reprojected while gaze cropping is
configured. Turning stabilization off stays off during ordinary frames;
the existing controller handoff can still bridge resolution/crop transitions.
No gaze deadzone, smoothing or quantization is added by this revision.

Before calling image quality verified, run the in-game SE/VR devbench and VR
headset checks required by runtime/open-shaders/AGENTS.md. In this environment
neither is connected. The focused VR acceptance matrix is:

1. Performance SR, zero deadzones, zero fixation smoothing/quantization;
   NR off, legacy NR, then forced one-pass atlas. Test slow/fast head rotation,
   translation, independent gaze movement and eye-tracker noise.
2. Force 100/85/70 model stages, then enable the FPS controller and exercise
   crop growth/shrink and model transitions. Inspect crop edges and both eyes.
3. Exercise tracking loss/reacquisition, menus, scene cuts and renderer reset.
   Ordinary gaze should preserve history; real discontinuities may reset it.
4. Compare neural tuning and optional stabilization off/same-pixel/motion modes;
   check ghosting, residual lag, fine detail and unintended tonal changes.
5. If shaking remains, compare SR-only input and NR residual captures to
   locate it. Jittered guide versus reconstructed color timing, native
   accumulation and edge filtering are not resolved by these CPU tests.

## Reproduce additional checks

First reconstruct the reviewed r2 generated source using its build workflow.
From this directory, set `GENERATED_ROOT` to that checkout, then run:

```sh
g++ -std=c++20 -O2 -Wall -Wextra -Werror -pedantic \
  -I"$GENERATED_ROOT" -shared -fPIC grid-export.cpp -o grid-export.so
python image-audit.py
```

Python requires NumPy. `results.json` is the recorded result from this review.

Build: https://github.com/liviutrn/OpenNR/actions/runs/37241596759

Artifact: https://github.com/liviutrn/OpenNR/actions/runs/37241596759/artifacts/11317942540

Streamline matrix/jitter reference:
https://github.com/NVIDIA-RTX/Streamline/blob/main/include/sl_consts.h
and its ProgrammingGuide.md. The unjittered row-vector matrix composition
preserves the SDK's separate pixel-jitter input contract.
