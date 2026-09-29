# OpenNR conditioning diagnostics — 2026-09-07

The four post-refresh pilots contain 32 complete base frames but no renderer
conditioning channels. A diagnostic OpenNR runtime is installed for one further
eight-frame pilot; this is not evidence that the missing-channel fault is fixed.

Each accepted capture frame now carries `renderer_conditioning_diagnostics`:
stage and eye, render-target slot, texture presence and descriptor (dimensions,
format, array size, mip count, sample count, bind flags), requested source
rectangle in `[x,y,width,height]` order, rejection reason, and copy submission
result. It also records the deferred refresh check count, refresh count, last
checked host frame, and last refresh status. These show whether the refresh
path ran and whether targets were recreated before the capture.

The first accepted frame of each sequence is also logged with the prefix
`[OpenNR Conditioning]`, once per stage and eye. `copy_queued` only means the
capture API submitted a copy; committed artifacts and their validation remain
the evidence of successful readback. Diagnostics do not relax availability
checks or change source rectangles.

Build: `Dev-Fast`, OpenNR ON/ON, successful compile and link; diff whitespace
check passed. All added diagnostics and deferred fields are compiled only with
`OPENNR_CAPTURE_ENABLED`. The public build was not rebuilt or deployed; its
existing Release DLL SHA-256 remains
`EFED0CA7C8622978CD1B24A83591C32E1B76609AF85C6097FA3D05536CB08A85`.

Installed DLL:
`E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR\SKSE\Plugins\CommunityShaders.dll`

SHA-256: `8DC6606CCB6FAA68DB1790B855C0E237BF7A7A86C5628AA1D04E603ED41AB32E`.
Verified identical to the freshly linked Dev-Fast DLL. Previous installed DLL
was backed up and hash checked in
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-conditioning-diagnostics-20260907-122728`.

Skyrim was closed at installation. Capture settings are unchanged (SHA-256
`5D742DC5DBECCBD08D5870BF8AF8E5CC1801CC780B449B65C4A487714C3FEC20`): eight-frame
burst, both eyes, one 512-square crop, conditioning enabled. Relaunch through
the normal MGO route and press backslash once after entering a stable scene.
Exit before validating the fresh sequence and game log. Live game validation
of this diagnostic build remains pending. Existing captures were not changed;
no training or cloud work was started.

## Native coordinate fix — subsequent diagnostic result

The three sequences `seq-1788800925644-1`, `seq-1788800935268-2`, and
`seq-1788800944536-3` contain 24 complete base frames and 192 artifacts with
no missing files. Temporal metadata passes. All 288 conditioning checks show
existing textures and `source_rectangle_out_of_bounds`: the native stereo
G-buffers are 3328x1792, while the color stereo texture is 4992x2688.
The refresh path ran in the same host frame and reported `targets_match_main`.
This disproves the stale-size hypothesis for these samples.

The OpenNR stereo conditioning path now maps rectangle edges from the full
color texture to the native main-target dimensions before availability and
copy checks. Left/right full-eye regions become [0,0,1664,1792] and
[1664,0,1664,1792]. Replaying the mapping against all 288 recorded checks
passes bounds and eye-isolation assertions. The raw crops remain native pixels;
their recorded source/crop rectangles must be used for later spatial alignment,
not assumed pixel-identical to the larger teacher image.

Dev-Fast compilation/link and diff checks passed. Installed DLL SHA-256:
`6FEA73ACC9AB18DE731FBCDDCEA3E929207114D9A42E848EDA97C68E73F5A04B`.
Previous DLL backup:
`E:\MGO-RC3-fresh\_OpenNR_Pilot_Backups\pre-native-conditioning-rect-20260907-131201`.
Public DLL and capture settings hashes remain unchanged. Skyrim was closed
during installation. One fresh eight-frame pilot is required to prove GPU
readback, typed channel contents, and subsequent alignment; training remains
pending. Existing sample files were preserved.
