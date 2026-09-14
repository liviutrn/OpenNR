# OpenNR 2.15.0 UI and map follow-up

This follow-up records the source and profile checks made after the initial
2.15.0 package.

## Neural Rendering UI

The dedicated Neural Rendering page no longer draws its blue recommendation
or page-handoff paragraphs. The remaining copy is short and describes the
current routes: adaptive NR changes model resolution against a frame-time
target, adaptive Crop may reduce coverage to its floor, and eye-tracked
foveation owns crop placement.

Adaptive NR now has an optional custom application target. The persisted field
`neuralRenderingAdaptiveTargetFps` uses `0` as the compatibility value, which
keeps the existing half-refresh budget (70/72/80/90 Hz). Values from 15 through
60 select a direct FPS deadline. The menu exposes a checkbox and 15–60 FPS
slider; while custom mode is enabled, the headset-Hz buttons are disabled.
The controller clamps out-of-range values and treats a change as a normal
configuration reset so quality decisions do not carry across budgets.

## Reported map view

The active `MGO NSFW - 4.0 BETA` profile contains A Quality World Map,
NavigateVR, Local Map Upgrade VR, Map Markers for NavigateVR, and the Papyrus
Extender VR MapMenu fix. Their inspected configuration files do not define a
world-map camera distance or zoom override. NavigateVR Map Framework documents
that it selects physical map armors and does not modify the world-map camera.

The installed A Quality World Map readme explicitly describes the paper map as
2D while its markers remain 3D, so markers can appear to float or swim because
Skyrim's world-map camera is perspective rather than orthographic. The supplied
image matches that known limitation. OpenNR's map-related code only handles
static-menu backdrop compositing; it has no camera-pose or map-distance owner.
The earlier claim that OpenNR had fixed this camera behavior was too broad. No
INI or mod setting was changed based on the screenshot alone. A controlled HMD
trace is still needed if the symptom persists with the paper-map feature
disabled.

## Verification boundary

The adaptive controller unit target passes after the change. The full release
build and package were regenerated, the archive passed integrity testing, and
the installed mod was refreshed from that archive. The new menu and the map
assessment are source/profile evidence; they do not claim live headset
acceptance.
