# Experimental stereo Quad Views

This work starts from the user-tested Build182 DuoView baseline and adds
a separate rendering mode, ID7. ID6 remains the original monoscopic
DuoView path. ID7 is intended to render four engine views: left/right
context at reduced resolution and left/right focus with cropped frusta,
then compose a distinct full-field image for each eye.

**Status:** portable contracts and the production D3D12 compositor pass
Windows CI. The engine/OpenXR adapters are integrated as experimental ID7.
Build-specific results are recorded in the matching Actions run and package
provenance files. The first headset test of Build 5 produced black output
without a crash; the delivery correction needs a new headset test.

## Initial target

- STALKER 2 (UE5.5), DX12, OpenXR.
- Standard stereo OpenXR submission; runtime quad-view support is not needed.
- Fixed-center focus. Gaze tracking is not part of the initial ID7 path.
- Default focus width/height: 50%/50% of each eye's image.
- Default context resolution: 20% per axis.
- Focus sampling density: 1.0 relative to the selected eye output size.
- The existing full `2W x H` scene-target allocation is retained.

The nominal view rectangles cover 29% of ordinary native-stereo raster
area at these defaults. That is a geometry calculation, not a GPU-time
savings measurement; engine work, allocations, temporal processing, and
four-view overhead remain.

## Planned package test procedure

Use a separate extraction folder for the experimental package, keeping
the working Build182 package available. Run the included injector with
the same known-working game and SteamVR/OpenXR configuration as Build182.
Select **Quad Views Stereo (Experimental)**, ID7.

Extreme Compatibility, split-screen, SceneView compatibility, 2D Screen,
and Stereo Emulation must be off for this initial implementation. Quad
mode bypasses Native Stereo Fix rather than generalizing its two-source
capture mechanism. Ordinary Native and DuoView settings remain separate.

Start with the default crop and context controls. Check that the image
has stereo depth, the focus region is centered in both eyes, head movement
remains coherent, and there are no flashes or recurring delivery stalls.
Then test for at least ten minutes. Automated CI cannot perform this test.

Compositor diagnostics are 0 = blended image, 1 = context only, 2 = focus
only, and 3 = synthetic eye/source colors. Mode 3 verifies compositor
mapping; it cannot prove that the engine rendered four scene views.

## Validation and limits

See [VALIDATION.md](VALIDATION.md) for exact CI commits and run links.
Tests cover asymmetric projection crops, explicit eye mapping, distinct
histories, immutable source/pose ownership, asynchronous delivery, GPU
pixel output, and compositor slot retirement.

Engine-created view/history identity and actual RHI execution must still
be observed through the injected adapters. Native secondary-pass shading
and the game's temporal upscaler may require further work with four views.
No performance increase, complete shading parity, or ten-minute crash-free
gameplay result has been established for ID7.
