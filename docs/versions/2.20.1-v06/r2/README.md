# OpenNR 2.20.1-v06-r2 — gaze crop geometry and sampling stability

[All three revisions](../README.md) · [r1](../r1/README.md) · [r2](../r2/README.md) · [r3](../r3/README.md)

r2 fixes the disagreement between crop placement, reconstructed image coordinates, and retained NR history that was exposed by the initial gaze-history fix. It targets image shaking and trembling without requiring an added gaze deadzone or smoothing filter.

**Headset feedback:** the tester reported no image shaking or trembling and a substantial improvement, with possible slight residual flickering. This is the user-confirmed stability baseline for r3.

Revision: [fc649f6](https://github.com/liviutrn/OpenNR/commit/fc649f65666137047035c644fca010bfcaf05a6d).

## What was wrong

Original OpenNR regenerated/flickered while gaze moved, but did not exhibit the later trembling. Keeping temporal history through gaze movement removed much of that regeneration and exposed inconsistent image-coordinate placement.

The local SR and NR paths independently rounded input/render and output/display crop rectangles. With DLSS Performance at **0.5 × 0.5 input resolution**, an output crop origin could advance one display pixel while the input crop had not moved by an input pixel. Retained NR history then compensated movement that was absent from the reconstructed local SR image.

Reduced-model sampling could also change phase as a crop moved. The same stationary scene location could therefore receive a different sampled value in successive crops. Large deadzones hid these effects by reducing crop movement, but introduced visible lag.

CPU reproductions demonstrated both geometry mismatch and sampling-phase sensitivity. They do not prove that these were the only possible causes of every native DLSS artifact.

## Changes from r1

### Derive display placement from the actual input crop

Default-mode SR now uses one crop plan: its output rectangle is derived from the input pixels actually rendered.

At Performance's exact 2:1 output/input ratio, the color and guide alignment maps are identity. **This path adds no extra resampling pass.** Other ratios align color in the existing writeback shader and conditionally align depth/motion guides to the same display positions.

### Use the current and previous cropped camera geometry

Cropped SR camera transforms now describe the actual current and previous cropped frusta. Ordinary same-size gaze movement keeps history. Engine TAA jitter stays separate from camera geometry, and the existing native motion-vector flags and scale contracts remain.

Camera history advances only after successful stereo SR, so a failed or incomplete frame cannot become the next frame's reference.

### Correct legacy NR crop displacement

Legacy NR crop compensation removes an extra model-resolution factor. A given physical crop displacement must describe the same motion at 100%, 85%, and 70% NR resolution.

This host reprojection correction retains r1's native guide-unit conversion.

### Anchor reduced one-pass atlas sampling

For a configured moving crop on the strict one-pass atlas route, reduced-model sampling is anchored to a fixed full-image lattice.

Downsampling, depth/motion packing, history reprojection, and output resolve now share the same pitch and phase. Previous model dimensions, valid eye-local overlap, and the right eye's changing packed origin remain part of correspondence and rejection.

### Reproject the optional result stabilizer

When gaze cropping can move, the optional same-pixel result stabilizer uses motion reprojection instead of assuming the previous pixel describes the same scene point.

Zero stabilization still adds no continuous filter. The existing configurable ladder-transition bridge can still operate during crop/model handoffs.

## Systems preserved

- FPS controller decisions, pass counts, GPU budget, hold/cooldown/retry policy, and crop tiers remain unchanged.
- Neural fine tuning, sequential-pass tuning, shaping controls, and inner crop feather remain unchanged.
- Ordinary same-size gaze movement does not request native DLSS resource recreation or a global history reset.
- Real tracking loss, scene cuts, frame gaps, and incompatible resource contracts still invalidate temporal state.
- Crop-transition mask bounds and resource-envelope rules are retained.
- Faster-mode placement and full-eye/flat nominal model resizing retain their existing paths.
- Pre-SR was left outside this revision's scope.

No new deadzone, pixel quantization, or gaze smoothing is used to conceal the coordinate problem.

## Quality and regression evidence

The [independent r2 review](https://github.com/liviutrn/OpenNR/blob/6439e8287d8427ff64cecafc473b8476205b95e6/experiments/gaze-stability-2026-10-04/verification-r2/verification-r2.md) recorded source replay, controller/gaze/history tests, CPU image and camera oracles, six buffer-layout checks, six shader compilations, full Windows compilation, and a shipped-package audit. That review predates the positive headset feedback above.

| Check | Result |
|---|---|
| Old Performance crop geometry | 4,566 coordinate mismatches reproduced |
| 210 overlapping moving-crop image cases | Maximum interior difference below 7.08e-7 on a 0–1 signal |
| 2,000 cropped-camera reprojection cases | Maximum NDC error below 1.29e-7 |
| 3,240 stereo atlas correspondence cases | 1,620 invalid-history cases rejected; valid correspondence error below 1.14e-13 pixels |
| Package comparison against r1 | No removals; one added guide-alignment shader; DLL and three existing shaders changed |

These are CPU/source/package checks, not native-network image measurements. The image oracle excludes a four-pixel edge strip and does not establish identical edge detail or seamless crop boundaries.

## Performance and remaining limitations

At exact DLSS Performance 2:1, the alignment correction adds no resampling pass. Other SR ratios may use conditional guide alignment and need their own visual and timing checks. FPS policy is unchanged; these facts do not establish a measured zero-cost or universally regression-free runtime.

The tester's positive result supports shaking/trembling improvement in the tested configuration. Possible slight flickering remains an observation, not a confirmed resolved issue. Other headsets, SR ratios, tracking discontinuities, and all tuning combinations still need runtime acceptance.

r3 builds on this geometry/history baseline and addresses the **outside crop's brightness/color seam**, not remaining temporal flicker.
