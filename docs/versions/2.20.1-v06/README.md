# OpenNR 2.20.1-v06 — gaze stability and recovery controls

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
