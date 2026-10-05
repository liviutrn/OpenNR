# OpenNR 2.20.1-v06-r1 — atlas motion and direct gaze response

[All three revisions](../README.md) · [r1](../r1/README.md) · [r2](../r2/README.md) · [r3](../r3/README.md)

r1 corrects motion-vector units in the forced one-pass atlas route and makes zero gaze smoothing/deadzone settings behave as requested. It retains the earlier work that reduced gaze-triggered flickering and regeneration. **It did not resolve the image shaking and trembling reported at zero deadzones; r2 is the revision that addresses that problem.**

Revision: [b33f184](https://github.com/liviutrn/OpenNR/commit/b33f184e0a2b5c659351de625a40feb5381c8cda).

## Changes from v06

### Correct native atlas motion-vector scale

The strict atlas path passed native Feature18 motion with a model-to-guide extent conversion. The legacy path used model-to-color extent conversion. When SR color and guide resolutions differed, these conversions described different amounts of physical motion. This was especially relevant when moving the head with forced one-pass atlas enabled.

r1 brings the native atlas conversion into agreement with the legacy guide-unit contract. The shader's separate conversion into model-pixel coordinates remains separate. The correction applies across full/reduced guide sizes and 100%, 85%, and 70% NR model resolution.

### Preserve small motion during guide packing

For an unchanged crop and atlas layout, guide packing now preserves the raw motion vector exactly. Previously, recovering small motion by subtracting large absolute positions could introduce numerical cancellation.

When the layout is unchanged but the crop moves, compensation uses the crop-origin delta directly. Crop-size changes, model-size changes, and the right eye's packed atlas origin still participate in history correspondence. Invalid source vectors and out-of-overlap history retain their rejection behavior.

### Make zero gaze controls mean direct response

- Zero fixation smoothing passes gaze samples directly in both filter modes.
- Zero deadzone plus zero pixel quantization bypasses the old hidden micro-guard.
- New configurations start with zero fixation smoothing. Existing saved values remain selected.
- The adaptive gaze filter remains available as an optional setting.

These changes do not add an image blur or temporal-history pass. They also do not suppress resets required by real tracking loss or scene cuts.

## Retained systems

r1 retains the v06 FPS/frametime ladder, forced one-pass execution policy, crop envelopes, bounded transition masks, and residual handoff. The preceding crop-transition work had already removed the black borders reported during crop changes. Neural tuning, sequential-pass tuning, and the existing inner crop feather remain available.

## What testing established

CI checked native/legacy motion-scale parity across guide/model sizes, direct subpixel gaze response, raw-motion preservation, and invalid-vector handling. The Windows runtime compiled and packaged successfully.

Headset feedback subsequently established that **shaking/trembling still remained** and could be hidden only by adding deadzones, which then made the crop lag. That feedback drove the coordinate and sampling investigation in r2. The current line was reported to have resolved the earlier flickering/regeneration, but r1's CPU checks did not establish complete headset stability or GPU performance.

## Why r2 followed

Changing filtering could not make the image inside the crop stable while preserving immediate gaze response. r2 therefore corrects SR/NR placement and history correspondence, rather than adding more gaze smoothing. See [r2's changes](../r2/README.md).
