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
