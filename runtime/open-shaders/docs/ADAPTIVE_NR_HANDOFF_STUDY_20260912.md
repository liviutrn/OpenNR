# Adaptive NR resolution handoff study

Date: 2026-09-13
Branch: `codex/adaptive-nr-handoff-study-opennr-2.14.8-fixed-20260913`
Baseline: OpenNR 2.14.8 snapshot (`3c28bb8f`)
Scope: isolated prototype branch plus an isolated MO2 test profile/mod. The
active MGO profile, its overwrite settings, and the known-good source checkout
remain unchanged. The earlier fixed handoff revision has a successful live MGO
smoke test; the controls revision described below still requires a fresh live
run after it is staged.

Refresh targets: 80 Hz is the primary target requested for this study, with
70 Hz and 72 Hz available as lower controller-budget choices and 90 Hz retained
as a comparison target. The calculations below assume stable 2:1 reprojection;
these controls do not change the physical headset refresh mode. This worktree
was created from the committed OpenNR 2.14.8 baseline; the separately dirty
source checkout was not switched, edited, or folded into this branch.

## Decision

This is realistically feasible as an isolated prototype, but not with the
current “change the model dimensions immediately” implementation. The viable
design is:

1. keep a small number of native resolution buckets pre-warmed;
2. choose the next bucket from a hysteretic frame-budget controller;
3. preserve a per-eye high-quality history;
4. reproject that history with the exact game motion vectors and depth;
5. blend to the new bucket over several frames; and
6. keep the active bucket stable for a minimum dwell time.

The current automatic and manual controls ladder is the shorter
`100, 95, 90, 85, 80, 75, 70` set. The UI shows the approximate model-pixel
area beside each NR percentage; because the percentage applies to both axes,
cost is approximately the square of the displayed scale. Arbitrary one-
percent values are not currently native resource tiers: every distinct
percentage creates a distinct resource/Feature 18 dimension state. The seven
5% steps are the resource/smoothness compromise for this controls build. Older
67/60/50/33 values are clamped to the 70% floor rather than creating additional
native resource states.

For the requested 80 Hz target, a stable 2:1 cadence means approximately 40
new application frames per second and a 25.00 ms application deadline. At
70 Hz the corresponding figures are approximately 35 FPS and 28.57 ms; at
72 Hz they are approximately 36 FPS and 27.78 ms. At
90 Hz the corresponding figures are approximately 45 FPS and 22.22 ms. The
controller should therefore be calibrated from the selected display refresh
rate, rather than treating 90 Hz as a universal constant. If the runtime is
attempting 1:1 application delivery, the relevant budgets are 12.50 ms at
80 Hz and 11.11 ms at 90 Hz; adaptive NR alone cannot make a full game frame
fit inside those tighter budgets.

## Offline experiment

The study harness is [`study_adaptive_nr_handoff_20260912.py`](../tools/study_adaptive_nr_handoff_20260912.py).
It reads the retained full-eye native scale replays and samples every eighth
full-resolution pixel. It compares:

* **hard switch**: full-resolution output changes directly to the reduced
  output;
* **output crossfade**: the current high and low images are blended over N
  frames; this is an idealized visual upper bound; and
* **source/residual ramp**: the reduced residual is gradually increased from
  the full-resolution input, which approximates changing resolve strength
  without retaining the previous high-quality output.

The low-resolution inputs were existing native replays. The matched residual
composition was reconstructed on the sampled grid; no NVIDIA or Feature 18
call was made by this harness.

Representative median results across possible switch positions are below.
The values are mean absolute 8-bit channel levels across both eyes. They are
diagnostic transition magnitudes, not a claim about a human perceptual
threshold.

| Simulated switch | Hard | 4-frame crossfade | 8-frame crossfade | 4-frame source/residual ramp |
|---|---:|---:|---:|---:|
| 100% → 75%, normal sequence | 3.81 | 1.68 | 1.45 | 5.26 |
| 100% → 50%, sequence 2 | 5.64 | 2.22 | 1.85 | 7.46 |
| 100% → 50%, sequence 5 | 6.48 | 2.68 | 2.27 | 8.35 |
| 100% → 50%, higher-motion sequence 4 | 15.92 | 15.58 | 15.71 | 18.89 |

The output crossfade reduces the visible tier boundary in quieter scenes by
roughly 40–60% in this experiment. In a high-motion sequence, normal scene
motion dominates the aggregate step, so a blend cannot remove every local
artifact.

The source/residual ramp is not the preferred handoff. It often creates a
larger first-frame change because `alpha = 0` is the raw source, not the
previous 100% NR output. It can be used as a secondary style control, but it
does not replace a history/output handoff.

The experiment is intentionally optimistic about the crossfade: it has access
to a high-quality current-frame image that a live runtime would not normally
compute after switching down. The production-feasible approximation is a
motion/depth-reprojected previous high-quality image. Running both tiers in
parallel would provide the same image-space blend but would temporarily
double the NR work during the transition.

The harness completed successfully across the four retained replay roots used
for this study (the 75% sequence and the three 50% sequences). That validates
the experiment's repeatability; it does not turn the offline reconstruction
into live Feature 18 or headset acceptance evidence.

## Prototype implementation

The branch now implements the proposed handoff in the renderer:

* `AdaptiveController` derives an 80 Hz / 40 FPS application deadline by
  default, with 70 Hz / 35 FPS, 72 Hz / 36 FPS, and 90 Hz / 45 FPS choices. It
  uses overrun/headroom hysteresis, configurable downshifts, slower upshifts,
  and configurable minimum dwell time.
* `Renderer` owns separate native tier resources and Feature 18 slots for both
  eyes. It pre-warms the seven automatic tiers (`100` through `70` in 5%
  steps) while the adaptive test is active, so a tier switch does not
  synchronously replace the current tier's resources. This reduces first-use
  allocation risk while keeping the number of per-eye resource states bounded.
* `AdaptiveHandoffCS.hlsl` blends the previously displayed tier into the new
  tier over the transition window. It uses separate per-eye color/depth
  history, current exact guides, motion-aware rejection, and depth gating.
* Full Eye and the selected foveated crop both use the handoff. In crop mode
  the handoff is crop-local and the result still passes through the existing
  Feather, Dither, or Hard Copy composite. Moving/resizing the crop invalidates
  the handoff rather than blending unrelated regions.
* Capture mode and the experimental pre-upscale route explicitly disable the
  adaptive controller; they retain fixed-resolution/stage-order semantics for
  validation.
* When adaptive crop is enabled and compatible, pressure handoffs alternate
  `Crop -> NR -> Crop`; if crop is unavailable or already at its 50% floor,
  NR remains the fallback. Restoration remains NR-first and is slower than
  downshift. Eye-tracked foveation retains ownership of crop placement.
* NR intensity, local tone, and structure strength remain fixed during a
  transition. The prototype does not claim that increasing those values makes
  a reduced tier equivalent to the full tier; it only smooths the visual
  handoff.

The renderer still waits for the D3D12 interop queue when a shared frame
resource set changes, and Feature 18 may create a handle the first time a tier
is evaluated. The pre-warm avoids the repeated resource teardown path but does
not prove that handle creation, shader compilation, or driver scheduling is
free of a one-time hitch.

The current code does support changing the NR tuning parameters each frame.
The runtime sets `DLSSNR.Intensity`, local tone, structure, and related values
for every evaluation. This is useful for appearance control but does not save
the neural workload.

The matched-residual shader already applies a scalar residual strength. Adding
a transition multiplier is cheap, but a source-anchored multiplier alone is
not enough. The correct transition should blend a valid high-quality history
with the current reduced result.

## Fine-grained tier economics

The retained native resolution study measured the following two-eye NR cost.
The 95%, 80%, and 70% rows are curve estimates from the measured points and
must be replaced by native measurements before promotion.

| Model scale | Model pixel area | Pair GPU time | Status |
|---:|---:|---:|---|
| 100% | 100.0% | 23.15 ms | measured |
| 99% | 98.0% | 22.76 ms | estimated |
| 98% | 96.0% | 22.34 ms | estimated |
| 95% | 90.3% | 21.12 ms | estimated |
| 90% | 81.0% | 19.33 ms | measured |
| 85% | 72.3% | 17.46 ms | measured |
| 80% | 64.0% | 15.56 ms | estimated |
| 75% | 56.3% | 13.64 ms | measured |
| 70% | 49.0% | 12.39 ms | estimated |
| 50% | 25.0% | 6.94 ms | measured |
| 33% | 10.9% | 4.69 ms | measured |

The refresh-rate comparison below subtracts the measured or estimated pair NR
GPU time from the 2:1 application deadline. A positive number is theoretical
headroom before engine work, other shader features, CPU submission, queue
latency, and compositor overhead; it is not a promise that the whole frame
will fit.

| Target | Display interval | 2:1 application deadline | 100% margin | 95% margin* | 90% margin | 85% margin | 80% margin* | 75% margin | 70% margin* |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 80 Hz / 40 FPS app cadence | 12.50 ms | 25.00 ms | 1.85 ms | 3.88 ms | 5.67 ms | 7.54 ms | 9.44 ms | 11.36 ms | 12.61 ms |
| 90 Hz / 45 FPS app cadence | 11.11 ms | 22.22 ms | -0.93 ms | 1.10 ms | 2.89 ms | 4.76 ms | 6.66 ms | 8.58 ms | 9.83 ms |

\* Curve estimate, not a native measurement.

This makes 80 Hz materially more approachable than 90 Hz. At 80 Hz, 100% NR
has about 1.85 ms of isolated pair-pass margin, so it may be usable only when
the rest of the frame is unusually light. A 95% or 90% bucket is a more
credible first fallback because it buys several milliseconds while remaining
visually close to full resolution. At 90 Hz, 100% is already about 0.93 ms
over the isolated 2:1 budget; 95% is the smallest plausible candidate, while
90–85% provides more realistic headroom for combat. The 99% and 98% steps are
still useful for fine correction after native measurements, but their modeled
savings are too small to be the primary combat-spike escape path.

## Runtime structure and remaining caveats

The prototype should separate shared frame resources from tier resources:

```text
SharedFrameResources
    full-resolution color
    exact depth guide
    exact motion-vector guide

TierResources[100/95/90/...]
    model input
    Feature 18 output
    reduced resolve
    Feature 18 handles/history

TransitionState[eye]
    previous high-quality output
    previous depth/validity
    target tier
    handoff alpha
```

The prototype pre-warms seven automatic tiers (`100, 95, 90, 85, 80, 75, 70`)
per eye when adaptive mode first enters the route. Keeping all one-percent
buckets alive would duplicate too many resources and Feature 18 handles, so
arbitrary 99/98/etc. values remain outside this build. The full-resolution
input and guides are shared rather than copied once per bucket. The pre-warm
itself can be a one-time VRAM/allocation event, and the first Feature 18
evaluation for a tier may still have driver/runtime work; this must be measured
in the live run.

The controller should report both requested and effective state:

```text
requested quality: 94%
effective native tier: 95%
handoff alpha: 0.35
```

That prevents telemetry from claiming that a true 94% Feature 18 graph is
running when the implementation is using a 95% bucket plus a visual handoff.

The downshift path should be fast—approximately four frames is a useful first
test. The upshift path should be slower—approximately eight to sixteen
frames—after a sustained period of headroom. Both eyes must use the same
alpha, while their histories remain separate.

The controller exposes a selected refresh target (70, 72, 80, or 90), assumes
`appCadence = 2`, and uses a derived deadline of `2000 / displayRefreshHz` milliseconds. It
should
use frame-time hysteresis, an emergency downshift rule, and a minimum dwell
time so that an 80 Hz combat trace does not oscillate around 40 FPS, a 70 Hz
trace does not oscillate around 35 FPS, and a 90 Hz trace does not oscillate
around 45 FPS.

The handoff must be bypassed and reset when depth/motion history is invalid,
including teleport/camera-cut/menu transitions or a rejected disocclusion.
The exact game guides must remain authoritative; optical-flow substitution is
out of scope.

## Acceptance gates before live use

This branch remains a study/test branch. Before integrating the controller into
the normal release route, the following evidence is required:

1. Native 95/80/70 replays measure the real cost and quality rather than using
   the curve estimates above.
2. A two-tier prewarm prototype changes from 100% to 90% without an idle-wait
   spike in a synthetic stress loop.
3. The history blend is tested per eye with depth/motion disocclusion handling.
4. A no-capture MGO combat run is tested first at 80 Hz and then at 90 Hz. It
   records app GPU/CPU p50/p95/p99, effective tier, transition state,
   delivered frames, reprojected frames, dropped frames, and the active
   OpenXR/SteamVR route. The 80 Hz 2:1 gate is sustained approximately 40 FPS
   of new application frames; the 90 Hz gate is approximately 45 FPS.
5. The system shows no tier oscillation, stereo mismatch, ghosting on fast
   camera motion, or obvious contrast pumping during repeated combat starts.

## Isolated test deployment

The branch was built with the Visual Studio RelWithDebInfo target. The handoff
shader is included in the inherited 2.14.8 asset tree, and the source-contract
validator passed as part of the plugin build. The original live-tested payload
remains available as a fallback; this controls revision is staged as a new MO2
mod so it inherits the existing OpenNR runtime/model files instead of replacing
the known-good runtime payload:

* Live-tested fallback profile: `MGO NSFW - Adaptive NR 80Hz FIXED 2.14.8 20260913`
* Live-tested fallback mod: `OpenNR EXP FIXED - Adaptive NR + Crop Handoff 2.14.8 20260913`
* Controls revision profile: `MGO NSFW - Adaptive NR 80Hz CONTROLS 2.14.8 20260913`
* Controls revision mod: `OpenNR EXP CONTROLS - Adaptive NR + Crop Handoff 2.14.8 20260913`
* Defaults: adaptive enabled, 80 Hz, 70% minimum NR tier, 50% minimum adaptive
  crop, four-frame NR downshift, twelve-frame NR upshift, thirty-frame NR dwell,
  and 1.0 ms reserved headroom. Adaptive crop remains disabled by default and,
  when enabled, is the first pressure action before the next NR tier.

The controls revision is not selected automatically. After the current game
session is finished, enable only the clearly named CONTROLS mod or create a
separate profile from the existing fixed test profile, keep the normal MGO
native-bridge route, and launch through MO2. The copied `SettingsUser.json`
keeps the experiment from writing the active profile's shared overwrite file.

No production promotion is implied by this branch, the offline numbers, or the
package build. The decisive evidence is still a no-capture live MGO run with
headset-delivered-frame telemetry and visual inspection in both Full Eye and a
foveated crop.
