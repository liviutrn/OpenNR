# CSX 3.20 FOV mask investigation and OpenNR port

## Baselines

- OpenNR: R8 `8fbfc13929ec6251cf05d4fed2bad667138b6bfa`.
- Supplied CSX AIO: 3.20.0-VR, build manifest source commit
  `45a59395bccec9df019cb11f1271c23d476e5f54`, dirty build.
- Public source: https://github.com/ParticleTroned/skyrim-community-shaders
  at that commit. Uploaded shaders are the authoritative comparison for
  this build because its manifest records local changes.
- Balanced preset: lighting, SSR, water-parallax and Wetterness masks
  enabled; hard cutoff disabled. Its center-area value is not copied into
  OpenNR: OpenNR owns crop/gaze geometry.

## Findings

`Common/FoveatedMask.hlsli` computes a power-four superellipse with a
feathered edge. `Common/FoveatedShaderDetail.hlsli` maps mode 0/1/2 to
passthrough/feather/hard cutoff and exposes a zero-weight work-skip test.
`State.cpp` supplies per-eye centers and effect modes. CSX consumers
explicitly gate individual expensive calculations. No universal raster,
compute or neural-inference clipping follows from including this helper.

CSX's Lighting shader gates auxiliary hair self-shadow, contact shadows,
extra wetness light evaluation and parallax-shadow quality. Water gates
parallax and contact-shadow rays. Screen Space GI and Screen Space Shadows
have their own compute-mask paths; Dynamic Cubemaps has separate scheduling
controls. These are distinct optimizations rather than all-shader masking.

## Implemented compatible subset

The port adapts the same mask and per-effect early-skip design to OpenNR's
existing shader versions. Lighting gates hair rays, LLF contact rays and
three extra direct-wetness evaluations. Water gates LLF contact rays and
three parallax marches, with reduced transition sample counts and weighted
UV displacement. Zero weight is checked before marching, rather than
rendering full quality and blurring afterwards. Base lighting and material
normals remain available outside the mask.

OpenNR already contains the shared superellipse helper, SSR foveation and
foveated Screen Space Shadows. This change extends that infrastructure;
it does not copy CSX's newer monolithic upscaler or DLSS implementation.
CSX-only Wetterness and cubemap scheduling are not transplanted.

`ShaderDetailMask.h` circumscribes both eye rectangles using a slightly
conservative fourth-root-of-two radius multiplier. Narrow/wide crops and
unequal per-eye sizes are protected. Nearly full vertical coverage bypasses
the mask rather than clipping the protected rectangle. R8's expanded SR
rectangles use the existing `FeatherGeometry::Expand` helper with the same
route conditions as Params.cpp. This deliberately protects the expanded
region and can reduce the saving when exterior expansion is large.

The actual mask's centers are those returned by the existing gaze/crop
path. No additional smoothing, deadzone or temporal neural operation is
introduced. Menu/reflection exclusions occur in the pixel shaders using
pass descriptors; the CPU's activeReflections flag is latched through the
frame and is therefore unsuitable as a main-view mask enable gate.

The three floats after RefractionScale formerly used as padding now carry
lighting mode, water mode and a reserved zero. CPU static assertions and
D3D reflection validate that the next wind field stays at the same offset.
No GPU resource, extra render pass or additional synchronization is added.

## Reconstruction and verification

The repository stores cumulative exact source transforms. The workflow
replays the existing v00–R8 chain, executes inherited tests, then applies
`scripts/csx-mask/csx-mask.patch` through an exact SHA-256 before/after
contract. Do not edit the checked-in pre-transform runtime files as though
they were the deployed R8 renderer.

The patch touches the shared mode upload, VR controls, mask profile,
Lighting/Water shaders and WaterParallax helper. It leaves NR renderer,
DLSS submission, crop motion, gaze sampling and guide shaders untouched.
CPU tests exercise stereo offsets, edge-clamped centers, rectangular
corners, unequal eye sizes and full-eye bypass. WARP executes the actual
HLSL helper in off/feather/hard-cutoff modes and reflects the production
SharedData layout. Shader compilation selects all singles and pairs of
material defines represented in the upstream Lighting/Water fixtures for
VR and SE, with full and minimal feature sets. This is representative
compilation, not every possible permutation or in-game acceptance.

A package audit against the compiled R7 package allows only the existing
R8 feather shaders, the new detail include, the four modified shader files
and the compiled DLL to differ. Every changed/added shader is checked
against this build's actual source. Build reports explicitly mark headset
acceptance and hardware timing as unperformed.

## Attribution

Mask/effect-gating design: ParticleTroned/CSX, linked above. Shared shader
lineage: Community Shaders/Open Shaders. The existing shader MIT license
is retained. This is an OpenNR derivative, not an official CSX release.
