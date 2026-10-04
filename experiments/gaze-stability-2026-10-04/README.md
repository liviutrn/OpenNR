# Moving gaze crop: coordinate investigation

Latest corrected baseline and ranked investigation:
[Causal reassessment](causal-reassessment.md). The current build has
shaking but no flickering/regeneration; the original build had the
opposite behavior.

Follow-up for the user's 0.5× Performance SR setting:
[Performance SR and historical gaze audit](performance-audit.md).

Investigated the generated source for v6-r1, commit
`b33f184e0a2b5c659351de625a40feb5381c8cda`. These are coordinate and
sampling reproductions, not DLSS/Feature18 GPU measurements. No runtime
fix or new install package is included in this investigation branch.

The headset report is that the FPS controller works, crop changes no
longer expose black borders, but zero deadzone gives severe trembling
inside the moving crop. A nonzero deadzone masks it at the cost of lag.

## 1. Independent crop rounding changes scene placement

`FoveatedRender/CropGeometry.h::MakeEyePlan` floors normalized input
and output rectangles independently. `Modes.cpp::ExecuteDefaultMode`
copies the integer input crop, evaluates SR in local coordinates, and
places its output at the independently rounded output origin.
`Core.cpp::BlendSubrectToOutput` and `SubrectBlendCS.hlsl` use integer
placement and unshifted source loads.

For one axis, denote full input/output extents by Fi/Fo, crop input
origin/extent by I/Ci, and crop output origin/extent by O/Co. A stationary
scene point at full display boundary coordinate P has this geometric
placement under the current crop-local scaling:

    rendered(P) = O + (P * Fi/Fo - I) * Co/Ci

The desired result is P. If Ci/Co differs from Fi/Fo, the error contains
both a scale term and an origin term. Sharing the integer rectangles
between SR and NR does not eliminate either term.

The reproducer calls the actual generated r1 `MakeEyePlan`:

| Normalized origin | Input origin | Output origin | Placement error at 1600→2400 |
|---|---:|---:|---:|
| 0.10010 | 160 | 240 | 0 display px |
| 0.10045 | 160 | 241 | +1 display px |
| 0.10070 | 161 | 241 | −0.5 display px |
| 0.10090 | 161 | 242 | +0.5 display px |

A 10,001-position sweep at each of twelve extent/crop combinations
produced a 1.5-display-pixel range and maximum step for 1600→2400 at
50%, 60%, and 80% crops. 1703→2400 produced ranges up to 2.444 pixels.
Equal full input/output extents produced zero error in this model.
A fixed crop has constant error, so it does not produce this movement.

The inverse affine sample mapping removes this geometric error:

    localSource(P) = (P * Fi/Fo - I) * Co/Ci

The experiment checks its round trip to within 1e-9 display pixels.
This verifies the coordinate algebra only. An actual implementation
needs filtering, crop coverage, and temporal metadata to agree with it.

## 2. NR guides assume coincident color and render grids

`ResultShapingCS.hlsl::GuidePixel` maps local color to guide pixels using
the extent ratio alone. `LadderAtlasGuidesCS.hlsl` similarly maps guide
centers to local color/model coordinates without the input/output phase.
The NR integration publishes output integer origins and cropped raw
render-resolution guides; the crop input origin is not carried in the
native atlas geometry contract.

At output origin 241 and input origin 160 in the table above, the
continuous color-to-guide mapping is displaced by −2/3 of a render
pixel relative to the global eye mapping. This is before nearest-guide
selection. Correcting only the final displayed translation would leave
depth and motion/history sampling inconsistent with color.

## 3. Reduced NR sampling restarts at each crop origin

`ModelResolutionCS.hlsl::SampleExactArea` computes source footprints as
`targetPixel * sourceSize / targetSize`; `DispatchModelInput` supplies
local extents but no global sampling phase. `DispatchModelResolve`
also samples in local normalized coordinates.

The included one-dimensional simulation uses the shader's area
footprints and linear reconstruction. For a stationary alternating
one-pixel stripe signal, a 1000→700 local crop grid moving through
origins 100–110 changes a fixed sample from 0.315 to 0.645. A model
grid anchored to full-eye coordinates stays at 0.360 in every case.

This is an intentionally demanding aliasing test of the model proxy,
not a measured NR output. The matched residual would cancel an identity
model exactly. A real nonlinear temporal model may produce a varying
residual when its input phase changes; that contribution needs a GPU
capture to quantify.

## 4. Cropped resources retain full-eye camera constants

`Streamline.cpp::CheckFrameConstants` supplies full-eye unjittered
projection and current/previous reprojection matrices during cropped
SR evaluation. The bridge carries crop motion scale and reset state,
but no current/previous crop projection. Explicit motion vectors do
include integer input crop displacement.

NVIDIA's [Streamline guide](https://github.com/NVIDIA-RTX/Streamline/blob/main/docs/ProgrammingGuide.md)
requires depth to agree with `clipToPrevClip`, and projection matrices
to exclude TAA jitter. Cropped local NDC describes a different frustum
from full-eye NDC. This contract needs correction; how much DLSS uses
it with camera motion already present in the supplied vectors is not
established by these CPU tests. Crop translation must not be treated
as random TAA jitter or counted twice in motion vectors.

## Required implementation

1. Give each eye one explicit transform between full render, full
   display, local SR, and global NR model coordinates. Retain current
   and previous transforms alongside history. Carry both scale and
   fractional phase, not just integer origin differences.
2. Resolve cropped SR into the full-eye display lattice, preferably
   through the existing composition pass. Give cropped depth and
   camera matrices the same effective frustum. Keep true renderer
   jitter separate and retain correct unjittered motion semantics.
3. Anchor the reduced NR lattice to the full eye for each model tier.
   Its integer global model window can move without changing the
   lattice. Derive downsample footprints, model resolve, raw-guide
   sampling, atlas motion, and previous-depth lookup from that mapping.
4. Keep a padded processing window distinct from the direct gaze mask.
   Internal coverage alignment must not delay the visible gaze center.
   Use existing current-frame background coverage at invalid edges.
5. Preserve the working controller, resident envelope, transition
   coverage, and one Feature18 atlas evaluation. Reset only where the
   history transform or coverage cannot be represented safely.

A final output shift, another smoothing filter, or a reset on every
gaze movement does not satisfy this contract. A global lattice also
does not promise that proprietary NR will never produce artifacts.

## Verification boundary and acceptance cases

Compile the reproducer against **generated r1** source after the v6
patch chain, overriding the header path when the source is elsewhere:

```sh
c++ -std=c++20 -Wall -Wextra -Werror -O2 \
  '-DCROP_GEOMETRY_HEADER="/absolute/generated/source/src/Features/Upscaling/FoveatedRender/CropGeometry.h"' \
  experiments/gaze-stability-2026-10-04/reproduce.cpp -o crop-phase
./crop-phase
```

This reproducer intentionally demonstrates the current defect. It is
not yet a runtime regression test or part of package CI. Add tests of
the actual shared transform once that implementation exists.

The runtime acceptance matrix must include stationary geometry with
moving injected gaze, stationary gaze with head motion, both moving,
all gaze filters at zero, render/display ratios including 1:1 and odd
extents, NR 100/85/70%, both eyes/atlas guards, crop-tier changes,
edge clipping, tracking loss/reacquisition, and skipped frames.
Record SR before NR, model input, native NR output, and final composite
to locate any remaining movement. For an SR-only diagnostic, bypass
Feature18 while keeping the gaze route active: the normal NR-disable
setting also affects whether gaze cropping runs, so it is not a valid
isolation test by itself.

Linux CPU reproductions pass. No headset validation or new Windows
runtime build has been performed for this investigation.
