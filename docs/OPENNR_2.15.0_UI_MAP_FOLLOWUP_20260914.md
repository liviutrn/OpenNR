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
Skyrim's world-map camera is perspective rather than orthographic. OpenNR's
map-related code only handles static-menu backdrop compositing; it has no
camera-pose or map-distance owner. The earlier claim that OpenNR had fixed this
camera behavior was too broad.

## Profile-scoped camera correction

On 2026-09-14 the active MO2 profile was backed up before each profile edit.
The latest recovery copy is
`C:\OpenNR\ConsolidationBackups\20260914\map-camera-fix-20260914-144232-before-height-calibration`.
The profile now contains the following targeted settings:

```ini
[MapMenu]
fMapWorldHeightAdjustmentForce=0

[VRUI]
fVrMapMenuScaleStart=1.0000
fVrMapMenuScale=1.0000
fVrMapMenuModelScale=1.0000
fVrMapMenuHeightOffset=20000.0000
```

`fMapWorldHeightAdjustmentForce=0` holds terrain-following height while panning;
it does not set the initial viewpoint. The earlier `1.25` scale values were an
unverified experiment and have been returned to the documented vanilla `1.0`
defaults. `fVrMapMenuHeightOffset=20000.0000` is a reversible profile
calibration against the engine's implicit `40000.0000` default and is intended
to bring the initial VR map view closer to the terrain. It is not a confirmed
engine-level fix until it is checked in the headset. No VRIK calibration,
world-scale setting, map plugin, or OpenNR runtime code was changed. Skyrim VR
must be restarted before it reads the INI; the result still needs a live HMD
check for initial altitude, panning, both eyes, and marker placement.

## Verification boundary

The adaptive controller unit target passes after the change. The full release
build and package were regenerated, the archive passed integrity testing, and
the installed mod was refreshed from that archive. The new menu and the map
assessment are source/profile evidence; they do not claim live headset
acceptance.
