# DLSSNR MGO VR 0.4.2 implementation

This release adds the parts of the current DLSSNR community work that map cleanly
onto the SkyrimVR D3D11 + D3D12-interop path. The existing post-upscale route and
its 0.4.1-compatible defaults remain the safety baseline.

## Included

- Reduced Feature 18 model resolutions: 100%, 90%, 85%, 75%, 50%, and 33%.
- Optional **Matched Residual** resolve for reduced model resolutions. The model
  input uses an exact-area filter, then the model-vs-input difference is composed
  conservatively onto the full-resolution source. This keeps the source dominant
  and limits dark-scene excursions and halos.
- Optional **Experimental pre-upscale NR**. The hook runs immediately before the
  normal DLSS dispatch, so the neural pass can operate on the lower-resolution
  native render image instead of the final display-sized image. In VR it is gated
  to Full Eye + Default mode and uses isolated per-eye color, depth, and motion
  guides. If any contract check fails, the normal post-upscale NR route remains
  available.
- Temporal-history reset when the pre-NR stage changes and when loading/console
  overlays open, preventing a stage-order change or invalid overlay frame from
  contaminating Feature 18 history.

## Defaults and compatibility gates

- Matched Residual: off.
- Pre-upscale NR: off.
- Frame Generation: blocked for the LDR NR integration.
- HDR Display: blocked for the LDR NR integration.
- DLSS Ray Reconstruction: must be disabled when testing pre-upscale NR. The
  experimental mode is expected to be incompatible with RR.
- A pre-upscale failure is fail-closed: it does not replace the native image and
  does not disable the established post-upscale fallback.

The pre-upscale mode is deliberately not enabled automatically. It may reduce
neural work when the game render resolution is below the display resolution, but
it can change exposure/color, remove fine texture, or interact badly with other
post-processing. Compare it against the classic path in the same scene and with
the same head movement before retaining it.

## Deliberately deferred

- **Native Vulkan:** SkyrimVR renders through D3D11; an OpenXR/OpenComposite
  presentation layer does not turn the game renderer into Vulkan. The OptiScaler
  Vulkan path therefore cannot be copied into this implementation as a useful
  SkyrimVR optimization.
- **Exposure-texture mapping:** no verified SkyrimVR exposure resource is part of
  the current Feature 18 parameter contract. The release does not invent an NGX
  parameter or guess a white point; that remains a separate runtime investigation.
- **Dual-GPU offload:** no safe in-process cross-adapter synchronization path or
  VR latency evidence is available. PCIe transfer and synchronization could erase
  the apparent tensor-cost benefit, so it is not included.
- **Full-resolution stereo pre-NR by default:** current independent flat-screen
  measurements put DLSSNR around the 8 ms class at 4K before accounting for VR
  duplication. Full-eye VR remains opt-in and must be measured on the target
  headset.

## Validation performed

- Release Ninja build of `CommunityShaders.dll`: passed.
- `ModelResolutionCS.hlsl` Shader Model 5 compile with `fxc`: passed.
- C++ tests: 1,649 assertions in 153 test cases: passed.
- Git whitespace check: passed.

The repository's `validate_changed` target could prepare the shader tree but could
not invoke `hlslkit-compile` because that executable is not installed in the
current environment. The complete Visual Studio solution still has an unrelated
FidelityFX generated-header failure; the DLSSNR/VR Release Ninja target builds
successfully.

## Required runtime A/B test

Use a fresh isolated MO2 test profile and record both feature markers and actual
headset output. Test, in the same scene and with identical head motion:

1. Classic resolve, 100% model resolution.
2. Classic resolve, 75% model resolution.
3. Matched Residual, 75% model resolution.
4. Pre-upscale NR, 75% model resolution, Full Eye + Default mode.

For each case capture left/right stability, fine texture, exposure transitions,
haloing, Feature 18 success markers, GPU frame time, and reprojection behavior.
Do not treat DLL load, a copied setting, or package integrity as proof of Feature
18 evaluation or two-eye headset acceptance.
