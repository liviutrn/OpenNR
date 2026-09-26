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

Legacy response follows gaze immediately. Adaptive response adds a small fixation
deadband and timed catch-up. That catch-up also eases crop recentering. The crop
stays still while the gaze target remains inside its movement guard; outside it,
the crop eases toward the live target instead of snapping between quantized pixels.
Brief invalid samples keep the held crop and its temporal history. A longer loss
returns to the saved static crop and resets history at the handoff.

## Safety and status

The provider falls back to the persisted static crop when VR, focus, menu/loading
state, the OpenVR interface, dimensions, or gaze validity are not acceptable.
It holds the last crop for up to 50 ms after an invalid query, then switches to
the static crop. Fixed-size tracking/fallback changes retain GPU allocations. If
enabled, VRS consumes the same frame's gaze crop and filtering configuration.

Diagnostics report query cost, valid-query count, time since the last valid query,
filtered gaze, crop changes, fallback and reset state. The center API has no sensor
timestamp: query age is not tracker age. The `Upscaling` devbench query
`eyeTrackingStatus` exposes these fields plus raw gaze and crop coordinates.

The gaze provider remains experimental. A compatible eye-tracking headset and OpenVR
runtime are required for live validation; no headset acceptance was performed
as part of packaging.

## Experimental one-eye NR

The optional `One-eye NR + residual reprojection` mode evaluates DLSS 5 NR for
one eye, then reprojects only the difference between that eye's NR result and
its SR input into the other eye. The target keeps its own SR image; depth,
color, and crop-edge checks reject pixels that cannot be matched safely. This
avoids a second Feature 18 evaluation and does not copy the anchor eye's finished
image. The mode is disabled by default and adds one residual-reprojection
compute pass. Water, reflections, disocclusions, and other view-dependent
effects still need headset testing; disable the mode if those areas show stereo
differences.

Sequential NR keeps a separate Feature 18 history for each pass, so each pass
receives the game's motion vectors once. Gaze crop-origin motion is compensated
once per eye before the pass cascade. The second-pass contribution control
limits the added pass's result without replacing the first-pass image; values
below 100% use an extra composite pass.
