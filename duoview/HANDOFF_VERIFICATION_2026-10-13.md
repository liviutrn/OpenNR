# DuoView Mono UEVR — verification handoff

**Prepared:** 2026-10-13 (Europe/Bucharest)  
**Project:** `liviutrn/OpenNR`  
**Experimental branch:** `experiments/duoview-uevr-v07-stalker-publicsdk`  
**Status:** First complete Windows injector build **succeeded**. Actual STALKER 2 + PSVR2 rendering **has not been tested**. This is not a stable release.

## 1. The decisive proof: complete successful build

- **GitHub Actions run:** https://github.com/liviutrn/OpenNR/actions/runs/38316421524
- **Workflow:** `DuoView public backend Windows injector` — `.github/workflows/duoview-public-backend.yml`
- **Run number:** 5
- **Run conclusion:** `completed / success`; its `windows-injector` job completed successfully.
- **Exact compiled source commit:** `bd74b21f46aa51c6d535680a005682e2572d6965`
- **Source view:** https://github.com/liviutrn/OpenNR/tree/bd74b21f46aa51c6d535680a005682e2572d6965
- **Runner:** GitHub-hosted Windows 2022; the backend uses MSVC and Visual Studio 2022; injector targets .NET 6 Windows.
- **Confirmed pipeline:** accessible upstream checkout → strict source-patch application → portable policy and production DX12 WARP test suite → full CMake configuration → build `uevr`, `vr-plugin-nullifier` and `LuaVR` → frontend rendering-mode ID test → build/publish Windows injector → upload installable artifact and diagnostics.
- **Compiler log check:** `build.log` and `configure.log` have no C++ compiler errors or linker errors. There are nonfatal upstream/dependency warnings.

**IMPORTANT:** This build was already running when the 2026-10-13 takeover began. The takeover monitored it through success; it did **not** originate this run or itself repair the earlier backend linker failure. The compile fix was present in commit `bd74b21...` from the prior implementation session.

## 2. What was delivered — byte-verifiable artifacts

### A. Installable experimental injector

- **GitHub artifact name:** `DuoView-Experimental-Windows-Injector-5`
- **GitHub artifact ID:** `11777567376`
- **Download from the run's Artifacts section:** https://github.com/liviutrn/OpenNR/actions/runs/38316421524
- **ZIP file name:** `DuoView-Experimental-Windows-Injector-5.zip`
- **ZIP size:** 106,305,144 bytes (approximately 101.38 MiB)
- **ZIP SHA-256:** `bf48e0ba7644182717e214d5acc5b14b6934978174777a643d9edbf7c95d9cdc`
- **ZIP CRC check:** passed for all 17 entries; no damaged entry reported.
- **Packaged BUILD_SOURCE.txt:** `Source: https://github.com/liviutrn/OpenNR/tree/bd74b21f46aa51c6d535680a005682e2572d6965`

Notable entries independently inspected in the ZIP:

| File | Uncompressed size | SHA-256 |
|---|---:|---|
| `UEVRBackend.dll` | 11,817,472 bytes | `3b5f2677d3d2f25e6ad0739215ef9d61671db375e4d915a781176a5ad003917c` |
| `UEVRInjector.exe` | 156,707,116 bytes | `1472acdfcbe37d2a554335ca8c0a458891674372e45fd330b49938e4aac794bd` |
| `LuaVR.dll` | 5,222,400 bytes | `5cb3ccbb8c51ae607ed71e6795acada34be070526e43508fc86ee94c634e7108` |
| `UEVRPluginNullifier.dll` | 1,045,504 bytes | `fcb951ad51322e00aa2b7e87e702bf0bdf4e02bb4807a381fb93da314ee80d6f` |

The DLL and EXE were identified as **x64 PE binaries** (machine `0x8664`). Other entries include dependencies, PDBs, `TESTING.md` and `UEVR-LICENSE.txt`. The presence of binaries does not prove that injection or rendering succeeds on a gaming PC.

### B. Build logs and applied patches

- **GitHub artifact name:** `DuoView-public-backend-build-logs-5`
- **Artifact ID:** `11777267912`
- **ZIP file:** `DuoView-public-backend-build-logs-5.zip`
- **ZIP size:** 24,183 bytes
- **SHA-256:** `61197f9fb8e1b5abe746e896b3d52d450e57504d1a6de976ae311062fbfe79df`
- **Contents:** `configure.log`, `build.log`, `applied-source.patch`, `applied-sdk.patch`; ZIP integrity check passed.

**Artifact retention:** The Actions workflow requests 30-day retention. The files are accessible at the time of writing but are not permanent releases; save a copy if a future review is needed.

## 3. Engineering implementation inherited from the earlier session

The established design is **dual-view monoscopic foveated rendering**, not stereoscopic quad views:

1. Original Mono is preserved as separate rendering method **5**; DuoView Mono is method **6**. Native stereo remains selectable.
2. Two Unreal Engine scene views use the same 6DoF camera pose (position and rotation), with **different render resolutions and projection rectangles**.
3. Peripheral view: full monoscopic FOV rendered at a lower scale. Foveal view: higher-density cropped projection centered on the latched gaze point.
4. The active source stores one immutable frame configuration covering view rectangles, camera and gaze; it refuses to composite an incomplete or mismatched frame packet.
5. A DX12 raster compositor samples both regions from a two-view atlas, blends them into a single full-FOV mono image, then duplicates this output to both halves of the OpenXR double-wide swapchain.
6. The PSVR2 Toolkit CAPI bridge provides a combined gaze sample with up to 50 ms sample freshness, no configured spatial smoothing or deadzone. It falls back to fixed center on unavailable/invalid gaze. Its *real* alignment and tracking behavior are not yet established in the headset.
7. The controls exposed in UEVR include crop width/height, peripheral scale, foveal density, feather, gaze on/off, debug border and which Unreal view supplies the fovea.

This public-baseline build is **not a byte-for-byte reproduction of Joey's latest private backend**. In particular, inaccessible private UESDK functionality and DIBR options are not presented as available in this build.

### Exact pinned sources

| Component | Source and commit |
|---|---|
| Public UEVR | `praydog/UEVR` — `4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d` |
| Public UESDK | `elliotttate/UESDK-RenderDoc` — `418729025bad57b094bf6b2e2b55734454c97de6` |
| Injector frontend | `joeyhodge/uevr-frontend` — `60be4b0f9a646109fd9fdf448bacd41477234091` |
| Joey Mono reference | `joeyhodge/UEVR` — `becc96692839f0087ccef238f03af618051fb765` and `db6729dd9f5745705b1cdec2ec6f51bdc9570983` |

### Main source files to inspect in the experimental branch

- `duoview/apply_public_mono.py` and `duoview/public_mono.patch` — port of original Mono and selection policy.
- `duoview/apply_public_duoview.py` — integrates method 6 into the public backend, UE callbacks, UI, Toolkit gaze and DX12 copy path.
- `duoview/DuoViewGeometry.hpp` — pixel layouts, off-axis foveal projection and blend geometry.
- `duoview/DuoViewConfig.hpp`, `DuoViewFrame.hpp`, `DuoViewState.hpp` — frame-scoped settings and packet synchronization.
- `duoview/DuoViewGaze.hpp`, `PSVR2NativeGaze.hpp` — ray-to-UV mapping and native gaze acquisition.
- `duoview/DuoViewD3D12.hpp`, `DuoViewCompositeRaster.hlsl`, `DuoViewMonoCopyD3D12.hpp` — production compositor, raster shader and double-wide copy.
- `duoview/apply_frontend.py` — updates injector to offer ID 6.
- `.github/workflows/duoview-public-backend.yml` — complete repeatable public Windows build and artifact upload.
- `duoview/UEVR_INTEGRATION.md`, `duoview/WORK_LOG.md`, `duoview/TESTING.md` — integration design, historical engineering record, user test protocol.

## 4. Historical failed builds and resolved compiler blocker

- [Run 38310862046](https://github.com/liviutrn/OpenNR/actions/runs/38310862046) — the *old* Joey/private-SDK-dependent v07 probe failed. The public UESDK did not provide all private declarations and discovery APIs; suppressing isolated declarations was not an adequate general fix.
- The previous development session switched to pinned public UEVR and public UESDK, carried forward the Mono algorithm and integrated the DuoView components.
- [Run 38314928535](https://github.com/liviutrn/OpenNR/actions/runs/38314928535) — portable/WARP tests passed, full C++ translation-unit compilation completed, **linking failed** because `FSceneViewFamily` was forward-declared as `struct` while the actual definition used `class`, changing the MSVC decorated symbol.
- The preceding development session corrected that declaration without inventing SDK memory structures.
- [Run 38316421524](https://github.com/liviutrn/OpenNR/actions/runs/38316421524) — **full build and package succeeded**.

## 5. Exactly what the takeover session itself changed

The 2026-10-13 takeover did **not** rewrite the renderer or make new functional source-code revisions. It:

1. Read the original handoff and current engineering/integration documents.
2. Checked the old failed Actions run, more recent branch runs and their statuses.
3. Traced the newer Windows job through portable/WARP tests, compilation, frontend publishing and artifact upload.
4. Inspected key public Mono, DuoView, frame state, CAPI gaze, shader, compositor, source-patch and frontend files for high-level integration consistency and residual risk.
5. Downloaded and independently inspected both ZIP artifacts, including ZIP checksums, expected binaries and build provenance.
6. Committed an updated successful-build record to `duoview/WORK_LOG.md` in commit `36c8bc94ac571d25923575e071cbb608e92db17a`.
7. Updated the outdated first section of `duoview/HANDOFF_CHATGPT_WORK.md` in commit `8bc5faaceb8df918e1a55131130613a155ab99e4`.
8. Prepared this separate verification handoff. No changes were made to `main`.

The compiled source commit remains `bd74b21...`. The documentation commits above occurred **after** that build and do not constitute newly compiled source changes. No GitHub Release was created.

**Independent reviewer disclosure:** The inherited `WORK_LOG.md` states that earlier development received GPT-6.1 SOL Medium review and records the issues it identified. The takeover session **did not invoke a separate GPT reviewer**, and no new independently audited report should be inferred.

## 6. Verification and proof limits

| Claim | Result | Basis |
|---|---|---|
| Strict source patches apply | **Pass** | Windows Actions job |
| Portable policy/state tests | **Pass** | Windows Actions job |
| Production DX12 compositor and duplicated eye output on WARP | **Pass** | Windows Actions job, software GPU |
| Complete UEVR backend DLL compiled and linked | **Pass** | Windows MSVC build |
| Matching injector published and zipped | **Pass** | Windows Actions + independently inspected ZIP |
| Injects and operates in STALKER 2 | **Not tested** | Requires user/game environment |
| Two actual UE5 game views produce the intended rectangles with matching camera pose | **Not tested in game** | Requires logging/RenderDoc/UE GPU capture |
| PSVR2 Toolkit gaze tracks accurately in OpenXR | **Not tested in headset** | Requires real device |
| Correct eye images, no flicker/stale frames, good TSR/Lumen/exposure continuity | **Not tested in headset** | Requires real gameplay |
| Higher PPD or measured GPU-time/FPS improvement | **Not measured** | Needs a controlled STALKER 2 benchmark |

A successful Windows build and WARP tests do **not** establish that the game creates two distinct shading passes correctly, avoids temporal-history contamination, or achieves an FPS increase. Screen-space exposure, shading/Lumen, actual resource formats, command ordering, projection/gaze coordinate mapping, and same-frame tokens remain the priority checks.

## 7. Recommended first real STALKER 2 / PSVR2 acceptance test

1. Keep your proven Joey UEVR installation backed up. Extract this experimental package into a separate directory.
2. Launch SteamVR, PSVR2 Toolkit and STALKER 2 with the **DX12/OpenXR** backend.
3. First choose **Mono (Experimental)** (method 5). Confirm correct image, 6DoF rotational and positional head tracking, and no startup crashes.
4. Choose **DuoView Mono (Experimental)** (method 6), initially **eye tracking OFF**, **debug border ON**, crop width/height **0.50 / 0.50**, peripheral scale **0.20**, foveal density **1.00**.
5. Check whether there is a sharp cropped center blended into a coarser full-FOV periphery, both eyes receiving the same Mono content, and no black/uninitialized atlas region.
6. Enable gaze and check independent fast eye movements, head rotation, head translation, stale sample handling, and frustum alignment. There should be no intentional gaze smoothing or deadzone.
7. Try a **0.30 × 0.30** crop and change fovea source view 0/1. Compare image quality and FPS with original Mono in the same stationary game scene.
8. Record actual headset resolution, GPU/CPU frametime, VR overlay, gaze status, any seams/flicker/misprojection, and ideally a GPU capture with UE viewport rect sizes.
9. If it fails, switch back to original Mono and retain `UEVR.log`, exact build source, in-headset screenshot/description, settings and game state. Do not interpret a blank frame as a validated result.

## 8. Independent verification commands

On Windows (PowerShell), in the download folder:

```powershell
Get-FileHash .\DuoView-Experimental-Windows-Injector-5.zip -Algorithm SHA256
Expand-Archive .\DuoView-Experimental-Windows-Injector-5.zip -DestinationPath .\DuoView-Test
Get-FileHash .\DuoView-Test\UEVRBackend.dll -Algorithm SHA256
Get-FileHash .\DuoView-Test\UEVRInjector.exe -Algorithm SHA256
Get-Content .\DuoView-Test\BUILD_SOURCE.txt
```

Verify the outputs match the hashes and exact source commit in §2. To audit the complete build, open the named Actions run, expand `windows-injector`, inspect its individual test, DLL build, frontend publishing and artifact upload steps, and compare `applied-source.patch` / `applied-sdk.patch` with the source-patch scripts at the compiled commit.

**Next engineering action after headset evidence:** fix any real game integration issue at the production UE hook/DX12/eye tracking layer, then push a targeted revision to the *same experimental branch*, wait for a **new complete successful Windows build**, test its new artifact, and record precise measurements. Preserve the original Mono selection and OpenNR `main`.