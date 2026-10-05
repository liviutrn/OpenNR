# OpenNR 2.20.1-v06-r3 — outside crop brightness and color transfer

[All three revisions](../README.md) · [r1](../r1/README.md) · [r2](../r2/README.md) · [r3](../r3/README.md)

r3 adds an optional way to make the DLSS5/NR crop less obvious when its brightness or color differs from the surrounding image. It transfers broad tonal changes into a feathered band **outside** the crop, with configurable static dither.

It builds on r2's user-confirmed shaking/trembling fix. The inner feather and pixels inside the crop remain unchanged. **The effect defaults to off.**

Revision: [4dfcd4d](https://github.com/liviutrn/OpenNR/commit/4dfcd4d2fdc547d3d8bdc9dff713016506e9299b).

## Changes from r2

### Estimate the crop's tonal change

A coarse current-frame 16 × 16 map compares paired samples from the original crop and the completed NR composite. Each map cell uses 8 × 8 paired samples to estimate broad brightness and channel-color changes.

The estimate uses bounded log2 gains, reduces confidence near black, and guards invalid/nonfinite values. Sampling can be moved farther toward the crop center to avoid measuring mostly the existing inner feather.

The calculation uses the existing LDR buffer representation; it does not assume a scene-linear buffer or copy NR detail into the periphery.

### Apply correction only outside the crop

A second compute shader applies the estimated brightness/color correction outside the actual rectangle or oval mask. For oval crops, this includes the exterior corner regions.

Correction ramps in beyond the untouched boundary, fades outward over a configurable width, and preserves original alpha. Pixels inside the mask are protected. A bounded application region and eye-local coordinates prevent correction from leaking into the other eye.

Sampling farther inward changes only the tone estimate; it does not modify the crop interior or its existing feather.

### Add static dither to the outward feather

Small screen-space dither breaks up the fade. It does not change with a frame index, so the effect introduces no animated-noise sequence. Width, falloff, dither strength, and boundary ramp can be tuned independently.

No new temporal accumulation or history is added.

## New live controls

The foveated Edge Blend controls contain **Outside NR tone transfer**. Changes are live and use the existing settings save/load path.

| Control | Default | Range | Effect |
|---|---:|---:|---|
| Enable | Off | On/off | Toggle the outside correction |
| Brightness | 0.65 | 0–1 | Strength of luminance transfer |
| Color | 0.30 | 0–1 | Strength of chromatic transfer |
| Fade width | 128 px | 8–512 px | Reach into the surrounding image |
| Falloff | 1.00 | 0.5–2 | Shape of the outward fade |
| Static dither | 0.15 | 0–1 | Subtle breakup of the feather |
| Boundary ramp | 8 px | 0.5–64 px | Fade correction in from the protected edge |
| Tone limit | 0.50 stops | 0–1 stops | Bound estimated/applied gain magnitude |
| Sampling inset | 8% | 0–25% | Sample farther toward crop center |

Widths are output-image pixels. If correction is too weak, a 15–25% sampling inset can measure beyond more of the inner feather. If a halo appears, reduce brightness/color or widen the outside fade. The correction extrapolates tone; scene-dependent differences can still leave a visible boundary.

## Performance measurement

**Measure outside tone GPU cost** uses the existing nonblocking GPU profiler. With runtime profiling enabled, the section open, and the effect active, it shows the latest and rolling-average sum of map and application timings for **both eyes**.

These are steady-state pass timings. First-use shader compilation and resource creation are excluded. The measurement checkbox is session-only; turn it off after tuning to remove capture-query overhead. The passes also appear as `NeuralRendering::OutsideTone*` profiler events.

The requested **0.1–0.2 ms** is a target, not a measured or guaranteed maximum. Wider application bands cover more pixels and can cost more.

The implementation adds no full-frame copy or CPU pixel readback. One small map is reused sequentially for the eyes. When disabled, it adds no new GPU allocation or dispatch; zero transfer strengths or a zero tone limit also skip the new dispatches.

## Integration and failure handling

- The effect runs after successful NR compositing.
- Full-eye and pre-SR routes skip it.
- Controls do not trigger native NR recreation, gaze filtering, or history resets.
- r2 crop placement, sampling phase, guide alignment, and temporal correspondence are retained.
- FPS controller policy, neural fine tuning, sequential-pass tuning, and the existing inner feather are retained.
- Shader/resource failure or an unsupported target skips the tone effect and reports status, without latching a native NR failure.
- Shader-cache clearing allows failed initialization to be retried.

Devbench adds `configureOutsideTone` for validated live changes and `outsideToneStatus` for settings and last application frame/eye count. Configuration changes persist through the existing save action.

## Verification and remaining limits

Source replay matched all 12 changed runtime files. Eighteen critical r2 gaze/history/grid/controller/compositor files remained byte-identical. Existing r2 policy, geometry, and image-oracle checks were rerun.

New checks covered 1.2 million outside-policy points and 18 synthetic image cases: interior/alpha preservation, identity transfer, eye isolation, rectangle/oval bounds, fade continuity, static-noise bounds, black/nonfinite protection, and gain limits. Eight CPU/HLSL buffer-layout checks, eight FXC shader checks, full Windows compilation, and package manifest checks passed.

The independent [r3 package audit](https://github.com/liviutrn/OpenNR/actions/runs/37335672597) compared both archives: r3 adds exactly two tone-transfer shaders, changes the DLL, removes no files, and leaves all existing shader/other payloads unchanged.

Actual VR seam quality, GPU cost, and coexistence across all runtime combinations remain unmeasured in this environment. No claim of a universal 0.2 ms ceiling or complete visual acceptance is made. Possible slight residual flickering reported with r2 is not addressed by this tonal correction.
