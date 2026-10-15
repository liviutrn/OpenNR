# DuoView v46 temporal bridge handoff

## Status

v46 implements the crop-history repair identified by the v44 handoff. The
code is based on the v44 off-axis, world-locked crop path. It does not steer a
camera and it does not add an OpenNR/Cheeky-style screen-space correction to
the final color image.

The Windows build and headset/game validation remain separate gates. A green
source or CI build is not a claim that STALKER2's TSR consumed the override
correctly on a PSVR2 headset.

## Root cause addressed

v44 changed the current UE projection and correctly kept the head pose fixed,
but its temporal code only diagnosed the expected fovea-buffer displacement.
It never supplied Unreal with the previous cropped projection. A persistent
ViewState by itself is insufficient when the temporal consumer is not given a
previous projection that contains the moving crop.

The OpenNR r10 stable and Cheeky foveated references were used as ownership
checks: both keep the crop/reconstruction relationship inside the renderer
that owns the history. Their private history data is not portable into UE, so
v46 uses Unreal's public `FSceneView::ClipToPrevClipOverride` contract instead
of copying private renderer offsets.

## v46 implementation

1. `DuoViewState` latches each source's exact UE5.6 view origin and rotation
   at the same constructor-input stage as the frozen crop projection. A
   temporal contract is available only for the same generation, the strictly
   adjacent producer frame, matching source `ViewState` identities and
   matching crop/layout dimensions. A prior failed pair becomes a new
   baseline; the next stable adjacent pair must prove both fresh overrides
   before composition resumes.
2. `DuoViewTemporalMath.hpp` builds each source view-projection from the
   frozen projection, current crop, origin and rotation. It computes:

   `ClipToPrevClip = inverse(CurrentCroppedViewProjection) * PreviousCroppedViewProjection`

   using Unreal's row-vector convention and without adding TAA jitter.
3. `DuoViewUE56Layout.hpp` records the public UE5.6.1 layout evidence used by
   the runtime gate. The mirror has `FSceneView::ClipToPrevClipOverride` at
   offset `0x12a0` and a total `FSceneView` size of `0x1330`.
4. `DuoViewSceneViewTemporal.hpp` refuses to write unless the live object
   proves its Family backlink, State identity, copied constructor Family and
   State, frozen crop projection, origin, rotation and source rectangle. It
   also requires the optional field to be unset and writable, then reads the
   matrix and optional-state byte back after the write.
5. After the first eye-tracked frame, composition is fail-closed unless both
   source views successfully applied the bridge. The same-camera invariant is
   checked before a pair can pass the history gate. A mismatch falls back to
   the existing internal DuoView quarantine path; the protected Build3 branch
   is not touched.

## Verification completed locally

- The v46 temporal bridge matrix test passes head translation/rotation and a
  moving ROI through the full current-to-previous clip transform. Identity,
  singular-projection and invalid-view negative controls fail as expected.
- A synthetic `FSceneView` memory image passes the UE5.6 layout-gate write,
  readback and already-populated refusal.
- All non-Windows independent C++ tests compile with `g++ -std=c++20
  -Wall -Wextra -Werror`, including the existing crop oracle, state tests and
  the new v46 bridge test.
- The source generator was run against the exact Joey backend pin with a
  Windows-shader compiler stub only to inspect generated C++ anchors. The
  actual Windows workflow still requires the real SDK `fxc.exe` and performs
  the complete build, original test suite, source-hash check and package audit.

## Required Windows/functional checks

- Run the v46 workflow on its dedicated branch and inspect the first failing
  step rather than treating a partial artifact as usable.
- Confirm the restricted UESDK remains at
  `3cffbc82429b6165ceec2714f0f0d9ae48f55596` and unchanged.
- Extract the resulting ZIP into a separate test directory. Never overwrite
  the stable 30-minute Build3 install.
- In STALKER2 DX12 OpenXR, test fixed-center first, then eye tracking with a
  deliberate horizontal and vertical gaze movement while turning the head.
  Check stationary world detail in the final image, fovea-local motion, TSR
  ghosts, shadows/Lumen, and first-use frame pacing. Enable the temporal audit
  only while collecting logs.
- If the layout gate refuses a write, the log should identify the first failed
  identity/projection/rect/readback check and the frame should be quarantined,
  not presented as a successful moving-crop result.

## Pins

- OpenNR v46 base: v44 off-axis crop branch head
  `1c116eeea54753c35dd1317462e57cc70d471c37`.
- Joey backend: `5ac7edc207866569334175e4ed8a7517971547f6`.
- UESDK: `3cffbc82429b6165ceec2714f0f0d9ae48f55596`.
- UE5.6 public layout evidence: source snapshot
  `21c8b14bfff55c51074d960563d1d92056a9b09a`.
- OpenNR r10 stable comparison: `1a6057eef550296a7aa7efa6295fa7ad46308fc8`.
- Cheeky foveated comparison: `ad2d43336318ac3c35f4ad42d1032c258e8f3cfc` branch head recorded in the
  originating handoff; its private history implementation is not copied.
