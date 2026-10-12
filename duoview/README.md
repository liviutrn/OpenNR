# DuoView Mono for UEVR

Experimental dual-view monoscopic foveated rendering for STALKER 2, DX12, OpenXR and PSVR2 Toolkit.

- Two internal Unreal views share one final camera position and rotation, retaining native 6DoF head tracking.
- A reduced-resolution full-FOV peripheral view and a high-density cropped foveal view are composited into one Mono image for both headset eyes.
- Native PSVR2 Toolkit gaze uses the calibrated common Mono optical projection, with no spatial smoothing or deadzone.
- Frame settings, gaze, view rectangles and optical projection are frozen for the pair; incomplete or mismatched packets are rejected.
- Crop width/height, foveal density, peripheral scale, feather, gaze/fixed center, debug border and source view are configurable and persistent.
- Original Mono (ID 5), DuoView Mono (ID 6) and Native Stereo remain distinct selections.
- Public UEVR/UESDK sources, strict pinned transformations, Windows Actions injector packaging and independent policy/production WARP GPU tests.

This is not OpenXR quad views. Different UE rectangles request less rendering work, but actual game shading savings, temporal stability and headset output require STALKER 2 testing. Standalone WARP execution and full DLL compilation are separate milestones. No gameplay performance gain is claimed.

Use the **DuoView public backend Windows injector** Actions workflow. Download the complete injector artifact from a successful current run; build-log artifacts do not contain an installable injector. Follow [TESTING.md](TESTING.md).

The public-backend port retains Joey's calibrated Mono approach, but excludes newer private-SDK compatibility hooks and DIBR modes. See [WORK_LOG.md](WORK_LOG.md) for verified development evidence and [HANDOFF_CHATGPT_WORK.md](HANDOFF_CHATGPT_WORK.md) for the inherited handoff.
