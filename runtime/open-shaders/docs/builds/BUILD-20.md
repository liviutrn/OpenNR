# Build 20 — gaze crop stability and per-pass NR tuning

This revision includes the Build 19 changes and additionally clears a rejected second-pass crop latch whenever its runtime resources are recreated or its resolution tier is evicted.

## Changes and reasons

- Uses one per-frame, per-eye crop plan for DLSS input/output rectangles and post-NR placement. This keeps the pixel rectangles consistent across stages when UV coordinates land between pixels.
- Scales motion vectors from the actual padded crop dimensions. Gaze edge padding therefore no longer leaves DLSS and crop-motion compensation using the unpadded scale.
- Makes the crop movement dead zone literal: `Off` means no movement threshold, and enabled thresholds consume only displacement beyond the configured pixel count. This removes the hidden minimum movement guard behind the old `Off` label.
- Latches a rejected second-pass subrect per eye, resolution tier, and crop configuration. A successful full-region retry prevents the same rejected subrect from being retried every frame. The latch clears when crop settings change, resources/runtime are recreated, a tier is evicted, or the user resets NR.
- Anchors dither to destination pixels, keeps it stable across frames, and tapers noise to zero at both ends of the feather. Alpha remains zero outside the mask.
- Adds independent Default, Balanced, Fabric Detail, Natural, Strong, or Custom tuning for passes 2 and 3. Each added pass has its own style, intensity, local tone, local structure, skin structure, automatic mask, and UI correction values. Pass 1 retains the existing controls. The stage-split route maps post-upscale evaluations to passes 2 and 3 rather than reusing pass 1 settings.

## Validation focus

Check steady fixation, small gaze movement, saccades, gaze reacquisition, crop padding, both eyes, and odd/non-integer crop ratios. Compare adaptive and static crop routes, and verify that a rejected second-pass crop continues using the full-region retry without repeated per-frame retries. Test pass-specific presets both with and without pre-upscale NR.

The common crop plan removes independent rectangle calculations, but it does not fully correct fractional sampling-phase changes as gaze moves. Astra advised deferring any guessed jitter-phase offset until it can be validated against runtime projection/jitter behavior or handled by coordinate-aware reconstruction.

