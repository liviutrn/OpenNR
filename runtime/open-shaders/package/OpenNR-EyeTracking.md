# OpenNR native OpenVR eye-tracking experiment

This package contains the opt-in native OpenVR gaze experiment within
OpenNR 2.15.0. The provider is compiled into `SKSE/Plugins/CommunityShaders.dll`
and reads the already-loaded game's OpenVR `IVRSystem_026` interface. It does
not initialize or shut down OpenVR, replace the Streamline/Feature 18 ownership
path, ship an OpenVR runtime, or install an OpenXR API layer.

## Enablement

In the in-game menu, open `Neural Rendering`, then the foveated-rendering
settings. Enable `Native OpenVR gaze provider`. The experiment also requires
VR rendering, DLSS upscaling, `Foveated Default`, and a cropped (non-full-eye)
static region. It is disabled by default.

The smoothing and crop-movement quantization controls are intentionally exposed
because the correct values depend on the headset, tracker, OpenVR runtime, and
game frame pacing. Start with the defaults and change one value at a time.

## Safety and status

The provider fails closed to the persisted static crop when VR, focus, menu and
loading state, the OpenVR interface, gaze validity, dimensions, or sample
freshness are not acceptable. It holds a recent sample briefly, returns to the
static crop after the stale timeout, and requests temporal-history invalidation
when a discontinuity is detected. Diagnostics in the same settings page report
the interface, sample sequence, age, filtered gaze, active/fallback state, and
history-reset state.

The gaze provider remains experimental. A compatible eye-tracking headset and OpenVR
runtime are required for live validation; no headset acceptance was performed
as part of packaging.
