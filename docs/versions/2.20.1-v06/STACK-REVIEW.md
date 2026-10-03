# v6 stack review — 3 October 2026

The recheck found integration defects. Local fixes address those defects; this is
not certification that the Windows plugin or closed neural backend is regression
free. Nothing was published and no GitHub build was started.

## Scope and fixes

Reviewed the retained v00–v05 transformation order, exact v5 generated-source
contract, and v6 execution through VRS, gaze sampling, crop geometry, SR, NR guide
packing, atlas feature lifetime, reduced-model resolve, residual history, crop
writeback, sharpening, settings and diagnostics.

| Finding | Local correction |
| --- | --- |
| VRS/SR/NR could re-enter the controller and change eligibility after the frame's crop was selected | One controller update owns the engine frame; redundant timing/log frame guards removed |
| Failed envelope path did not actually hold quality/crop changes | Policy and actuator hold after SR/NR envelope rejection; a held transition no longer advances its geometry or mask |
| Menu/loading samples could trigger quality changes | Decisions and crop transitions pause in these contexts |
| Old timing and failed-growth evidence survived a starting-crop/resolution/preset change | Reset those measurements and settle on fresh timing for the changed workload; use PerfMode's actual dimensions |
| Frozen gaze crop could report dynamic state and reset history when tracking failed or recovered | Frozen output always uses the selected static crop and never requests a gaze-driven reset |
| Brief tracking loss reused the previous crop size while the adaptive tier changed | Hold the filtered gaze centre while rebuilding the current crop size |
| Gaze-origin policy used hidden global switches | Dead zone and continuous-origin choice travel in the same VRS/SR/NR configuration |
| Previous gaze origin could remain outside a larger crop's new bounds | Clamp the previous origin; recompute origin when crop dimensions change |
| Inactive model controller still supplied diagnostics and provisional tuning | Remove its runtime instance, dead counters, and stale diagnostics; retain shared model-tier definitions and persisted legacy settings |
| SR intermediate renewal also reset compatible NR atlas history | Separate SR-only invalidation for the strict ladder; NR resource/feature contracts still control their own necessary resets |
| Stereo output could be partially prepared before the other eye's resolve/shaping failed | Prepare both eyes before writeback; propagate result-shaping and crop-blend failures |
| RCAS failure could cause stale scratch imagery to be copied into the visible output | Return dispatch success and preserve/copy the current DLSS image on failure |
| Standard and foveated sharpening mapped strengths above 1 differently | Share the conversion, preserve the old 0–1 curve, and expose 0–3 in the existing controls |
| Atlas/dead-zone help and output diagnostics described obsolete behavior | Update them to reflect strict versus legacy behavior and active controller ownership |

The new controller and the legacy controller remain mutually exclusive selectable
policies. The crop actuator does not own a second timing policy. Scene/menu
history discontinuities, non-consecutive frames and real feature-contract changes
still reset the relevant history. Required atlas failure remains explicit.

## Verification performed

- The v01–v05 transformation scripts are unchanged from the known-good v5 commit.
- Reconstruct the exact saved v5 source and apply the v6 patch with hash checks.
- Check transformed source whitespace against a tracked baseline.
- Compile standalone tests with C++20, warnings as errors; test gaze, overlap,
  budget/headroom boundaries, malformed input, legacy policy, ladder/actuator
  integration, repeated frame IDs, transition hold/resume and crop bounds.
- Validate component layouts of CropMotion (32 bytes), ResultShaping (160 bytes)
  and LadderAtlas (112 bytes) against their HLSL constant buffers; compile the
  extracted actual C++ structures and sharpening conversion.
- Add integration-contract and buffer-layout checks to the Windows workflow,
  ahead of shader compilation and the full plugin build.

These source-contract checks guard specific integration invariants. They do not
replace compilation of all Windows source, execution of HLSL or headset tests.
PowerShell transformation replay was not available locally; CI still must prove
that it reproduces the exact saved v5 contract before applying v6.

## Remaining acceptance work

- Full Windows/MSVC and FXC build has not run for v6.
- Native NR may reject or visually mishandle compatible extent changes despite
  retained handles and reprojection; this is a closed backend contract limitation.
- Native SR output-size changes still renew history. The existing fixed allocation
  envelope is not a fixed output canvas and cannot prove seamless SR renewal.
- Atlas acceptance across starting crops, SR/display resolutions, NR percentages,
  gaze loss, scene changes and minimum/maximum tiers still needs the runtime matrix
  in README.md. Black borders, boiling and flicker cannot be judged from CPU tests.
- Feature creation/allocation stalls and residual-history bandwidth/VRAM costs
  remain unmeasured on the user's GPU.
- Before/after-NR sharpening placement is not exposed by the retained v5 stack:
  v02 removed unfinished NR-specific fields in favor of the original shared
  upscaling sharpening path. This review hardens that path; it does not claim that
  an independent after-NR execution option was implemented.
- Unrelated experimental training, capture and optical-flow routes were not
  exhaustively runtime-validated. Their presence does not imply compatibility with
  the strict ladder; existing eligibility and route restrictions remain relevant.
