# R9 combined rebuild — changes and verification

Parent: combined R8 commit `5fa9a3adc638777cfb23e2c7d730cb15ec74c714`.
Version remains 2.20.1; branch/artifact names distinguish this revision.

## Why the previous revision failed validation

Both feather shaders included `FeatherMap.hlsli` as a sibling path. The
game's `Util::CustomInclude` resolves includes from `Data/Shaders`, so it
attempted the absent `Data/Shaders/FeatherMap.hlsli`. Previous WARP tests
used a sibling-relative loader and missed the compilation failure reported
as model input downsample. Both now use the packaged root-qualified path.

The old CSX patch also skipped six hair material setup blocks while hair
lighting stayed enabled, and protected continuous rectangles without SR
pixel quantization. Those defects are corrected.

## Rebuilt pipeline

1. Resolve the retained same-frame gaze/controller core.
2. `FeatherPlan::Make` produces core and expanded SR plans on the actual
   render grid, contains the core and keeps stereo extents symmetric.
   Params and shader-mask upload use the same planner.
3. SR evaluates the expanded region. Its actual output coordinates define
   the compressed neural map; central lattice/phase and exterior curve
   equations are retained.
4. Explicit packing creates model input. It shares only the sampler with
   uniform downsampling, not its shader setup. Maps, extents and views are
   validated before dispatch.
5. Current depth/motion use the same nonlinear geometry; one Feature 18
   stereo atlas evaluates it. Previous geometry is published after success.
6. A separate resolve variant transfers the neural residual onto SR output
   with exterior strength/fade. Zero residual strength preserves the source
   through resolve rather than mistakenly selecting the packing operation.
7. A failure exposes its specific stage and withdraws expansion next frame.
   Manual Reset Neural Rendering rearms the route.

Gaze sampling, zero-smoothing/deadzone behavior, controller ladder, raw
history ordering and the near-black shader are unchanged.

## Mask behavior and controls

Primary controls: **Upscaling → CSX shader detail mask**. Also retained
under **VR → Stereo → Foveation-Following Effects**:

- CSX lighting detail mask
- CSX water parallax mask
- Hard cutoff for CSX detail mask

Upscaling reports off, bypassed or estimated fully skipped screen area.
Full/near-full SR bypasses masking. Actual render pixel bounds plus a
two-pixel jitter/sampling margin remain protected, independently per eye.

Selected skips are hair self-shadow, LLF contact rays, extra direct wetness
lighting and water parallax. Hair material/tint/tangents and base lighting
stay coherent. Existing SSR/screen-space controls remain separate. This
does not clip every shader. Enlarging SR leaves less maskable area, and
the screen-area estimate is not GPU timing or a promised speedup.

For a centered core spanning 65% of each eye's width and height, 50% SR
expansion produces near-full protected SR and bypasses this mask. A 75%
core bypasses it at 25% expansion. With a 50% core and 50% expansion, the
64-by-64 estimate leaves about 7.6% fully skipped area with feathering, or
25.0% with hard cutoff (1201-by-1122 render eye). These are geometry
examples, not GPU measurements or recommended settings.

CSX coverage was checked against ParticleTroned/skyrim-community-shaders
commit `45a59395bccec9df019cb11f1271c23d476e5f54`:

| Work | R9 coverage |
| --- | --- |
| Hair self-shadow, contact rays, extra wetness lighting | Selective detail mask |
| Water parallax | Selective detail mask |
| SSR and screen-space shadows | Existing OpenNR foveation controls |
| GI/AO center-resolution mask | Not ported |
| Dynamic cubemap cadence and visibility throttling | Not ported |
| Raster shading rate | Existing NVIDIA VRS feature; separate controls and GPU requirements |

CSX has effect-specific budgets, not a universal mask that skips all
shaders. Its GI center pass relies on a cheaper peripheral pass and
separate history/resources; copying only its early-out into OpenNR's
single GI pass would remove peripheral AO/GI. Its cubemap cadence changes
reflection freshness and uses a different task scheduler. This rebuild
does not represent those omitted paths as implemented or validated.

The `shaderDetailMaskStatus` devbench query includes
`estimatedSkippedAreaFraction`. `neuralFeatherStatus` exposes
`rendererFailed`/`rendererStatus`; a failed route no longer reports active.
Registered query descriptions document the new fields.

## Validation

- Exact reconstruction through R7/R8/CSX followed by the R9 patch and
  before/after SHA-256 source contracts.
- Local: 57,600 integrated plans, 748,800 actual SR/jitter corner samples,
  core containment, stereo dimensions, render/display ratios, clipped
  expansion, invalid maps and inactive R7 parity passed.
- Local: retained 6,089 nonlinear geometry cases, 5,670 continuous mask
  samples and six CPU/HLSL layout contracts passed.
- Windows CI repeats controller and near-black/resume tests after R9,
  and compiles final Lighting/Water permutations.
- Whole AIO audited against R7: four expected shader additions, five
  expected payload changes, no removals, other payloads identical; x64
  integration markers and archive integrity checked.
- Artifact delivery is gated on extracted-package execution. The test
  compiles actual `Utils/ShaderInclude.cpp` and uses its production include
  resolver. Strict optimized shaders execute on WARP with D3D11 debug
  validation, including explicit zero-calibration resolve, alpha, fade,
  mapped guides, stereo offsets, guard pixels and active/resident splits.
  Known synthetic residuals replace native neural inference in these tests.

Windows CI completed successfully on 2026-10-09 for build commit
`b91425220cfa3b755933042b85242c8dde1badf5`:

- [Run 37936962593](https://github.com/liviutrn/OpenNR/actions/runs/37936962593):
  full universal DLL build, AIO packaging, source contracts, retained tests,
  142 final optimized Lighting/Water permutations and package audit passed.
- Extracted-package production-loader WARP execution: 1,440 cases passed,
  including zero-calibration resolve and D3D11 debug-layer validation.
- [R9 package](https://github.com/liviutrn/OpenNR/actions/runs/37936962593/artifacts/11621710921)
  and [audit](https://github.com/liviutrn/OpenNR/actions/runs/37936962593/artifacts/11621515952)
  uploaded, expiring 2026-10-23. No payload removals; four expected shader
  additions and five expected changes against the R7 AIO; all other
  payloads identical.
- Inner AIO SHA-256:
  `7a9a08ce39ec55dc80c061107f82c612cde48dab030ce007ff920fc0d9d0fd89`.

The immutable artifact's README was captured before CI completed; these
results and the uploaded audit provide the final software validation.
Native Feature 18, driver/GPU timing and Skyrim VR headset acceptance remain
unperformed. Do not call this revision fully working or faster until
hardware checks succeed.

## Hardware acceptance still required

Install the carrier-excluded AIO while retaining the existing compatible
`nvngx_dlssnr.dll`. Use Reset Neural Rendering to rearm a latched failure.

| Check | Acceptance evidence |
| --- | --- |
| Expanded SR on/off, expansion 0/25/50/100 | No downsample/packing failure; live feather status agrees with the route |
| Gaze movement, crop/model tier changes, pause/resume and reset | Stable left/right placement; no border loss, darkening or stale history |
| CSX detail mask off/on and hard/feathered cutoff | Protected SR remains full quality; selected peripheral effects change coherently |
| Near-full SR | Mask reports bypass; no peripheral cutoff inside SR |
| Same-scene GPU A/B | Hold camera, resolution, SR coverage, NR tier and effects fixed; compare GPU pass times and total frame budget |

Read `shaderDetailMaskStatus` and `neuralFeatherStatus` through devbench
alongside the log. A screen-area percentage is evidence of mask geometry,
not a performance measurement. SE and VR in-game checks required by the
runtime repository's AGENTS.md remain outstanding in this environment.
