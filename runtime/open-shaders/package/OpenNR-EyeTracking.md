# OpenNR native OpenVR eye-tracking experiment

This package contains the opt-in native OpenVR gaze experiment within
OpenNR 2.15.1. The provider is compiled into `SKSE/Plugins/CommunityShaders.dll`
and reads the already-loaded game's OpenVR `IVRSystem_026` interface. It does
not initialize or shut down OpenVR, replace the Streamline/Feature 18 ownership
path, ship an OpenVR runtime, or install an OpenXR API layer.

## Enablement

In the in-game menu, open `Neural Rendering`, then the foveated-rendering
settings. Enable `Native OpenVR gaze provider`. The experiment also requires
VR rendering, DLSS upscaling, `Foveated Default`, and a cropped (non-full-eye)
static region. It is disabled by default.

Eye movements update immediately. Fixation smoothing applies only to noise within
two input pixels; it defaults to zero and saved values do not delay larger moves.
A small central guard and bounded quantization stabilize the crop during fixation.
Crossing the guard recenters the crop without changing its dimensions. Both DLSS
and NR history reset when the crop moves, rather than reusing misaligned history.

## Safety and status

The provider falls back to the persisted static crop when VR, focus, menu/loading
state, the OpenVR interface, dimensions, or gaze validity are not acceptable.
It holds the last crop for up to 50 ms after an invalid
query, then switches once to the static crop. Fixed-size tracking/fallback changes
retain GPU allocations. If enabled, VRS consumes the same frame's gaze crop.

Diagnostics report query cost, valid-query count, time since the last valid query,
filtered gaze, crop changes, fallback and reset state. The center API has no sensor
timestamp: query age is not tracker age. The `Upscaling` devbench query
`eyeTrackingStatus` exposes these fields plus raw gaze and crop coordinates.

The gaze provider remains experimental. A compatible eye-tracking headset and OpenVR
runtime are required for live validation; no headset acceptance was performed
as part of packaging.
