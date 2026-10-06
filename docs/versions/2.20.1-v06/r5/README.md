# OpenNR 2.20.1-v06-r5 — targeted outside seam correction

Build and package audit pending. GPU timing and headset quality require an in-game comparison.

## Changes from r4

r5 adds a **Targeted seam curve** mode to the existing outside NR tone transfer.
It uses the completed NR output already available; it adds no neural
evaluation, second NR instance, or enlarged NR crop.

- Fit a local curved RGB correction as a function of original brightness.
  Separate the average tone shift, contrast response, and shadow/highlight
  curvature instead of applying one gain/offset response across every tone.
- Estimate from paired original and completed pre-feather NR samples close
  to the actual rectangle/oval boundary. Sample focus preferentially weights
  the nearest inward samples; no distant inset is required.
- Fit confidence suppresses poorly explained edits; low-variance patches
  fall back toward an additive tone correction. Flat black can still receive
  a shadow lift when near-black protection is zero.
- Interpolate/smooth coefficients in a common polynomial basis, avoiding
  brightness errors caused by mixing curves with different local origins.
  Smoothing affects only a 16 × 16 map, never the scene image.
- Hold the outside correction before its final fade. Contrast reach can fade
  the contrast/curvature contribution sooner than the average brightness/color
  contribution, reducing a pronounced outer ring.
- Optional near-black protection attenuates positive luminance transfer onto
  near-black pixels. It is outside-only and off by default; enabling it can
  reduce desired NR shadow lifting too.
- Compact the outside application into one dispatch that skips a protected
  interior rectangle. Oval crops skip a conservative inscribed rectangle;
  the exact existing mask test still protects every interior pixel.
- Preserve the r3/r4 estimator shaders byte-for-byte for live A/B comparison.
  The crop interior, inner feather, NR renderer, result shaping/stabilization,
  r2 gaze/motion/grid fixes and FPS-controller policy are unchanged.

## In-game controls

Open **Foveated / Edge Blend → Outside NR tone transfer**, then press
**Use targeted seam defaults**. This enables mode 2 and a starting preset:
brightness 1.0, color 0.65, width 160 px, no dither, boundary ramp 8 px,
sample width 32 px, smoothing 0.35, hold 0.35, contrast/curve 1.0,
contrast reach 0.5, sample focus 0.5, edge and near-black protection zero.
Old saved estimator selections remain selected until you choose the new mode.

| New control | Range | Purpose |
|---|---:|---|
| Tone estimator | 0 / 1 / 2 | r3 legacy / r4 affine / r5 targeted curve |
| Outside contrast transfer | 0–1 | Strength of brightness-dependent contrast change |
| Shadow / highlight curve | 0–1 | Nonlinear tonal change |
| Contrast reach | 0–1 | Fraction of outside width retained before contrast fades; 1 retains the full response |
| Hold before outside fade | 0–0.8 | Fraction of width held before the final fade |
| Outside near-black protection | 0–1 | Limit positive brightness transfer onto near-black pixels |
| Prefer near-boundary samples | 0–1 | Weight the nearest valid inward samples more strongly |

Existing brightness/color strengths, sample width, offset/tone limits, fade
width/falloff, boundary ramp, map smoothing, edge protection and static dither
remain live, configurable and persistent.

If the seam remains weakly corrected, raise color toward 1 and check the
offset/tone limits. If the outside looks like a ring, reduce hold or strengthen
the final falloff; compare contrast reach 0.3–0.7. Increase edge protection
only when correction appears to cross onto differently colored surfaces.
For gray lift in dark regions, try near-black protection; it does not repair
grain or haze inside the NR crop.

## Performance and integration

The new mode uses the same **two passes**, or **three with optional map
smoothing**, per eye as r4. The two reusable coefficient textures total
32 KiB of texel payload. There are no full-image copies, CPU readbacks,
temporal correction history, gaze deadzones, or native history resets.

For a 1000 × 1000 rectangular crop with a 128 px outside width, the compact
dispatch launches approximately 0.582 million content threads instead of
1.578 million. This is a work-count comparison, not a measured speedup.
Map estimation still takes at most 64 sample pairs per 256 cells per eye.

**Measure outside tone GPU cost** shows the summed steady-state cost for both
eyes. Enable runtime profiling first; turn capture off after tuning.
The requested maximum is **0.3–0.4 ms**, but this is not a verified cap.
Fade width, output resolution and GPU matter. First-use shader compilation
and allocation are excluded from the displayed pass timings.

The existing geometry and pre-feather output routing continue to cover moving
gaze, rectangle/oval masks, controller crop transitions, supported atlas and
compact multipass routes, and final neural tuning/result-shaping output.
Full-eye/off routes retain their existing bypass behavior. Unsupported inputs
skip the optional correction without changing the NR recovery state.

## Verification and limits

Exact r4 source contract and independent patch replay; retained r2 critical
file hashes; legacy estimator/renderer identity; twelve CPU/HLSL buffer
layouts; affine and curved tone fixtures; bounded finite corrections; compact
dispatch coverage; existing gaze/grid/controller/outside-mask suites.

Windows compilation, complete source contracts and package comparison are
required build gates. Native NR/headset runtime is unavailable here. No
universal invisible-seam claim: unseen peripheral objects can need different
neural lighting, and this method estimates their appearance from nearby crop
samples. It operates in the existing LDR buffer representation.

## Earlier version pages

[r4](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r4) ·
[r3](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r3) ·
[r2](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2)

OpenNR is a fork with upstream lineage from
[Open Shaders](https://github.com/alandtse/open-shaders) and
[Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).

