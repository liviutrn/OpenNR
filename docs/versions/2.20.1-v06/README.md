# OpenNR 2.20.1-v06-r6 — inside NR black protection and wider controls

**Windows build and package audit passed.** [Download r6](https://github.com/liviutrn/OpenNR/actions/runs/37420891871/artifacts/11393785953) · [Build](https://github.com/liviutrn/OpenNR/actions/runs/37420891871) · [Package audit](https://github.com/liviutrn/OpenNR/actions/runs/37420891871/artifacts/11393541443). GPU timing and headset quality require an in-game comparison.

## Changes from r5

- Move near-black protection **inside the NR region**. Retire the misplaced outside control. Existing r5 outside-black values are ignored; the new inside control defaults to zero and is enabled explicitly.
- Apply protection after NR result shaping, before crop compositing. The outside seam estimator samples this protected output. It also works with outside tone transfer disabled and ordinary result shaping disabled.
- Reduce positive NR edits on originally near-black pixels. Preserve darker edits and bright source pixels; use the original RGB peak so saturated highlights are not mistaken for black. This targets gray lift and associated brightening artifacts, not general denoising.
- Smooth the onset around zero NR brightening to avoid a hard color switch. No new temporal filtering, gaze smoothing, deadzone, native history reset or NR evaluation.
- Keep stabilization history in the unprotected raw NR domain. Changing protection strength/threshold/onset does not invalidate that history or native NR/SR history.
- Extend brightness, color, contrast, nonlinear response, dither, edge protection and sample focus up to **2.0**. Above 1, edge protection uses bounded stronger affinity rejection rather than extrapolating to negative confidence.
- Broaden fade width, sample width, tone/offset limits, falloff and boundary ramp. Existing values and the seam preset retain their previous meaning. Fractional smoothing and contrast reach stay at 0–1; hold reaches 0.95 while retaining a final fade.
- Add separate NR postprocess timing controls. Measurement selections are exclusive so one capture request does not overwrite another.

## Controls

**Neural Rendering → NR near-black protection**:

| Control | Range | Meaning |
|---|---:|---|
| Protection strength | 0–2 | 0 off; 1 normal; 2 protects more of the threshold range; attenuation never reverses NR edits |
| Dark threshold | 0.001–0.25 | Protection fades away as original RGB peak approaches this value; default 0.035 |
| Positive lift onset | 0.00001–0.05 | Smooth protection onset as NR brightening increases; default 0.001; higher values preserve more tiny edits |

Start with strength **1**, threshold **0.035**, onset **0.001**. Compare strength 0 and 1 in the same dark scene. Raise strength toward 2 or threshold gradually if gray lift remains. This also suppresses legitimate shadow lifting, and can reduce neural detail in the darkest pixels. It preserves the original game pixels rather than recovering unavailable NR detail.

**Foveated / Edge Blend → Outside NR tone transfer**:

| Control | r6 range |
|---|---:|
| Brightness, color, contrast, shadow/highlight curve, static dither | 0–2 |
| Outside edge protection, near-boundary sample preference | 0–2 |
| Fade width | 8–1024 px |
| Falloff | 0.25–4 |
| Boundary ramp | 0.5–128 px |
| Tone limit | 0–2 stops |
| Brightness offset limit | 0–0.5 |
| Boundary sample width | 4–256 px |
| Map smoothing, contrast reach | 0–1 |
| Hold before final fade | 0–0.95 |

For 2× brightness/color to be visible, the tone/offset limits may need raising too. Those limits still constrain the resulting correction. Wider fades cover more pixels and cost more; higher sample width still uses at most 64 sample pairs per map cell.

All controls persist and apply live. Developer command **configureNeuralBlackProtection** accepts strength, threshold and liftSoftness atomically; **neuralRenderingOutputStatus** reports them. The outside command rejects the retired blackProtection argument and directs callers to the inside command. Its other ranges match the UI and runtime validation.

## Integration and performance

The shared output stage covers full-eye, cropped stereo/atlas, reduced NR resolution after resolve, sequential final output and supported temporal residual reuse. Crop/mask geometry, controller policy, native guide transforms and the r2 gaze fix are unchanged. Native SR performance mode (0.5 × 0.5 render size) is not modified.

When result shaping/stabilization already runs, protection adds arithmetic to that same pass. Otherwise enabling it adds **one postprocess dispatch per eye**, with the existing reusable output texture. It adds no NR evaluation, spatial image blur, new history or readback. It is not guaranteed to be free.

**Measure NR postprocess GPU cost** reports the shared ResultShaping pass, including existing shaping/stabilization and the eyes that ran. Compare strength 0 with the chosen strength in the same scene. **Measure outside tone GPU cost** remains separate. Disable measurement after tuning.

The requested 0.3–0.4 ms budget is an in-game measurement target, not a verified cap. Large fade widths can exceed it. This build has no hardware GPU timing or headset acceptance evidence yet.

## Verification

Windows x64 build passed, with all twelve selected shaders compiled under warnings-as-errors. [Actual software D3D11 tests](https://github.com/liviutrn/OpenNR/actions/runs/37421657084) passed **32 inside-protection cases and 16 seam cases**, including the 2× overdrive extremes. These are shader execution checks, not hardware timing or native DLSS5 quality tests.

The archive audit passed all data/CRC checks. Only the runtime DLL and the three expected shaders changed; there are no added or removed payloads. Every other r5 payload is byte-identical. The NR carrier remains excluded. The 7z archive SHA-256 is `cb19dd939387c7b5ab57a2d4bc4164693fa4a5c3ddb635bd64b7c63eaf416369`.

Build gates include exact r5 patch replay, twelve CPU/HLSL layouts, retained gaze/grid/controller policies, 16 matching UI/load/runtime/command range contracts, 10,000 bounded protection cases, expanded-width compact-ring coverage, actual ResultShaping and seam shader execution on software D3D11, full Windows compilation and r5-to-r6 archive comparison.

Native DLSS5 appearance and in-headset stability need an in-game A/B. Source and software checks cannot establish universal visual correctness or a measured GPU budget.

[r5 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r5) · [r4 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r4) · [r2 branch](https://github.com/liviutrn/OpenNR/tree/build/2.20.1-v06-r2)

OpenNR is a fork with upstream lineage from [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders).

---

## Earlier r5 checkpoint

# OpenNR 2.20.1-v06-r5 — targeted outside seam correction

**Built and package-audited successfully.** [Download r5](https://github.com/liviutrn/OpenNR/actions/runs/37392639119/artifacts/11382089894) · [Build](https://github.com/liviutrn/OpenNR/actions/runs/37392639119) · [Package audit](https://github.com/liviutrn/OpenNR/actions/runs/37392639119/artifacts/11383085799). GPU timing and headset quality require an in-game comparison.

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

Windows x64 compilation and complete source contracts passed. All twelve selected shaders passed FXC with warnings treated as errors. Twelve actual map/smooth/apply cases passed on D3D11 WARP, covering both crop masks, identity, RGB offsets, mixed-channel contrast, nonlinear curves, black lift/protection, alpha and interior protection; this software test does not measure GPU milliseconds or native NR quality.

The [r4-to-r5 package audit](https://github.com/liviutrn/OpenNR/actions/runs/37392639119/artifacts/11383085799) checked all archive data and hashes. Only the runtime DLL changed; exactly three new seam shaders were added. No files were removed, every other r4 payload is byte-identical, and the packaged shader bytes match the reviewed source. The NR carrier remains excluded. The 7z archive SHA-256 is `c138a4ab1e1af7d75a5b500c6ca5c9feb5e3818552b44bc4ad1c70d1378f13d9`.

Native NR/headset runtime is unavailable here. No
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

## Earlier checkpoint documentation

# OpenNR 2.20.1-v06-r4 — boundary tone matching

**Built and package-audited:** [Download r4](https://github.com/liviutrn/OpenNR/actions/runs/37346929262/artifacts/11361958002) · [Build](https://github.com/liviutrn/OpenNR/actions/runs/37346929262) · [Package audit](https://github.com/liviutrn/OpenNR/actions/runs/37347213177).

Windows shader/DLL compilation and regression checks passed. The package adds one smoothing shader, changes the two existing tone shaders and DLL, removes nothing, and preserves every other r3 payload. Headset quality and GPU cost remain pending.

r4 replaces the inset-dependent outside-tone estimate with local **gain plus offset** matching. It measures the completed NR crop **before the outer crop feather**, so a weak feathered edge does not hide the tone change and a large inset does not borrow tone from a distant surface.

## Changes from r3

- Fit local RGB gain and offset from paired original/NR samples in a narrow strip along the actual rectangle or oval boundary.
- Carry additive shadow lifting, darkening, contrast compression, and broad color changes into the outside band. Black samples are no longer automatically assigned zero confidence.
- Sample the actual shaped/resolved/transition-handoff result used for writeback. Compact sequential passes and temporal-reuse routes retain their own completed output.
- Smooth only the small correction map. The existing scene image, inner feather, and pixels inside the crop are unchanged.
- Retain **Legacy inset gain** as an immediate A/B estimator.
- Add optional outside edge protection, **off by default**. It reduces transfer when an outside pixel differs strongly from the local original reference.
- Include coefficient smoothing in the GPU-cost readout.
- Preserve the r2 gaze geometry/history fix, FPS policy, neural tuning, and native resource contracts.

## Controls

Outside NR tone transfer remains **off by default**. Existing brightness, color, outside width/falloff, boundary ramp, static dither, and gain-limit controls remain live and saved.

| New control | Default | Range | Purpose |
|---|---:|---:|---|
| Tone estimator | Boundary gain + offset | Legacy / Boundary | Compare r3-style gain with local affine matching |
| Brightness offset limit | 0.08 | 0–0.25 | Cap positive/negative per-channel additive correction in the existing LDR representation |
| Boundary sample width | 32 px | 4–128 px | Local inward depth and tangential sampling width |
| Correction map smoothing | 0.50 | 0–1 | Spatial smoothing of coefficients; zero skips this pass |
| Outside edge protection | 0.00 | 0–1 | Optional attenuation across dissimilar outside colors |

The legacy sampling inset affects only the legacy estimator. The new mode samples near the boundary automatically; sample width controls how local the estimate is.

For visual comparison, select **Boundary gain + offset** and try brightness/color at **1.0** first, then reduce them if the transfer is too strong. Keep edge protection at zero initially. If an offset hits its limit, increase the offset limit cautiously; widening the fade spreads the correction farther.

This estimates broad local tone transformations. It cannot reproduce arbitrary neural detail, spatial relighting outside the available crop, or every nonlinear color operation exactly. Scene-dependent differences can still leave a seam or halo.

## Performance and integration

The default boundary mode runs map fitting, optional tiny-map smoothing, and outside application. There is **no new full-image copy, pixel readback, temporal history, or full-image guided filter**.

The coefficient textures occupy 24 KiB of texel payload in total and are reused sequentially for the eyes. Smoothing covers only 16×16 cells. Edge protection is optional; disabling it avoids its extra reference-map sample. Disabling tone transfer adds no new GPU dispatches or allocation. Full-eye and pre-SR routes still skip the effect.

**Measure outside tone GPU cost** reports the sum of active tone passes for both eyes using the existing nonblocking profiler. Initial allocation/shader compilation and query overhead are separate from the steady-state pass measurement. The requested **0.1–0.2 ms** remains a target until measured on the actual GPU.

Changing these controls does not recreate native NR, reset gaze history, or alter FPS-controller decisions. Failure skips the tone effect and retains NR rendering.

Devbench `configureOutsideTone` adds `mode` (0 legacy / 1 boundary), `offsetLimit`, `sampleWidth`, `smoothing`, and `edgeProtection`, with validation before assignment. `outsideToneStatus` returns the new fields. Existing save/load persists them.

## Verification scope

An independent r3-to-r4 replay checks the exact generated-source contract. CPU oracles cover identity, black shadow lifting, gain darkening, negative offsets, contrast compression, tint, invalid/extreme samples, valid rectangle/oval sample positions, outside-only writes, and alpha preservation.

The existing controller, zero-filter gaze, crop-grid, head-motion, and outside-mask suites are retained. CI checks nine CPU/HLSL buffer layouts, compiles the nine involved shaders, and builds/packages the full Windows runtime.

CPU/source checks do not execute native NR or prove headset quality. VR acceptance and GPU cost remain pending.

## Lineage

These are custom OpenNR 2.20.1 checkpoints. OpenNR inherits [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders) ([Nexus](https://www.nexusmods.com/skyrimspecialedition/mods/86492)).

---

## Earlier cumulative revision notes

# OpenNR 2.20.1-v06-r3 — optional outside NR tone transfer

## Latest three revisions: changes and modifications

These are successive custom checkpoints of OpenNR 2.20.1-v06. Each README describes its changes from the preceding revision.

| Revision | Main modifications | Current evidence |
|---|---|---|
| [v06-r1](r1/README.md) | Correct native atlas motion units; preserve small guide motion; make zero gaze filtering direct | Compiled and checked; shaking/trembling still reported |
| [v06-r2](r2/README.md) | Align SR/NR crop coordinates, cropped cameras, motion compensation, and reduced atlas sampling phase | Tester confirmed no shaking/trembling; possible slight flicker remained |
| [v06-r3](r3/README.md) | Optional outside-only brightness/color transfer, outward feather, static dither, and live GPU timing | Source/build/package checks passed; headset seam quality and GPU cost pending |

The FPS controller, neural fine tuning, earlier gaze-history work, and existing inner feather are retained across these revisions. r3 defaults to the r2 behavior until its new outside-tone option is enabled.

The detailed cumulative notes below preserve the implementation and verification record. Earlier “headset acceptance pending” statements describe the evidence available when those notes were written; the per-revision READMEs above record subsequent r2 user feedback.

OpenNR inherits [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders) ([Nexus](https://www.nexusmods.com/skyrimspecialedition/mods/86492)). This custom fork is not an official upstream release.

---

## r3 outside-only tone transfer

Built on r2, which the user confirmed removed image shaking/trembling. This
change retains r2 crop-grid/history alignment and the current inner feather.
The possible slight residual flicker reported with r2 is not addressed here.

Enable **Outside NR tone transfer** in the foveated Edge Blend controls. It is
**off by default**; disabling it bypasses all new GPU allocation and dispatch.
Changes are live and persist with the existing settings save/load path. There
is no restart, native NR re-creation, gaze filtering or history reset when these
controls change. Full-eye and pre-SR routes do not run this outside-crop effect.

A coarse, current-frame 16x16 paired map estimates broad brightness/color
changes between the original crop and its completed NR composite. Gain is
applied only outside the existing rectangle/oval mask, including oval corners,
with an outward fade and small, static screen-space dither. It does not copy
neural detail, add temporal accumulation, or write any inside-mask pixels.
Sampling farther inward changes the estimated tone only; it does not change the
crop image. Near-black samples have reduced confidence. Gains are bounded in
log2 stops, with original alpha preserved. The calculation runs in the existing
LDR buffer representation; it does not assume that buffer is scene-linear.

| Control | Default | Range | Purpose |
|---|---:|---:|---|
| Enable | Off | On/off | Immediate A/B comparison |
| Brightness | 0.65 | 0–1 | Transfer luminance change |
| Color | 0.30 | 0–1 | Transfer chromatic change |
| Fade width | 128 px | 8–512 px | Outside reach; wider bands cost more |
| Falloff | 1.00 | 0.5–2 | Shape of outward decay |
| Static dither | 0.15 | 0–1 | Subtle fade breakup without animated noise |
| Boundary ramp | 8 px | 0.5–64 px | Fade correction in from the untouched edge |
| Tone limit | 0.50 stops | 0–1 stops | Maximum estimated and applied gain magnitude |
| Sampling inset | 8% | 0–25% | Measure farther toward the crop center |

Start with the defaults. If the effect is weak, raise the sampling inset toward
15–25% to get beyond the existing inner feather. If a halo appears, lower
brightness/color or broaden the outside fade. Dither is deliberately subtle.
Some scene-dependent tonal changes cannot be perfectly extrapolated into unseen
periphery; this is an opt-in visual adjustment, not a seamlessness guarantee.

**Measure outside tone GPU cost** requests the existing nonblocking GPU profiler
while this section is open. Runtime profiling must be enabled. It displays the
latest and rolling-average sum of map/application timings for **both eyes**;
these are steady-state pass timings, excluding first-use shader compilation and
resource creation. Turn measurement off after tuning to remove capture-query
overhead. New passes are also visible under `NeuralRendering::OutsideTone*` in
Profiling/Tracy/RenderDoc. No GPU timing or VR quality has been measured in the
build environment. The requested **0.1–0.2 ms** is a target, not a verified
maximum; use your GPU's readout and narrow the band if needed.

Resource/shader failures skip only the tone effect and appear in the controls;
they do not latch an NR failure. Shader-cache clearing retries initialization.
No new full-frame copies or CPU pixel readbacks are introduced. Existing staged
NR writeback remains unchanged. A target without a usable SRV/UAV skips the new
effect rather than forcing an additional copy path.

Devbench: `configureOutsideTone` changes enabled/brightness/color/width/curve/
dither/boundaryRamp/limitStops/sampleInset after validating every argument;
`outsideToneStatus` reports configuration and last application frame/eye count.
Use the existing settings save action to make a Devbench A/B change durable.

Verification includes r2 policy/integration checks, independent outside-mask
protection and eye-isolation tests, eight CPU/HLSL buffer layouts, and Windows
FXC/full runtime compilation. CPU image oracles verify exact interior/alpha
protection, identity transfer, near-black/nonfinite protection and gain limits.
Actual VR visual stability, coexistence under all runtime modes, and the GPU
budget still require the in-game A/B test.

Base: successful v05 source `2963e93f6242696755cac829b7fd59b6590b4ac7`.
The entire v00-v05 transformation chain runs unchanged, followed by a
hash-checked v06 patch. Source-contract mismatches stop before compilation.

## Rendering fixes

- Crop handoff masks never exceed the crop actually rendered, including growth.
- Adaptive gaze crops can use the existing stable SR resource envelope, sized
  from the user's selected crop rather than a fixed 60–85% assumption.
- Atlas backing resources follow the resident per-eye envelope; valid evaluation
  extents remain the current crop. This avoids atlas texture recreation on each
  crop tier change. Existing exact-size fallback remains available.
- Explicit NR history resets now reset the live atlas domain as well as dormant
  independent-eye histories. Ordinary compensated origin motion preserves history.
- Optional residual-reuse layout checks do not reset native history when residual
  reuse is disabled. Motion-mode result stabilization retains history across
  consecutive compensated crop motion using per-pixel reprojection validity; model
  changes and incompatible resource layouts still invalidate it.
- VRS applies the adaptive decision before sampling gaze. VRS/SR/NR share one
  config builder and one crop sample per engine frame.
- Restores the shared integer crop-plan approach from historical Build 19:
  DLSS copies, NR placement and motion-vector scales use the same actual pixel
  rectangles rather than independently reconstructing rectangles from UVs.
- Changing adaptive crop size does not clear the gaze filter. Brief invalid
  samples held within the existing 50 ms grace period do not force a reset on
  reacquisition. Long loss, context/config changes and genuine discontinuities
  still reset safely.

## Overlap-aware crop history

The old crop-motion 25% displacement reset and the new result-stabilization 25%
reset are removed. Consecutive, equal-layout crop moves keep their coordinate
transform regardless of displacement. The existing crop-motion dispatch checks
current-to-previous positions per pixel, including scene motion. In-bounds pixels
retain compensated vectors; pixels outside the previous eye crop are sent outside
the eye/atlas vertically, avoiding cross-eye history aliasing. Source invalid
vectors retain their original representation. Extreme, unrepresentable half-float
rejection vectors fall back to a full reset rather than writing infinity.

The optional motion stabilizer also drops its 50%-motion rejection threshold and
uses previous-position bounds, depth and color tests. While the crop moves, its
history contribution fades over two pixels at the previous crop edge; the stationary
crop does not acquire this new fade. Missing consecutive history, dimension/format
changes, model changes and explicit resets remain genuine invalidations. Newly
exposed pixels use the current result, not an uninitialized or clamped history.

This does not expose or rewrite proprietary Feature18 history. Native history
rejection relies on out-of-bounds reprojection and needs headset verification.
The standalone tests check crop-coordinate correspondence and retained pixel counts
through positive/negative large moves and complete loss of overlap. Windows CI
also compiles both changed shaders as cs_5_0 before building the runtime.

Research references: [NVIDIA NRD](https://github.com/NVIDIA-RTX/NRD) and
[AMD temporal upscaling integration](https://gpuopen.com/manuals/fsr_sdk/techniques/super-resolution-temporal/).
Their history/rectangle contracts support the general design; they are not a
Feature18 dynamic-resolution or per-pixel-reset specification.

## Gaze controls

Adaptive gaze smoothing is enabled by default. New configurations start with
zero fixation smoothing and zero pixel quantization; existing saved values
remain selected. Set smoothing to zero for a direct response.

Controls: fixation smoothing, movement responsiveness, slow/fast movement zones,
immediate jump distance and speed, maximum lag, existing dead zone/quantization,
and a freeze-at-selected-centre comparison toggle.

The adaptive filter smooths the crop-relative derivative, increases response
with speed and distance, bypasses filtering for fast/large jumps, and enforces a
maximum positional lag. Percentages refer to the selected static crop dimensions,
not the changing adaptive tier. The algorithm is speed-adaptive and inspired by
One Euro filtering; it adds crop-relative distance and explicit jump/lag bounds.
It does not delay headset pose updates or add an image-history blur pass.

The provider exposes no sensor timestamp or head pose. No world-space gaze
prediction or measured sensor-age claim is made. The actual head-motion symptom
must still be checked in the headset.

## Exact one-pass atlas ladder

The controller defaults to the requested ladder when adaptive performance is enabled:

| Stage | Relative crop | NR model resolution | NR passes |
|---|---:|---:|---:|
| 0 | 100% | 100% | 1 |
| 1 | 80% | 100% | 1 |
| 2 | 60% | 100% | 1 |
| 3 | 60% | 85% | 1 |
| 4 | 60% | 70% | 1 |

Starts at stage 0. Sustained filtered GPU time above the configured budget advances
one stage; sustained time below budget minus recovery headroom reverses one stage.
No stage drops NR or adds a second pass. Crop percentages are relative to the user's
selected crop. At stage 4, an unmet budget is reported and one pass remains enabled.

Controls: enable/mode, GPU budget (default 20 ms), recovery headroom (default 1 ms),
frametime smoothing, decrease/increase holds, cooldown, crop transition frames,
and residual handoff duration (default 150 ms). Crop floor/step, pass thresholds and
zero-pass recovery controls belong to the retained legacy mode and are disabled
in the ladder mode. Disabling the ladder restores the original v5 policy plus v6
optional first-pass recovery; manual multi-pass settings remain available outside
this mode. Manual model and multi-pass selections do not override the active ladder.

A failed recovery is remembered at the lower-quality stage and cannot be retried
until timing improves by another recovery-headroom amount below its previous trial
baseline. Policy edits clear this evidence. Missing fresh timing clears pending
holds, repeated calls cannot spend time twice, and unfinished crop handoffs block
further quality decisions. Budget is a sustained GPU target, not a hard bound on
individual frames or CPU/compositor time.

Atlas is required at the tuning and renderer boundaries regardless of the saved
manual atlas checkbox. UI shows requested quality and actual atlas activity.
Incompatible routes, packing/evaluation errors or envelope rejection do not silently
switch to independent-eye NR. The renderer reports a failure and retains the current
base rendering. One working NR pass cannot be guaranteed after a runtime failure;
that failure is visible rather than hidden as a different execution mode.

## Transition handling

The ladder atlas keeps backing allocations at the largest selected-crop envelope.
A combined depth/motion pack handles crop source origins, crop-size changes and the
right eye's changing packed atlas origin. At a compatible crop transition, history
reprojection maps to the previous model coordinates and rejects invalid eye-local
positions. The old crop-commit global history reset is bypassed only for this ladder.

The strict ladder shares one native atlas feature across model percentages when
its creation envelope and motion-vector resolution classification remain compatible.
Changing a model percentage alone no longer retires the native feature or requests
a history reset. Previous/current model dimensions and eye origins still determine
reprojection. A real creation-contract change waits for the GPU, retires the feature,
and logs the reset. Backend acceptance and image quality remain unverified; this is
not a guarantee that the closed runtime preserves its internal history correctly.
Allocations/feature creation can still cause a timing spike.

A display-resolution residual history bridges crop/model changes for a configurable
duration. It reprojects the previous unshaped NR residual onto the current live base,
checks depth/color/previous-rectangle validity, and tapers history weight to zero.
It does not freeze the finished image or evaluate both NR tiers per frame. New or
invalid regions use current output. Stable history allocations survive compatible
crop/model changes; previous valid color/guide dimensions are tracked separately.

The result stabilizer now samples allocated texture dimensions while clamping to
valid crop texel centers. History copies use valid boxes, preventing mismatched
CopyResource dimensions and stale envelope reads. This adds residual history work
and memory; performance has not been measured.

SR retains its existing output-size contract. Changing the SR output dimensions can
still require reconstruction history renewal; those necessary resets have not been
suppressed blindly. The residual handoff targets visible regeneration but cannot
prove that an SR base-image transient disappears. Headset acceptance is required.

## Verification

CI checks the retained v05 generated-source invariants before v06 is applied,
checks exact v05 input hashes, applies v06, compiles/runs standalone C++ policy
and crop-actuator tests plus the exact ladder, then builds/packages the full runtime.

Tests cover overlap correspondence beyond 25% displacement, complete loss of overlap,
fixation jitter attenuation, immediate gaze jumps, zero smoothing,
NaN samples, bounded lag, original/first-pass recovery order, cost/retry guards,
overload priority, crop floors/steps and masks bounded by rendered extents.

Devbench actions: `freezeGazeCrop` (enabled boolean), `adaptiveFrameStatus`.
Other settings remain available through the existing generic feature settings API.

Headset acceptance is pending: compare fixed centre, provider active with freeze,
moving gaze with controller disabled, and moving gaze with forced shrink/growth.
Then compare atlas on/off and one pass at all five ladder states. Compilation and policy tests cannot
prove that visible boiling or black borders are eliminated in Skyrim VR.

Package retains CommunityShaders.dll identity and excludes nvngx_dlssnr.dll.

Live configuration can be inspected with `adaptiveFrameStatus`, including budget,
headroom, recovery threshold, ladder stage, model resolution, actual atlas activity
and failure detail. `configureSinglePassBudget` accepts optional `budgetMs` (10–30),
`recoveryHeadroomMs` (0.5–5) and `handoffMs` (0–500). Invalid updates are rejected
before any field changes. The action does not enable the controller or save to disk.
Menu/config serialization already includes these fields. Standalone policy tests
cover changed budgets, exact threshold holds and malformed timing/config values.

### Required runtime transition matrix

The following checks are pending; passing the standalone policy suite does not
verify native feature behavior, shader execution or headset image quality.

| Change | Code behavior | Runtime acceptance |
| --- | --- | --- |
| Budget/headroom edited live | Clear pending decisions and blocked growth evidence | Observe new thresholds and hold/cooldown behavior |
| Crop 100 ↔ 80 ↔ 60 | Stable atlas allocation; previous/current reprojection | No black edges, wrong-eye samples or regeneration flash |
| NR 100 ↔ 85 ↔ 70 | Shared native feature if creation contract is unchanged | Backend accepts extent changes; no visible flash |
| Starting crop changed | Rebuild envelope safely when required | No stale pixels; correct left/right coverage |
| DLSS input resolution changed | Revalidate backing resources and MV classification | Correct motion, depth and crop alignment |
| Display/SR output resolution changed | Existing SR contract renewal remains | No promise of native SR history retention |
| Strict ladder ↔ legacy atlas | Drain GPU and retire atlas features | No reuse of unrelated native history |
| Head moves while gaze is fixed | Adaptive gaze filter and overlap correspondence | Match the fixed-centre stability reference |
| Tracking loss, scene cut, frame gap | Required discontinuity resets remain | No stale reconstruction or wrong-eye history |
| Atlas allocation/evaluation fails | Explicit failure; current base rendering remains | Error visible; no independent-eye substitution |

Test the size rows with fixed centre, frozen gaze-provider crop and moving gaze;
repeat left/right gaze jumps near all crop boundaries. Visual acceptance requires
both headset observation and captured transitions. No hardware measurements or
visual acceptance were performed in this environment.

The follow-up [stack review](STACK-REVIEW.md) records controller frame ownership,
rejected-envelope/menu holds, workload-change timing resets, frozen/held gaze
corrections, SR-only invalidation, stereo writeback failure handling, removal of
inactive controller state, and shared fail-safe sharpening. It also lists the
remaining build/runtime and inherited feature gaps. `verify-stack.py` checks the
specific integration invariants and CPU/HLSL buffer layouts before the CI build.

## v06-r1 head-motion correction

The user's headset test found head-motion flicker only with the forced one-pass
atlas ladder; legacy behavior remained usable. Crop transitions no longer showed
black borders. This revision retains the crop actuator/envelope/writeback fixes.

The strict atlas sent native Feature18 guide motion scaled by model/guide extent;
the legacy route scales it by model/color extent. At 100% model resolution the
former inflates native motion by the SR color/guide ratio (1.5x at a 2/3 render
scale). The native atlas now shares the legacy guide-unit conversion. Shader
model-pixel coordinates still use their separate model/guide conversion.
The strict guide pack also preserves raw motion exactly for unchanged crop/layout,
avoiding cancellation of small motion against large absolute pixel coordinates.
Compensated equal-layout moves use origin delta directly; invalid source-vector
representations and overlap rejection remain intact. Packing offsets and previous
model geometry still handle crop/resolution transitions.

Zero fixation smoothing now means direct gaze samples in both filter modes.
Zero deadzone plus zero quantization also bypasses the legacy hidden micro-guard.
New configs default to zero smoothing; existing saved smoothing values are kept,
so select zero explicitly when testing an existing installation. The adaptive
filter remains an optional control. This correction adds no new blur/history pass
and does not suppress real tracking loss or scene-cut resets.

CI tests native/legacy scale parity over full/reduced guide sizes and 100/85/70
NR resolutions, plus direct subpixel gaze responses in both origin modes.
Shader checks guard exact unchanged motion and source-invalid preservation.
Headset acceptance remains pending: stationary centre and live gaze, all five
ladder states, head rotations/translations, shrink/growth, and tracking loss.
Tracker noise and proprietary backend behavior cannot be certified from CPU tests.


## v06-r2 crop-grid correction

The user clarified the causal history: original OpenNR flickered/regenerated
while moving gaze but did not shake; the initial gaze-history fix removed
flicker/regeneration and introduced trembling. The current r1 version has no
flicker/regeneration. This revision targets image-coordinate correspondence,
not an additional gaze filter. Pre-SR is unchanged at the user's request.

The retained port of the initial history fix is compared against r1. Its
current-to-previous motion sign is correct. The old local SR and NR placement
independently rounded render and display rectangles. For DLSS Performance,
an output origin could advance one display pixel without an input-pixel move;
retained NR history then compensated motion absent from the local SR image.
This mismatch was present beneath the history change, but keeping history
exposed its inconsistency. CPU reproduction establishes the mismatch, not
that it accounts for every headset symptom.

- Default-mode SR derives its output rectangle from the actual input pixels.
  At Performance's exact 2:1 ratio the mapping is identity and uses no added
  resampling pass. Other ratios align color in the existing writeback shader
  and, when necessary, align depth/motion guides to the same display positions.
- Cropped SR camera transforms describe the current and previous cropped
  frusta; ordinary gaze changes preserve history. Engine TAA jitter remains
  separate, and existing motion-vector flags/native scale contracts remain.
- Legacy NR crop compensation removes the extra model-resolution factor.
  Physical displacement must remain identical at 100%, 85%, or 70% NR.
- The moving strict single-pass atlas anchors reduced-model sampling to a
  fixed full-image lattice. Downsampling, depth/motion packing, history, and
  resolve use the same pitch/phase. Previous crop/model dimensions and packed
  right-eye origins remain part of history correspondence and rejection.
- An optional same-pixel result stabilizer uses motion reprojection while
  the gaze crop can move. Zero stabilization still adds no continuous filter;
  the existing configurable ladder-transition bridge is retained.

The FPS decision policy, pass counts, budget/hold/retry settings, neural tuning,
sequential pass tuning, shaping controls, crop transition masks, resource
identity rules, and carrier requirement remain. Full-eye/flat model resizing
keeps its original nominal ratio; Faster mode retains its original placement.
Real tracking loss, scene cuts, incompatible resource contracts, and gaps
still invalidate temporal state. Ordinary same-size gaze movement does not
request DLSS resource recreation or history resets.

Verification includes crop/world-marker and guide alignment across integer
and noninteger SR ratios, 100/85/70 model correspondence, crop/model changes,
flat-path resize parity, successful stereo-frame history ownership, existing
controller/overlap/zero-filter tests, six CPU/HLSL constant-buffer layouts,
compilation of all six involved shaders, and the full Windows runtime build.
The CPU sweep reproduces 4,566 mismatches in the old Performance crop geometry.
Headset acceptance remains required; CPU/CI checks cannot certify zero shakes.

Test with DLSS Performance, deadzone 0, pixel deadzone/quantization 0, fixation
smoothing 0, and both optional filter modes. Compare NR disabled, legacy NR,
and forced one-pass atlas; then test all ladder stages, neural fine tuning,
head rotations/translations, crop growth/shrink, tracking loss, and scene cuts.
Record whether any motion remains in the SR base or only the NR residual.
The package excludes nvngx_dlssnr.dll; retain the existing carrier.

