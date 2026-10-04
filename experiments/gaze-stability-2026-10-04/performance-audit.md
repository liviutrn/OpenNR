# Follow-up: Performance SR and historical gaze invariants

Read the subsequent [causal reassessment](causal-reassessment.md)
for the user's corrected baseline: the historical successful fix had
shaking, and the current build has no flickering/regeneration.

User clarification: SR uses DLSS Performance, approximately 0.5 × 0.5
render resolution (25% of display pixels). The crop-size slider and NR
model-resolution slider are separate from that SR ratio.

## Historical reference

The retrieved conversation record identifies the successful September
24, 2026 package as `OpenNR-2.15.1-Gaze-History-Fix.zip`, DLL SHA-256
`8864fd5824f4a8c599f336362ffc7457047c21af2c7be84e6fcb0cb29e608a05`,
run `35916167130`, branch `fix/opennr-2151-gaze-history`, commit
`269c9c53a2ad4e855e892b40b476d540015d1a7b`. The user reported
“actually it works. its like black magic. great job!” and no flickering
while moving the head. Newly exposed edges and entirely new gaze
locations still had issues.

The source reference used here is the documented 2.20.1 port in
`patches/2.20.1-v00-gaze-history.patch`. The historical commit is not
resolvable in the current public OpenNR repository (GitHub returned
404); this is not a binary comparison with the old DLL.

The fix's protected behavior is persistent history for ordinary
same-size translations, separate SR/NR and per-eye histories, crop
translation represented in motion vectors, and history committed only
after reconstruction succeeds. It reset for invalid/discontinuous
history, changed extents/scales, explicit resets, and large jumps.

## Findings and confidence

### A. Exact 2:1 SR has a one-pixel placement/history disagreement

This is a confirmed CPU coordinate reproduction using actual r1
`MakeEyePlan`. At an unchanged 50% crop and full input/output extents
1200/2400:

| Input origin | Output origin | Expected local SR history displacement | Atlas color history displacement |
|---:|---:|---:|---:|
| 120 → 120 | 240 → 241 | 0 display px | 1 display px |
| 120 → 121 | 241 → 242 | 2 display px | 1 display px |

When the input origin stays still, Default mode copies identical local
scene geometry into SR. The changed output origin translates the
composited image. Strict atlas guide packing and strict residual
stabilization use output-origin differences, so their displacement
also disagrees with the local SR image. Real renderer jitter and camera
motion are additional terms; this test isolates crop displacement.

The previous 1.5-pixel example used a 1.5:1 ratio. At the user's exact
2:1 ratio, equal-ratio crop extents produce a 0/1-pixel phase toggle.
This sharpens the diagnosis rather than eliminating the defect.

### B. Controller crop tiers can change the SR scale despite 2:1 full-eye SR

For representative full input/output widths 1202/2404, the selected
50% crop produces 601/1202 (exact 2:1). Controller scales 80% and 60%
of that crop produce 480/961 and 360/721, with local ratios 2.002083
and 2.002778. These are actual independently truncated extents.

The correction must carry scale as well as origin phase. A single
half-pixel correction, or assuming Performance always gives exact
2:1 local crop dimensions, is insufficient. These dimensions are an
example, not a claim about the user's current headset settings.

### C. Reduced NR grid drift remains an independent problem

The prior `reproduce.cpp` demonstrates changing downsampled proxy data
as a crop-local 70% model lattice moves through a stationary stripe
scene. Full-eye lattice anchoring eliminates that model-proxy change.
It does not measure proprietary Feature18 output or prove that this
alone causes every reported artifact.

### D. Residual stabilization mode 1 does not reproject a moving crop

Confirmed source behavior: `ResultShapingCS.hlsl` adds motion and crop
origin delta only for mode 2. Mode 1 samples previous residual at the
same local pixel. In the strict ladder, result history may be retained
across origin changes even with mode 1 selected. Similar depth/color
thresholds can accept an unrelated old residual. This is conditional
on the selected stabilization mode; the user's setting is unknown.

A moving gaze crop should use the validated reprojection transform or
skip temporal residual reuse. This is independent of gaze smoothing.
Ladder transitions already select mode 2 during their bridge interval.

### E. Legacy residual reprojection depends incorrectly on model tier

For non-strict gaze NR, `CropMotion::Prepare` uses a normalized scale
containing `modelWidth/colorWidth`, and the compensated vectors are
copied to `eye.motionVectors`. Host result stabilization converts those
vectors back to color pixels using `GuideToColorMotionScale`, without
undoing that model factor. With a one-display-pixel output-origin
change and Performance SR, the CPU calculation gives:

| NR resolution | Color displacement seen by legacy residual stabilization |
|---:|---:|
| 100% | 1.000 px |
| 85% | 1.176 px |
| 70% | 1.429 px |

The strict ladder supplies raw copied vectors to host residual
stabilization and adds its own output-origin delta, so it avoids this
particular legacy model-tier factor. It still has finding A.

This audit concerns host shader reprojection, not the undocumented
native Feature18 motion contract. Do not change native motion scales
solely on the basis of this result. Separate raw scene vectors from
native-compensated vectors and use one explicit host transform.

### F. V6 changed the old large-jump protection

The v00 port resets at a translation exceeding 25% of crop extent.
`scripts/v06/stability.patch` explicitly removes this guard from
`CropMotionHistory.h`. The current provider resets on reacquisition or
static/dynamic handoff, but does not restore the ordinary large-shift
guard. The strict atlas also bypasses the old NR `Prepare` route and
uses `LadderAtlasGeometry` for native history.

V6 instead rejects out-of-bounds history per guide sample. That is a
different safety policy, not demonstrated equivalent to the old tested
one. It can be valid, but should not be treated as preservation proven
by source lineage. It does not explain every tiny-motion tremble.

Keep the old targeted protection until a replacement is verified, or
test large jumps/no-overlap and tracking discontinuities explicitly
with native reset and rejection tracing. Retain ordinary translation
history; do not restore blanket reset-on-origin-change behavior.

### G. Raw jittered depth is paired with SR-reconstructed color

The render projection uses a Halton jitter sequence. Default mode
copies native cropped depth; the depth-copy shaders do not remove its
sampling jitter. NR and host residual stabilization use that depth
with post-SR color. `GuidePixel` and previous-depth lookup account for
extent ratios but not current/previous jitter sampling offsets.

This is a confirmed absence in host guide mapping; its visual impact
and the proprietary native depth convention still require a capture.
At Performance SR, up to half a render pixel corresponds to one display
pixel. Temporal depth rejection at thin geometry and silhouettes is
therefore another plausible contributor. Align depth/motion guide
sampling to the color's physical coordinates. Do not insert jitter
into unjittered scene motion or set a jittered-MV flag speculatively.

### H. Cropped SR retains full-eye camera matrices

The previous report's cropped-frustum contract issue remains. Correct
current/previous crop camera transforms while keeping true renderer
jitter separate. Explicit camera motion in supplied MVs may reduce
DLSS's dependency on some constants; GPU contribution is unmeasured.

## Preservation checks performed

`performance-history.cpp` was compiled against both the generated r1
history helper and the actual helper extracted from the v00 patch.
Both retain ordinary one-render-pixel movement without reset and
invalidate for invalid history, skipped frames, changed extents,
changed motion scale, and explicit reset. The large-jump test confirms
the policy difference described above.

Source inspection also confirms Default SR still excludes gaze origin
from resource identity, keeps separate eye slots, and commits them
only when current-frame reconstruction/guides succeeded. Non-strict
NR commits its crop history only after successful stereo reconstruction.
Strict atlas now has its own geometry state; it must satisfy those
same invariants independently, not merely leave the old slots present.

This follow-up modifies only experiments and documentation. No runtime
patch or new install package was produced. Hardware validation remains
necessary before declaring zero-deadzone stability fixed.

## Implementation priority

First establish a single current/previous physical coordinate transform
through SR placement, NR input sampling, guide lookup, atlas vectors,
and host residual history. Anchor reduced NR sampling to full-eye
model lattices and keep direct gaze mask placement separate from
padded processing coverage. Use the same transform for mode 2;
gate mode 1 on actual stationary coordinates. Preserve native motion
scale behavior until its contract is demonstrated. Add a diagnostic
that bypasses native NR without disabling the gaze route, and trace
reset reasons/resource generation alongside SR-before-NR captures.

Run the acceptance cases in the first report at Performance SR first,
including 50/40/30% crop extents and 100/85/70% model tiers. Preserve
the working FPS controller and current-frame transition coverage.
