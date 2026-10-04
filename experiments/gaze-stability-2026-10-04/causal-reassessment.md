# Corrected baseline and causal reassessment

Latest user clarification on October 5, 2026 (Bucharest):

| Build | Flickering/regeneration | Image trembling/shaking |
|---|---|---|
| Original OpenNR | Present | Absent |
| Successful September 24 gaze-history fix | Solved | Present |
| Current tested build | Absent | Present |

This supersedes earlier assumptions that the old successful fix was
visually stable in every respect, or that the current build still
has the earlier reported forced-atlas flickering. The old fix solved
history regeneration; it did not solve shaking.

## Revised causal interpretation

The major behavioral change in the gaze fix was retaining SR/NR
temporal history and adding crop-motion compensation. Shaking
appearing alongside that change makes inconsistent retained-history
reprojection the first investigation target. It does not prove one
specific compensation formula or native backend contract is wrong.

Independent crop rounding was already possible in the original
crop-local architecture. Its existence alone therefore cannot explain
why the original did not visibly shake. A plausible causal chain is
that fresh history limited accumulation of the coordinate error,
whereas retained history repeatedly mixes spatially inconsistent
samples. That amplification is an inference, not a measured GPU result.

The strongest concrete mismatch remains Performance SR's differing
input/output-origin deltas. The local SR scene image can move by zero
or two display pixels while NR host/atlas reprojection assumes one.
The desired coordinate contract must describe the actual SR sampling
footprint, not merely the displayed rectangle's integer origin.

## Checks that narrow the search

The SR translation sign and normalization are mathematically correct
for a same-size crop. Let Scur/Sprev be full-render scene positions,
Icur/Iprev crop origins, F full render extent, and C crop extent:

    rawMV = (Sprev - Scur) / F
    cropOffset = (Icur - Iprev) / F
    previousLocal = (Scur - Icur) + (rawMV + cropOffset) * (F/C) * C
                  = Sprev - Iprev

A 100,000-case randomized algebra check produced a maximum error of
4.55e-13 render pixels. Actual v00/r1 history-helper checks in
`performance-history.cpp` also verify ordinary translation. This rules
out a simple reversed SR crop delta under the stated motion convention;
it does not verify DLSS's internal use of camera matrices or sampling.

FP16 rounding after adding a one-display-pixel compensation at 2400
display extent was also modeled. At zero scene motion the extra error
was approximately 0.000214 display pixels; at normalized raw motion
0.005, 0.01 and 0.05 it was approximately -0.0021, +0.0071 and +0.0254
pixels. These representative values make half-precision rounding a
lower-priority explanation for extreme trembling with little scene
motion. This is not a universal error bound or a GPU format capture.

## Ranked hypotheses

1. **Inconsistent NR reprojection of moving SR content.** Confirmed
   coordinate mismatch, especially relevant to the change that retained
   history. Verify native NR and host residual output separately.
2. **Cropped SR matrices disagree with cropped resources.** Confirmed
   source contract difference; DLSS's actual contribution is unmeasured.
   SR's supplied MV crop delta is correct, but the camera constants
   continue to describe full-eye current/previous projections.
3. **Residual history uses an inappropriate transform.** Mode 1's
   same-local-pixel history sampling and the legacy reduced-model
   factor are conditional confirmed host issues. Avoid attributing
   them to this run without establishing the active mode/route.
4. **Reduced NR lattice phase and jittered-guide alignment.** Confirmed
   sampling differences, plausible temporal contributors. A diagnosis
   must also explain shaking when NR model resolution is 100%, if
   observed; reduced-grid drift alone cannot do that.
5. **Gaze noise drives repeated processing-origin changes.** It can
   expose the defects and explain why a deadzone masks them. The
   content should retain world position even when the mask moves.
   It is not enough to label the whole image motion as tracker noise.

Resource churn, reset storms, and tracking reacquisition should be
traced as safeguards, but the user's current absence of regeneration
puts them below coordinate/reprojection defects in the causal ranking.

## Discriminating capture plan

Use a stationary scene/camera and inject a deterministic gaze path
through the two rounding boundaries in `performance-history.cpp`.
Record pre-SR crop color, SR local output, composited SR before NR,
NR model proxy, native NR result, host stabilized residual and final
composite. Compare overlapping scene content in full-eye coordinates;
moving local pixel indices by themselves are expected.

Then use three narrow diagnostic variants with gaze still active:

- Bypass NR while preserving the moving SR route. Shaking here locates
  an SR or composition problem.
- Keep native NR enabled but bypass host residual temporal blending.
  A change here locates host residual-history behavior.
- Use a stable full-eye SR reference feeding the same moving NR crop.
  This isolates moving SR from moving NR at additional SR cost.

Keep model resolution at 100% first, then compare 85/70%. Compare
stationary versus moving gaze and head motion separately. Log integer
and physical origins, crop extents, jitter, effective scales, native
reset reasons, resource generations and the history frame consumed.
Normal NR-off settings are not an adequate bypass because they also
gate whether gaze routing is active.

## Candidate fixes and tradeoffs

The preferred correction is one explicit physical current/previous
mapping across SR placement, guide sampling, native NR input/model
lattices and host history. It must preserve small-motion history and
single-pass atlas operation. Move the visible gaze mask directly over
padded coverage. Grid alignment is internal processing geometry, not
a gaze deadzone.

A fixed/full-eye SR processing window with a moving NR/mask window is
a useful reference or fallback architecture if cropped SR cannot meet
its temporal contract. Its extra SR workload must be measured before
adoption. Retaining a larger stable processing window can reduce
relocation frequency, but by itself does not guarantee correct NR
reprojection or eliminate processing-window handoffs.

No runtime changes are included here. Current no-regeneration behavior
is a protected acceptance requirement alongside zero-deadzone content
stability, the working controller and the black-border correction.
