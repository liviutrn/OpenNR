# Work-session engineering record

## 2026-10-13 — public backend takeover

Read the complete prior handoff, initial project specification, current source transformations, and supplied standalone test evidence. Reused geometry, cropped projection, gaze mapping, settings latch, raster shader and Mono-copy components.

Checked failed run 38310862046 (Windows job 115015981817) and newer branch runs. Earliest causal errors: suppressed UE5.8 transitional manager still referenced by its member/accessor; missing BoundedDiscovery.hpp and MafiaDiscovery.hpp. Source inspection found additional generic private DiscoveryMemory/RtmDiscovery dependencies and references to the suppressed UE5.0–5.3 InitOptions layout. Excluding game names alone cannot safely fix this backend.

Adopted an accessible source baseline: Praydog UEVR 4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d and public UESDK-RenderDoc 418729025bad57b094bf6b2e2b55734454c97de6. Ported Joey's guarded selection and calibrated Mono geometry from becc96692839f0087ccef238f03af618051fb765 and db6729dd9f5745705b1cdec2ec6f51bdc9570983. Added strict patch application. Public Mono port references 53 SDK headers; all are accessible. Missing private APIs were not replaced with fabricated structures.

Requested independent GPT-6.1 SOL Medium review. Reviews identified stale-frame rejection erasing valid state, accidental copy insertion in an OpenVR branch, reversed float/double projection writes, SDK Family-pointer offset mismatch for UE5.5, camera mismatch acceptance, logging macro mismatch, and shader linker requirements. Corrected those issues. Review also identified main-viewport ownership and frozen near-plane validation as requirements for continued scrutiny.

Public backend build 38312753656 launched from commit 97dd43d02b25b4bb0261ac14efca4ef23b991f9d. Windows configuration passed; compilation was still running when the integrated revision was prepared. That first revision is a compilation probe, not a DuoView game build.

Integrated method 6 with two UE view rectangles/projections, a final camera-pose latch, per-frame settings/gaze and a bounded frame ring; a same-queue DX12 raster compositor plus duplicate eye copy; native Toolkit CAPI gaze in the common Mono optical basis; persistent controls and a matching injector ID list. The compositor owns resources/descriptors separately for each retired OpenXR command slot. Production WARP tests execute this class, in addition to existing standalone policy tests.

Portable geometry, gaze, frame, config and state tests passed g++ C++20 with warnings as errors. Original calibrated Mono policy tests passed independently. Source transformation and whitespace checks passed. Windows/full-DLL/WARP outcomes must be read from the latest named workflow; no headset or gameplay test has been performed in this workspace.

Windows run 38312753656 finished with failure: six FUObjectItem.object runtime accesses must use public get_object(); OpenXR logging macro include was missing in that earlier revision. Converted only real runtime reads, retaining generated SDK text where its own structure still uses object. Forced zero effective frame-delay compensation for Mono without overwriting config and locked the producer-frame snapshot.

Integrated Windows run 38313745713: portable policy tests and the new production Compositor::record WARP test passed. The production test compiled the embedded HLSL, executed the BGRA8 raster path and compared all channels of 1,024 duplicated pixel pairs. Full DLL compile was still running at the next revision. Added asynchronous per-command-slot GPU timestamps for compositor plus eye-copy cost, and latched current game near clipping plane.

Further review tightened main-draw camera ownership and excluded non-eye callbacks from DuoView crop/index tracking. The foveal density control now permits up to 4 within the existing atlas bounds (30% crop/density 3 yields 2700×2700 plus 600×600 at 3000 output, 7.65M view pixels); widths above 8192 are rejected because the initial double-wide atlas cannot exceed D3D12’s 16384 texture width. Added WARP retired-slot reuse, moved-crop and GPU timestamp assertions.

Run 38313745713 full-backend compile failed on the already identified FUObjectItem API calls and Win32 min/max macros expanding std::min/max in DuoViewGeometry.hpp. The standalone GPU harness previously defined NOMINMAX, hiding this integration-only error. Parenthesized the standard-library calls and removed NOMINMAX from the production harness so the next GPU compile covers the real Win32 macro context. Superseded runs with these known root failures are cancelled by workflow concurrency when a corrected revision is pushed.

The next review found inherited view-index heuristics could persist across rendering modes. DuoView now uses one explicit UE5 zero-based / UE4 one-based mapping for rectangle, camera and projection callbacks and does not mutate legacy mode index state. Original Mono and Native Stereo keep their existing heuristics. A failed viewport hook is no longer marked installed before enablement succeeds. Strict clean-source patch checks passed independently and locally.

Run 38314928535: all six portable/production WARP tests passed and every full-backend C++ translation unit compiled. The DLL link failed only at FSceneView::get_view_family: FSceneView.hpp forward-declared Family as struct, while FSceneViewFamily.hpp defines class. The out-of-line definition and caller therefore had different MSVC return-type symbol decoration. Matched the forward declaration to the existing class definition; no layout was changed.

## 2026-10-13 — first successful complete public injector

**GitHub Actions run [38316421524](https://github.com/liviutrn/OpenNR/actions/runs/38316421524) passed** on commit `bd74b21f46aa51c6d535680a005682e2572d6965` (Windows 2022). The prior run 38314928535 compiled every backend translation unit, but its DLL link failed due to an `FSceneViewFamily` forward-declaration mismatch. The corrected declaration in the next revision resolved that link blocker.

The complete `windows-injector` job passed the public-source checkout/patch checks, all six portable and production WARP tests, full CMake configure, `uevr` + `vr-plugin-nullifier` + `LuaVR` build, rendering-mode ID checks, .NET 6 Windows injector publish, and upload stages.

**Installable artifact:** `DuoView-Experimental-Windows-Injector-5` (GitHub artifact ID `11777567376`, approximately 101.4 MiB ZIP, 30-day retention); separate build diagnostics `DuoView-public-backend-build-logs-5` (ID `11777267912`). The artifact was downloaded and its ZIP entries verified: 17 files including `UEVRBackend.dll` (11,817,472 bytes), `UEVRInjector.exe` (156,707,116 bytes), `LuaVR.dll`, `UEVRPluginNullifier.dll`, and `TESTING.md`. ZIP CRC verification passed. The downloaded ZIP SHA-256 was `bf48e0ba7644182717e214d5acc5b14b6934978174777a643d9edbf7c95d9cdc`. `BUILD_SOURCE.txt` embeds the expected exact commit SHA.

Inspected the successful `build.log` and `configure.log`: no compiler or linker errors; the log includes non-fatal git-describe complaints from the tagless pinned checkout, third-party MSVC/[[nodiscard]] warnings, and upstream CMake deprecation warnings. These do not invalidate compilation.

**Proof boundary:** full Windows backend + matching injector compile and package are now verified, and production DX12 WARP tests passed. This session has **not** executed UEVR in STALKER 2, confirmed PSVR2 gaze at runtime, or benchmarked real frame rendering. In-game head pose, main view rectangles, temporal shading/TSR behavior, runtime resource formats, and frame-token agreement remain acceptance tests. The exact artifact is suitable for **controlled headset smoke testing**, not yet a stable or performance-verified release. Keep Joey's original injector installation separate.
