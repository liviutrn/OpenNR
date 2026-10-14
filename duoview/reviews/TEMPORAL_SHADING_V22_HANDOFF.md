# DuoView temporal stability and runtime shading experiment v22

## User request and baseline

The user requested improvement 1 (gaze stability), improvement 3 (crop image,
projection/history/motion-vector coherence) and improvement 2 (shading), with
an in-game toggle for shading that starts off and can be enabled after DuoView
is stable. Preserve the completed v21 Build26 and original Joey Build3.

Build26 source: 28dae2e13666b4f5513b6666546e8620d0926ce4.
Run: https://github.com/liviutrn/OpenNR/actions/runs/38543842360
Artifact: https://github.com/liviutrn/OpenNR/actions/runs/38543842360/artifacts/11884263766
All 50 tests, exact SDK/source checks, complete Windows build and independent
archive/source-hash/AMD64 binary inspection passed. It restores old behavior
but does not contain v22 changes.

User retested old Injector-5: good foveal shading, worse peripheral shading
and twitchy gaze. The earlier claim of perfect shading in both old sources is
superseded. User accepts this limitation for comparison.

## Implementation

### 1. OpenNR-inspired crop stabilization

Reference source inspected: OpenNR r10 GazeCropPolicy (source attribution
commit 3a403d6fea9cc73818b1cdd7473bd6fd9cb5cb98), copied by Cheeky in
CheekyPort/overrides/src/OpenNR_R10_GazeCropPolicy.h on
experiments/cheeky-psvr2-r10. Cheeky's apply_overrides.py confirms compatible
crop translations preserve overlapping history with backend MV handling.

New DuoViewCropStability.hpp uses r10's crop-origin guard: retain the previous
crop inside min(2% full image, 5% crop extent); align repositioned crop to a
four-foveal-source-pixel lattice without resizing it. UI stabilization defaults
on, has an Off toggle and an effective 0-5%-of-crop guard control. Large gaze
moves recenter immediately. No additional temporal smoothing or slew is used.

On gaze loss, the ROI position may remain fixed for 100 ms after the last
usable gaze read. It is still labelled unavailable; no stale image or pose is
reused. CAPI sample validity remains bounded by its existing 50 ms policy.
The hold protects against abrupt blink-to-center crop shifts. Reset on output
size, crop dimensions, density, source index, method generation or clock reset.
Rejected/out-of-order frames do not mutate accepted crop state.

### 3. Actual projection coherence repair

Confirmed v21 integration defect: State::begin stored a frozen projection, but
calculate_stereo_projection_matrix later updated the runtime and reread a live
projection before applying the frozen crop. Neither original view actually
used ViewFrame::projection. Thus source projection and compositor/gaze basis
could differ within the same frame.

v22 apply_frame_projection copies all 16 frozen elements into each view's
actual projection, then applies the foveal crop only to the chosen fovea.
Near clipping is captured once with the packet. Nonfinite packets are rejected.
The original runtime update remains, preserving Joey lifecycle behavior; its
live matrix cannot replace the packet's source projection.

Unreal retains ownership of ViewStates and previous view matrices. Crop
translations keep render dimensions/resources stable and do not trigger our
own history resets. The new source observations report separate/shared
ViewStates. We do NOT inject Cheeky's post-render crop-motion offset into
Unreal-generated velocity textures: here cropping changes the projection
before rendering, and a second offset could double-compensate motion.

Tests independently check stationary world-point reconstruction through moving
cropped projections, the expected previous/current local-UV displacement,
constant render dimensions, fractional-density sampling-grid phase, rejection of a changed live matrix, and immutable
source/compositor settings. These prove CPU geometry/coherence, not actual
STALKER 2 TSR/Lumen history quality. No custom engine memory offsets, guessed
PrevViewInfo layout, raw velocity texture patch or forced per-frame camera cut
is used. Remaining engine temporal artifacts must be measured in the headset.

### 2. Runtime independent-primary shading toggle

UI: Independent primary shading (experimental, runtime only). It starts off
on each injection AND rendering-mode transition and is intentionally excluded
from persisted options, allowing activation after DuoView settles.

At a matching main viewport FSceneView constructor, keep the original source
eye index/state selection. Only when view 0 and view 1 have proven nonzero,
distinct ViewStates and both rectangle/projection observations with a captured
Mono camera does the SECONDARY constructor temporarily receive PRIMARY.
The existing ScopeGuard restores the original init options after construction.
The original family list/count and view-state pointers are not altered; this
preserves the second primary's position in the paired family.

Toggle requests are latched in the immutable source frame; Off applies to the
next producer frame. UI shows actual constructor adaptation versus waiting for
safe pair evidence, and observed separate/shared histories. Original Mono ID5,
Native Stereo ID0 and global Native Stereo Fix behavior remain untouched.

This is a **constructor-only independent-shading experiment**, not the complete
Native Fix implementation. It does not create a capture target, duplicate
BeginRenderViewFamily transactions, decrement frame counts or reroute XR copies.
It may improve primary-dependent shading without the full Native Fix's capture
bugs/cost, but shader/history parity and paired-primary renderer behavior are
NOT headset-proven. Do not claim a complete Native Fix port or guaranteed good
peripheral shadows. A separate render-transaction design may still be needed.

## Offline verification and continuation

Local: five portable C++ suites and production contracts against exact applied
backend headers passed, with expanded stabilization, mapping, history/state and
toggle fixtures. Exact original source edit anchors applied successfully.
Windows must run all three pinned, six independent and 41 original suites,
compile the full backend/frontend, freeze source hashes and package the ZIP.
Then independently download, inspect hashes/provenance and AMD64 DLLs.

Keep SDK/backend/frontend pins identical to Build26. No restricted SDK source
is bundled or altered. No per-frame shader compilation, added GPU wait,
forced gamma correction, global Lumen CVar or stale-frame reuse is introduced.

## Efficient headset test

1. Inject separately, choose DuoView ID6, match Build26 crop/density/periphery
   settings and confirm Stable gaze crop is on; shading is off.
2. Compare fixation and fast gaze moves, then head motion. Check crop-border
   motion separately from content jumping/shimmer. Stabilization can be turned
   off in-game for an otherwise matched comparison.
3. After DuoView settles, enable independent primary shading. Check the UI says
   applied rather than waiting; compare shadows, image stability and frametime.
   Toggle off again to verify reversibility. Never enable the global Native Fix
   expecting it to control this ID6-specific feature.
4. Original Mono ID5 remains the control. Record any startup crash, periodic
   hitch, quarantine, content jump or history artifact; then longer gameplay.

Sampling-grid correction: quantization uses the actual rounded foveal source
width/height, rather than full output pixels. This keeps translations aligned
with the submitted view grid even at fractional density (tested at 1.8x and
3400x3172 output). The crop guard caps the alignment step; clipped frustum
edges retain bounded coordinates. No new GPU operation is added.
