# OpenNR 2.20.1-v06-r7

This custom OpenNR build combines DLSS Super Resolution with stereo-atlas Neural Rendering, gaze-tracked foveated crops, a coordinated GPU-frametime controller and configurable protection for dark scenes. The guide describes the features and controls present in this release.

**[Download the complete OpenNR release](https://github.com/liviutrn/OpenNR/releases/tag/opennr-2.20.1-v06-r7)** · **[Download the mod archive](https://github.com/liviutrn/OpenNR/releases/download/opennr-2.20.1-v06-r7/OpenNR-2.20.1-v06-r7.7z)**

The archive contains the OpenNR plugin, helper DLL, shaders, feature configurations, menu assets, translations, bundled SR/backend libraries and Terrain Helper asset. The NVIDIA Neural Rendering carrier **`nvngx_dlssnr.dll` is excluded**. Supply your compatible copy separately. Skyrim, SKSE and the Address Library appropriate to your game remain prerequisites.

## Rendering pipeline

The main Skyrim VR route is **game rendering → DLSS SR → one stereo-atlas NR evaluation → crop composite → UI**. Both eyes are packed into a stereo atlas for one neural evaluation. The configured atlas guard separates the eye regions; incompatible geometry or a failed NR evaluation leaves a usable non-NR path rather than substituting a different NR mode.

**Natural** visual style and **Matched Residual** reconstruction are fixed. NR uses the selected foveated region at 100% coverage; its model resolution starts at 100% per axis and changes only through the adaptive controller. Matched Residual reconstructs the neural correction against the matching non-neural input when NR runs below full crop resolution. SR render scale and NR model resolution are separate settings.

Moving gaze uses matched crop sampling, depth/motion guides and motion compensation. Compatible crop/model transitions use resident resources and residual handoffs. This preserves the underlying gaze alignment and transition handling independently of optional image shaping. Genuine layout/route changes, lost validity and failures can still reset history.

The custom controller targets **Skyrim VR through SteamVR/OpenVR**. A compatible native gaze provider is required for gaze following; the selected static crop remains usable without it. For PSVR2 on PC, use your working PSVR2 Toolkit eye-tracking setup. NR requires a compatible GPU/driver/carrier and the DLSS route. Disable Frame Generation and restart before using NR. The VR route also requires the active engine-resolution/PerfMode hook.

## Crop, periphery and edge

- **Crop presets and editor:** Full Eye; Center 90/80/75/70/60/50/40/30%; Nasal Convergence 50/60/70%; and editable region selection. Crop percentages describe width and height per eye. A 50% × 50% crop covers 25% of the rectangular eye image.
- **Gaze centre:** follows native OpenVR gaze when valid. The controller changes size relative to your selected crop while gaze retains ownership of its centre.
- **VR DLSS mode:** Default, fixed.
- **Periphery reconstruction:** Point, fixed. Periphery AA can be disabled or use motion-reprojected temporal smoothing. Its Smoothing control spans 0.05–0.50; lower values retain more history, while higher values respond faster.
- **Inner edge:** Dither, 128-pixel configured width, falloff 0.5 and noise strength 1.0, fixed. Actual blending is bounded by the crop geometry. Choose **Oval** or **Rectangle**. Oval changes the composite edge; the neural evaluation still uses its rectangular bounding region.
- **Visualize regions:** displays the crop/periphery for alignment and tuning. Disable it for normal viewing.

## Adaptive Performance

The controller reads fresh SteamVR application GPU frametime. It does not change headset refresh, compositor throttling or motion smoothing. Its policy moves one stage at a time, with coordinated crop commits, timing smoothing, holds and cooldown. The persisted selected crop stays the reference size.

| Stage | Crop: 20-point drop | Crop: 15-point drop | Crop: 10-point drop | NR resolution per axis |
|---|---:|---:|---:|---:|
| 1 — highest quality | 100% | 100% | 100% | 100% |
| 2 | 80% | 85% | 90% | 100% |
| 3 | 60% | 70% | 80% | 100% |
| 4 | 60% | 70% | 80% | 85% |
| 5 — minimum active NR | 60% | 70% | 80% | 70% |
| 6 — NR suspended | 100% | 100% | 100% | NR off |

Crop columns are relative to **your selected crop**, per axis. With Center 50% and a 20-point drop, the first three crop sizes become 50%, 40% and 30% of each eye's width/height. Stage 6 restores the selected 50% crop with NR bypassed; it does not switch SR to a full-eye crop. NR 70% means 0.70 × 0.70, or 49% of the full-resolution neural pixel count for that crop, before atlas alignment/guards.

At stages 1–4, sustained GPU time above **GPU budget** lowers quality. Recovery requires GPU time below **budget minus recovery headroom**, and the increase hold. A failed quality-growth trial can be held until sufficient extra headroom appears. Decisions pause while geometry is settling, timing is unavailable, or the route/menu/loading state is unsuitable.

**Disable NR above** applies only while at stage 5. **Re-enable NR below** applies only while at stage 6. These endpoint thresholds cannot disable NR in earlier stages. Re-enable must be lower than Disable; an invalid ordering holds the NR on/off boundary. Both boundaries use the configured holds and cooldown. Returning from stage 6 waits for the requested crop geometry to commit, resets stale NR history once and fades the neural correction back in.

| Control | Range / choices | First-run value |
|---|---|---:|
| Enable adaptive performance controller | On / Off | On |
| Controller mode | Auto / Force stage 1–6 | Auto |
| Crop reduction per step | 20 / 15 / 10 percentage points | 20 |
| GPU budget | 10–30 ms | 20 ms |
| Recovery headroom | 0.5–5 ms | 1 ms |
| Disable NR above — stage 5 only | 10–50 ms | 24 ms |
| Re-enable NR below — stage 6 only | 1–50 ms | 14 ms |
| Frametime smoothing | 0–1000 ms | 250 ms |
| Decrease hold | 0–2500 ms | 350 ms |
| Increase hold | 0–5000 ms | 1200 ms |
| Cooldown after change | 0–5000 ms | 1000 ms |
| NR transition smoothing | 0–500 ms | 150 ms |

**Force stage** holds that quality stage regardless of frametime and enables the controller if necessary. It uses the same crop/history handoffs as Auto. Close the menu, let the **Settling** indication clear, then measure. Return to **Auto** to resume decisions from the current stage with decision holds cleared. Disabling the controller uses the selected crop at full NR resolution; it does not disable NR itself. The status display shows the stage, crop target, NR resolution, NR active/suspended state, filtered GPU time, holds and cooldown.

## Native NR tuning

These controls are passed to the native neural evaluation. They are independent of image-space Result Shaping.

| Control | Range | First-run value |
|---|---:|---:|
| Intensity | 0–2 | 1.70 |
| Local Tone | 0–2 | 1.00 |
| Local Structure | 0–2 | 1.70 |
| Skin Structure | −1–2 | −1.00 |
| Automatic Mask | On / Off | On |
| UI Correction | On / Off | Off |

Use your saved tuning as the starting point. Change one control at a time; the default values above are not claims about your saved settings. Natural style is always active.

## Near-black protection

Protection acts **inside the NR region**, after optional result shaping. It reduces positive neural lifting on originally near-black pixels, using the original RGB peak to avoid treating bright saturated colors as black. Darkening edits and bright source pixels remain eligible for the normal NR result. Stronger protection can also suppress intentional neural shadow lifting.

| Control | Range | First-run value |
|---|---:|---:|
| Protection strength | 0–2 | 0 — off |
| Dark threshold | 0.001–0.25 | 0.035 |
| Positive lift onset | 0.00001–0.05 | 0.001 |

Strength 1 is the normal reference and 2 extends protection over more of the threshold range. Increasing Dark threshold includes brighter source pixels. Positive lift onset makes protection enter smoothly as neural brightening grows; larger values preserve more tiny brightening edits. The raw neural history is stored before protection, so the display correction does not feed back into that history.

**Measure NR postprocess GPU cost** requests profiling of the shared output shaping/protection/transition pass. Enable runtime profiling on the Profiling page, compare the same scene with protection 0 versus your chosen strength, and turn measurement off afterward. The measurement is combined across the eyes that ran and is not the entire NR evaluation cost. Protection uses the existing output shader; without an already active output pass, it can add one postprocess dispatch per eye. Hardware cost depends on resolution and settings.

## NR Result Shaping

**Shape the NR result** enables optional image-space adjustments to the neural correction. Native NR tuning remains separate. Neutral multipliers are 1; zero change limits leave the corresponding change uncapped.

| Control | Range | Meaning |
|---|---:|---|
| Edit strength | 0–2 | Overall neural correction; 0 removes it, 1 preserves it, 2 doubles it |
| Brightening | 0–2 | Positive brightness correction |
| Color | 0–2 | Neural chroma correction |
| Highlights | 0–2 | Correction in brighter image regions |
| Max brightening / Max darkening | 0–4 stops each | Limits on brightness changes |
| Max color change | 0–4 stops | Limit on chroma change |
| Large-scale tone | 0–2 | Broad tone/lighting correction |
| Fine detail | 0–2 | Smaller-scale correction |
| Detail radius | 0.1–8% of image height | Separation between broad tone and fine detail |

Result Shaping is off on first run. Near-black protection works independently of this toggle. The controller's underlying residual handoff and resume fade remain active when needed, including with shaping off.

## Eye-tracking controls

Native gaze is used automatically when available. **Gaze smoothing** spans 0–250 ms; zero adds no gaze filtering. **Crop movement quantization** spans 0–64 input pixels; zero turns optional movement quantization off, while internal guide/sampling-grid alignment remains active. There is no configurable gaze deadzone. **Freeze crop at selected centre** provides a fixed-crop comparison.

Diagnostics show provider/API, focus, query validity, dynamic/static crop, fallback, history-reset state, query age/cost, counters and filtered coordinates. Query age is time since the last valid application query, not headset sensor age. Invalid queries briefly hold the last valid crop before a static fallback; availability, focus, menu/loading and geometry checks can also select fallback. See [the current eye-tracking guide](https://github.com/liviutrn/OpenNR/blob/build/2.20.1-v06-r7/docs/versions/2.20.1-v06/r7/EYE_TRACKING.md).

## Shared Upscaling and settings

SR backend, quality, DLSS model preset, sharpening and supported latency/backend controls are on **Upscaling**. The backend menu offers None, TAA, AMD FSR 3.1 and NVIDIA DLSS; NR uses DLSS. SR quality choices include Native AA, Quality, Balanced, Performance and Ultra Performance. DLSS Performance is 0.5 per axis. DLSS model choices are Default, J, K, L, M, E and F; E/F are labelled deprecated, and actual preset support depends on the loaded SR runtime. **Render engine at upscaled resolution** allocates engine targets at the reduced render resolution and uses a separate display-resolution upscaler output. **VR Render Scale: Auto** follows the quality preset; an explicit scale overrides it. Quality/render-scale and foveated enablement can require a restart, as shown by the menu. DLSS sharpening is optional, with a 0–3 slider; keep it off or modest while evaluating dark-scene artifacts.

The settings page retains load/save/reset behavior. Save Settings persists your changes; live tuning alone is not a substitute for saving. The runtime validates values and fixed rendering choices at the settings boundary. Native-gaze, adaptive-performance and near-black developer commands expose corresponding status/configuration through the optional Remote Control/DevBench interface. Status and failure-reset controls help recover the NR route after a runtime error.

## Short installation and usage guide

1. Install the **OpenNR-2.20.1-v06-r7.7z** release asset as a mod in your manager. Its `SKSE`, `Shaders` and `Interface` folders belong under the game's `Data` directory. Use one active OpenNR/CommunityShaders plugin deployment and let this build win conflicts with an older build. Keep your existing working SKSE/Address Library and mod-list prerequisites.
2. Put your compatible **`nvngx_dlssnr.dll`** at **`Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll`**, or at that relative path inside the OpenNR mod folder. Keep the bundled SR/helper libraries. Without the NR carrier, NR cannot initialize; the release still supplies its normal non-NR rendering components.
3. Start SteamVR with your compatible eye-tracking provider active, then launch Skyrim through your normal SKSE/mod-manager entry point. Open the OpenNR menu with your configured menu key.
4. On Upscaling, select NVIDIA DLSS and your preferred quality/render scale. Enable the engine-resolution hook and foveated region source as needed; save and restart when the menu requests it. In the DLSS 5/Neural Rendering controls, enable NR, choose your crop preset and gaze controls, and select Auto controller mode.
5. Close the menu and let the image settle. Check that diagnostics report valid dynamic gaze and that the NR status is active or intentionally suspended. Tune near-black protection in a dark scene. For stage comparisons select Force stage 1–6, close the menu, wait for settling and measure the same scene. Return to Auto and Save Settings when finished.

## Included rendering and utility modules

These are the feature configurations shipped in this release. Their activation and compatibility follow the installed profile and supported runtime; inclusion does not mean every feature is enabled together.

| Area | Included modules |
|---|---|
| Upscaling, VR and display | Upscaling, VR, VRS, HDR Display, Post Processing, Performance Overlay, OpenNR Capture |
| Lighting and atmosphere | Cloud Relight, Cloud Shadows, Dynamic Cubemaps, Exponential Height Fog, Image Based Lighting, Interior Sun, Inverse Square Lighting, Light Limit Fix, Linear Lighting, Procedural Sun, Screen Space GI, Screen Space Shadows, Skylighting, Sky Sync, Volumetric Lighting, Volumetric Shadows |
| Materials and characters | Extended Materials, Extended Translucency, Hair Specular, Skin, Subsurface Scattering, TruePBR, Vanilla Fresnel |
| Terrain and vegetation | Foliage Lighting, Grass Collision, Grass Lighting, Grass Optimizations, Horizon Fix, LOD Blending, Terrain Blending, Terrain Helper, Terrain Shadows, Terrain Variation, Wind |
| Water and weather surfaces | Unified Water, Water Effects, Wetness Effects |
| Tools and integration | CS Editor, CS Utility, Effects11, Feature Overwrites, Remote Control, Scene Manager, Screenshot, Weather Picker |

## Verification and project identity

The release runtime comes from the successful Windows r7 build. Source/guide contracts, controller/crop paths, CPU/HLSL layouts and the actual output shader on software D3D11 passed. The release package checks all extracted runtime payloads against the verified build manifest and permits only current-documentation additions/replacements. Release hashes and its package audit are downloadable alongside the archive. Automated checks do not establish headset visual acceptance or hardware GPU timings.

OpenNR retains the `CommunityShaders.dll` runtime identity. This is a custom fork, with upstream lineage in [Open Shaders](https://github.com/alandtse/open-shaders) and [Community Shaders](https://github.com/community-shaders/skyrim-community-shaders). It is not an official upstream release. Bundled attribution and license files remain with their corresponding assets.
