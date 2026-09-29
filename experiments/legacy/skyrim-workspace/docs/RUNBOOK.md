# Isolated test runbook

## Current Open Shaders package labels

For the current Open Shaders DLSSNR VR handoff, install exactly one canonical
archive through MO2. `Open Shaders DLSSNR VR x.x.x` is the public-label,
authorized internal-LAN variant and `Open Shaders DLSSNR VR x.x.x OpenNR` is
the local capture variant. Both are complete one-click MO2 packages with the
DLL/runtime payload; only the OpenNR-tagged package contains the opt-in capture
implementation. Do not add dates, `MGO Dev`, `private-dev`, fix descriptions,
or any other suffix. See [`DISTRIBUTION.md`](DISTRIBUTION.md) for the build and
package contract. Older profile names elsewhere in this runbook describe
earlier prototype runs and are retained as test history.

## Before launch

1. Close SkyrimVR and leave the active profile unchanged.
2. In MO2 select `DLSS5 SkyrimVR Prototype`.
3. Confirm `DLSS5 SkyrimVR Experimental` is enabled and the original active
   profile remains unchanged.
4. Launch SkyrimVR only through MO2. RootBuilder should supply the prototype
   `dxgi.dll`, add-ons, `nvngx_dlssnr.dll`, and ReShade configuration.

For the Open Shaders DLSSNR branch, select `DLSS5 SkyrimVR Open Shaders DLSSNR`
and confirm that `DLSS5 SkyrimVR Open Shaders DLSSNR` is enabled while
`DLSS5 SkyrimVR Experimental`, CSX, and the bridge-only prototype entries are
disabled. This branch uses the fork's native Streamline path and does not use
the older ReShade bridge/add-on stack.

Before the first launch, capture or verify the game-root baseline with
`scripts\New-GameRootManifest.ps1`. After closing the game, run
`scripts\Compare-GameRootManifest.ps1`; any added or modified root file must be
explained before returning to the normal profile.

The prototype bridge is intentionally inert on its first run:
`stage=0`, `mode=0`. This establishes the ReShade/add-on loader baseline.

## Test stages

Collect diagnostics after each stage and do not change scene, headset refresh,
render scale, or CS preset within an A/B pair.

| Stage | Bridge configuration | Purpose |
| --- | --- | --- |
| A | `stage=0`, `mode=0` | loader-only baseline; ReShade and add-on logs |
| B | `stage=1`, `mode=1` | input-resource copies only |
| C | `stage=2`, `mode=1` | input copies plus depth conversion |
| D | `stage=3`, `mode=2` | full D3D12 NGX/DLSS5 evaluation |

At stage D, use the prototype-only CSX override first: `upscaleMethod=3`,
`qualityMode=0` (DLAA/native AA), `streamlineLogLevel=2`, with
`NeuralUplift=1` and `EnableHooks=2` in the prototype `ReShade.ini`. This is
the known-good integration probe. With the prototype priority corrected, the
saved-game run reached 60 successful native feature-18 evaluations at
`2496x2688`. A quality-mode saved-game run reached the upscaled contract but
returned `0xBAD00005` and fell back to native; do not treat its performance
sample as DLSS5 super-resolution performance until that resource contract is
resolved. The current bridge probe also has `feature_input=1`, aligning feature
creation with the DLSS input subrect when the quality-mode color allocation is
padded (`1468x1580` resource versus `1448x1559` nominal render size). This is
an experiment and requires a fresh saved-game run for verification.

If the panel stays standby, use the bridge and ReShade logs to distinguish
missing D3D11 hooks, no NGX calls, failed D3D12 initialization, Streamline
hook installation, and a failed evaluate call.

For the Open Shaders branch, also record whether `CommunityShaders.dll`,
`sl.dlss.dll`, and `nvngx_dlssnr.dll` are present in the Skyrim process. A
loaded Streamline plugin without the neural DLL is only an initialization
milestone; it is not neural-rendering evidence. If the game remains on the
loading logo and startup hooks exhaust their retry budgets, stop the exact
test process and record the startup failure rather than changing the primary
MGO profile.

Use at least one static scene and one head-motion/foliage scene. Record both
eyes in the headset, not only the desktop mirror. Use the add-on's F5 matched
frame capture if it is available.

For the Open Shaders branch, the fork's in-game Upscaling panel exposes the
DLSSNR enable toggle, Natural/Balanced/Fabric Detail/Strong presets, intensity,
local tone/structure, skin structure, style, automatic mask, and UI correction.
The persistent controller and matched screenshot-pair workflow are documented
in `docs\NR_CONTROL_AND_AB.md`; they create backups and keep A/B changes
explicit.

Use `scripts\Collect-PerformanceSample.ps1 -Label baseline` and then
`-Label neural` for matched samples. The full gate definitions are in
`docs\ACCEPTANCE_MATRIX.md`.

## Rollback

Close SkyrimVR, switch MO2 back to `Mad God Overhaul - NSFW`, refresh RootBuilder,
and verify the game root no longer contains the prototype `dxgi.dll`, add-ons,
or `nvngx_dlssnr.dll`. The original profile backup is under
`backups\active-profile-baseline-20260829`.
