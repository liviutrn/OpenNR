# Map and lockpicking resolution investigation

Date: 2026-09-05. Scope: source/configuration investigation and proposed fixes only.

The leading hypothesis is loss of reconstructed detail in the reduced-resolution menu compositing path. The clarified symptom is an extremely low-resolution map, rather than demonstrated temporal smearing. No headset reproduction or tester DLL comparison was available. No runtime code, settings, or installed packages were changed.

## Verified context

- The selected local MO2 profile is `MGO NSFW - 4.0 BETA`, with `Open Shaders DLSSNR VR 0.5.3 OpenNR` enabled.
- The overwrite settings have `renderAtUpscaleRes=true`, `qualityMode=1`, `vrRenderScale=0.0`, and DLSS sharpening disabled. These are local saved settings, not evidence of tester settings or active runtime state.
- No SkyrimVR process was found during this investigation.
- The inspected vendor checkout has HEAD `3bd930002a96135cff5b092a7e55e11cf28bc912` and extensive existing changes. The PerfMode files and State.h have no working diff against that HEAD. This suggests the inspected menu mechanisms predate the current local 0.5.3 changes; it does not prove which code shipped in each tester DLL.

## Findings

1. **The general menu copy can enlarge low-resolution content without selecting the reconstructed output.** In `src/Features/Upscaling/PerfMode/PostIntercept.cpp:200`, `ISCopyRender_Hook` runs the engine draw, compares the destination size against the viewport, and optionally replays the draw with a larger viewport. It does not inspect or replace the source SRV. Its comments describe kMAIN copies to menu projection surfaces. The code establishes a stretch-only fallback; a capture must establish whether the affected map uses it and which source is bound.

2. **The reconstructed menu bridge has narrower delivery coverage than its interface suggests.** `MenuBridge.cpp:108` accepts kTOTAL or kMENUBG, but the sole discovered caller, `PostIntercept.cpp:37`, passes kTOTAL. Thus the bridge does not independently ensure that kMENUBG or a projected-menu surface consumes the reconstructed result. This can still be correct if the engine subsequently copies kTOTAL; that dependency is precisely what must be traced.

3. **A low-resolution scene texture deliberately remains available.** `PostIntercept.cpp:355` downsamples reconstructed testTexture into kMAIN for the exposure/bloom path. Gameplay tonemapping redirects kMAIN's SRV to testTexture, but the static-map branch skips that swap and uses the separate bridge. A downstream consumer reading kMAIN can therefore encounter reduced-resolution content. The downsample itself serves a valid purpose and should not be deleted blindly. Its execution order during the affected map frame remains unverified.

4. **Bridge freshness is not explicitly validated.** `MaybeBlitMenuBG` calls a void `Upscale()`, then blits testTexture and marks the frame complete. It does not receive a success result confirming both eyes were produced. Its single frame guard also combines reconstruction and delivery, so it cannot support multiple destinations in one frame without refactoring. `Streamline.cpp:723` selects the full display-size output correctly under PerfMode; the issue is not an obvious missing output-size override in that function.

5. **Lockpicking is not explicitly classified.** `State.h:366` uses paused/main/loading/map/stats state, without explicit lockpicking recognition. An unpaused lockpicking mod can bypass gameplay-menu protections. However, adding lockpicking to the static-backdrop category indiscriminately could break menus retaining a live world. Lockpicking's actual draw path must be checked separately.

6. **Lower-priority leads remain.** The menu bridge bypasses sharpening when redirected output must be copied, which explains a smaller crispness difference but is insufficient evidence for severe resolution loss. Map camera/depth consistency and transition history resets matter if temporal artifacts also occur. The bridge shader samples mip zero, so it does not explicitly select a low mip. A fixed 2048-square projected surface is described in source comments, but its live dimensions and involvement in the map were not measured.

## Proposed patch

Prioritize a narrow menu compositor correction, conditional on a frame trace confirming the affected route:

1. Identify the actual menu destination and source resources at the affected copy. Match known menu resource identities and menu state; do not apply a source substitution to every ISCopy operation based only on dimensions.
2. Produce a valid reconstruction once for the current menu scene, with success and freshness recorded for both eyes. Reuse it when a second menu destination needs the same image. If gameplay and menu cameras both render in one frame, distinguish those render sequences rather than using only frameCount.
3. Deliver that reconstruction through the correct menu color/tonemap stage to every destination actually consumed. Preserve the compositor's stereo/mono layout, UV mapping, blend/depth state, and viewport. A direct side-by-side HDR texture substitution into a projected or tonemapped surface is not automatically valid.
4. Separate reconstruction tracking from per-destination delivery tracking. Do not mark a destination complete when reconstruction fails. Retain a defined current-frame fallback and log the failure.
5. Add explicit lockpicking protection against gameplay NR/foveation while keeping live-world versus static-background classification separate. Reset temporal history once when camera/render context changes, if the traced route shares history across that boundary.

Only enlarge a projected-menu target if measurements demonstrate that it is the remaining resolution bottleneck. That needs a coordinated allocation, depth, viewport and projection change; enlarging only the viewport or destination cannot restore detail already lost upstream.

## Isolation and acceptance

First compare the affected setup against the same setup with `renderAtUpscaleRes=false`, restarting Skyrim VR between runs. Keep headset resolution, DLSS preset, map position and other settings fixed. This isolates the reduced engine-target mode more directly than changing several quality settings together. It may increase GPU cost. Then compare native/DLAA with explicit render-scale override disabled and another restart.

Capture the map image at kMAIN, reconstructed output, kTOTAL, kMENUBG and the actually consumed projected surface. Record source/destination identity, dimensions, active viewport, eye layout, frame/render-sequence identity, upscaler outcome and draw order. If reconstruction is sharp but the final menu is soft, correct downstream delivery. If reconstruction is already soft, inspect the source viewport/input extents and map-specific reconstruction. If both reduced-target and native paths show the same problem, inspect map assets/LOD and other menu modifications.

Acceptance requires comparable map and lockpicking captures, both eyes in-headset, open/close transitions, map pan/zoom, paused and unpaused lockpicking, and regression checks for main/loading/stats menus and live VR playroom backgrounds. Check sharpening both ways and record menu/gameplay GPU frame times. A successful build alone does not establish a visual fix.

To establish a regression, collect the exact tester archive/DLL hash and saved settings and reproduce against the previous known-good package under identical conditions. Current evidence supports a compositor defect hypothesis, not a confirmed 0.5.3 regression or a proven final patch.
