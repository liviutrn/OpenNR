# DuoView Mono for STALKER 2 — Joey-First Engineering Handoff

**Date:** 2026-10-13 (Europe/Bucharest)  
**Repository:** https://github.com/liviutrn/OpenNR  
**New continuation branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-joey-first-v11  
**Working ancestor:** experiments/duoview-uevr-v08-joey-plugin  
**Status:** Re-architecture DECIDED, not yet headset-validated in the Joey-plugin form. Read this document before making new builds.

## 0. USER'S CURRENT DECISION — MOST IMPORTANT

**STOP developing the substitute public-Praydog-backend DuoView injector as the main product.** The user has verified that the original Joey UEVR works smoothly in both Native Stereo and its Mono mode in STALKER 2, whereas our public-backend DuoView Injector-5 and v09 hitch periodically even when configured for Native Stereo. The v09 build did not fix that behavior. The user explicitly does not want serial diagnostic builds or needless headset tests. The sensible baseline is the EXACT RELEASED, WORKING JOEY BINARY, UNMODIFIED, with DuoView added by a self-contained optional plugin. This is the agreed new direction.

Preserve the excellent visual behavior already demonstrated by Injector-5: real gaze-dependent high-density foveal view, independently low-resolution full-field peripheral view, one shared Mono camera, correct image to both OpenXR eyes, no gaze deadzone or forced smoothing. Do not exchange a working Joey Mono/Native baseline for a rewritten old UEVR backend merely because a substitute build compiles.

**No promise of a proven FPS gain, injection fix, or correct headset operation can be made for the plugin until demonstrated in STALKER 2.**

## 1. LATEST JOEY RELEASE — VERIFIED OCTOBER 13, 2026

Source of truth: GitHub API for joeyhodge/UEVR releases/latest and releases list checked 2026-10-13.

- Tag: **101226HELLRAISERp1** — **Hellraiser Native Fix-Fix**
- Published: **2026-10-11 17:13:12 UTC**
- Official release: https://github.com/joeyhodge/UEVR/releases/tag/101226HELLRAISERp1
- Official Mono/DIBR package: https://github.com/joeyhodge/UEVR/releases/download/101226HELLRAISERp1/DIBRMONOUEVR.zip
- Release also has UEVR.zip and separate DIBRUEVRBackend.dll / UEVRBackend.dll; **do not silently substitute one of those for the Mono package**.
- DIBRMONOUEVR.zip SHA256 from the previous v08 release-verification workflow: **d078f6e8c3c36f6877d0c6eafcb1d0344111d4f4992838c1a5ec4b91c553fade**
- Exact UEVRBackend.dll inside that Mono ZIP SHA256: **19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966**
- Previous v08 binary disassembly found embedded identifier 092826MONO+5_8_3_UEVR and commit-like strings 5ac7edc207866569334175e4ed8a7517971547f6 / 3cffbc82429b6165ceec2714f0f0d9ae48f55596. Those strings are NOT verified public Git provenance; DO NOT treat Joey's current branch HEAD as the source of that exact release.
- This was already the official binary targeted by v08 plugin. **No new Joey release needs substituting as of this handoff.** Recheck only if working after the handoff on a later date, and if updated, regenerate/revalidate exact ABI signatures rather than reusing old offsets.

The latest release's own notes describe a UE5.6.1 Hellraiser Native Fix graphics-resource readiness correction; this is one example of newer Joey safeguards not present in the older public substitute. It is NOT evidence that the release specifically fixed STALKER 2 hitches.

## 2. NON-NEGOTIABLE PROJECT GOAL

Game: STALKER 2, UE 5.5.4, DX12, PSVR2 on PC, SteamVR OpenXR runtime, RTX 5070. User operates joystick/controller and may use additional VR mods, but initial isolated adapter must avoid hook conflicts.

DuoView Mono = **two actual Unreal scene views representing one Mono camera pose**, not stereo left/right eyes:
1. View A: full Mono optical field of view, low-resolution peripheral scene.
2. View B: small gaze-centered off-axis frustum, high-resolution foveal scene.
3. Compose A + B in a single final full-FOV Mono image.
4. Send matching Mono image with calibrated OpenXR projection/subimage mapping to both headset eyes.
5. Retain 6DoF movement/head tracking, proper optical tangents, and frozen gaze/crop/settings per producer frame.
6. Preserve Joey's original **Native Stereo and Mono** unchanged when plugin disabled. The plugin may borrow Native Stereo's two engine views internally while creating Mono output; the end result must not contain stereo disparity.
7. If crop, packets or image are invalid, do not present stale or wrong-eye imagery; recover to Joey or fail closed without crashing.
8. Prefer one-pass engine scene rendering per frame (two distinct views) and one composite; no sequential Mono camera re-render.

This is **true dual-view foveated Mono** if Unreal really renders both scene views with the specified rects and their corresponding frusta, and the compositor uses those actual results. It is NOT postprocess-only foveation and NOT quad-view OpenXR submission.

## 3. WHY THE PUBLIC BACKEND PATH WAS REJECTED

Old compiled source: public praydog/UEVR commit 4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d + manually ported Joey Mono policies + DuoView.
Public SDK substitution: elliotttate/UESDK-RenderDoc 418729025bad57b094bf6b2e2b55734454c97de6.
Frontend: joeyhodge/uevr-frontend 60be4b0f9a646109fd9fdf448bacd41477234091.
- v07 Injector-5 compiled successfully: run https://github.com/liviutrn/OpenNR/actions/runs/38316421524 ; source bd74b21f46aa51c6d535680a005682e2572d6965 ; artifact DuoView-Experimental-Windows-Injector-5.
- User tested: Native-first injection -> switch to DuoView yields very good fovea, peripheral scaling, gaze and central clarity. Cold/direct Mono/DuoView startup often crashes with Unreal DX12 PresentInternal E_ABORT 0x80004004; ordinary Mono ID 5 black screen; periodic hitches in EVERY mode.
- v09 separate stability/diagnostic branch experiments/duoview-uevr-v09-stability, successful compiled run https://github.com/liviutrn/OpenNR/actions/runs/38365762543 , backend source 40c5b72abd5805645a3e63def5a8a85d748abad8; added graphics-memory-commit and Native exit-gate changes + aggregate timings. USER TESTED v09 and reports **same behavior / hitches**. It is not accepted.
- v10 frame-trace branch experiments/duoview-uevr-v10-frame-trace and run 38368336458 were abandoned after architectural decision; run reported FAILURE; do not direct user to v10. Its instrumentation and public backend are not necessary for new Joey-first work.
- Joey's original Native Stereo and Mono do not hitch for user. Source comparison confirms newer Joey has many changes missing from the old public backend (e.g. game-specific resource readiness, sync and DXGI Present safeguards). Their exact relationship to the observed hitches is UNPROVEN. We should not throw them away.

Preserve old source and builds as technical references ONLY; do not replace the user's Joey installation.

## 4. EXISTING JOEY-FIRST IMPLEMENTATION TO CONTINUE, NOT REDO

**v08 branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-uevr-v08-joey-plugin  
**v08 source commit built:** 5da78be30c11b2b209fb0596a5cb9e7fe6446f3d  
**Windows build and six tests passed:** https://github.com/liviutrn/OpenNR/actions/runs/38360520420  
**Experimental prerelease:** https://github.com/liviutrn/OpenNR/releases/tag/duoview-joey-plugin-v08-build-3  
**Critical status:** Plugin loads/compiles under Windows and WARP GPU tests passed. **Never claim that STALKER 2 accepts its hooks, that DuoView draws correctly on PSVR2, or that it improves FPS yet.** User has not tested v08 in headset.

Source map in the v11 branch (branch originated from v08):
- duoview/joey_plugin/Plugin.cpp — plug-in entrypoint, strict binary guard, native-mode check, exact inline hooks, common Mono pose, per-frame optical/gaze capture, frame-family pairing, DX12 composite and OpenXR end-frame projection adjustments.
- duoview/joey_plugin/BINARY_ADAPTER.md — reverse-engineered RVA/prologue/source operand contract for **exact** 101226HELLRAISERp1 backend. Contains address table and explicit limits.
- duoview/joey_plugin/verify_release.py — validates official binary hash and PE/hook signatures; must stay enforced.
- duoview/joey_plugin/DuoViewJoey.ini — Mode and crop/peripheral/density/feather settings loaded at plugin startup.
- duoview/joey_plugin/Install-DuoView.ps1 — profile plugin deployment and backup, use with care (moves other profile plugin files).
- duoview/joey_plugin/README.md — original v08 test instructions, NOT evidence of runtime success.
- duoview/DuoViewGeometry.hpp — geometry and pixel budget; precise per-frame off-axis crop.
- duoview/DuoViewConfig.hpp / DuoViewFrame.hpp / DuoViewState.hpp — immutable frame-state and validation.
- duoview/DuoViewD3D12.hpp / DuoViewCompositeRaster.hlsl / DuoViewShaderSource.hpp — DX12 raster compositor and shader packaging (verify exact present paths in current branch).
- duoview/PSVR2NativeGaze.hpp — Toolkit bridge, no smoothing/deadzone, short missed-sample cache.
- duoview/DuoViewProductionWarpTests.cpp / duoview/CMakeLists.txt — GPU tests.
- .github/workflows/duoview-joey-plugin.yml — official binary fetch+hash, ABI tests, six policy/WARP tests, Windows plugin build and release packaging. Currently only automatic push trigger on v08 branch; **update trigger for v11** when starting a new build.

v08 plugin Mode:
- Mode 0: diagnostics only, renderer hooks not installed, original Joey rendering remains in control.
- Mode 1: two full-size engine views from shared Mono camera (no foveal crop).
- Mode 2: fixed central foveal + low-res peripheral, atlas composite.
- Mode 3: PSVR2 gaze moved fovea + atlas composite.
Important: Modes 1-3 currently request Joey Native Stereo ID 0 as the engine's two-view producer. They are NOT Joey Mono ID 5 plus a second pass. Mode 5 is kept untouched and works when plugin disabled/Mode 0.

The plugin uses exact released backend binary API/hooks; doesn't rebuild UEVRBackend.dll. Public header version is pinned from Joey branch e30b0ee5dd480ce607abb63ef74c317bd43bd871. Full Joey backend source is public, but private joeyhodge/UESDK git submodule does not resolve for this user; avoid requiring it for compilation. The released backend is the authority for hook ABI.

## 5. REAL PERFORMANCE GOAL AND ITS VALIDATION

Original user Mono benchmark: approximately 3000x3000 internal Mono at 50 FPS. Stereo roughly 2000x2000 per-eye at 50 FPS (user estimate). These are user reports/estimates, not repeatable controlled measurements.

For fixed 3000x3000 output, full periphery at scale .20x.20 is 600x600 = 0.36 million viewport pixels. The conceptual budget is:
  scene_pixels = (3000 * crop_width * foveal_density) * (3000 * crop_height * foveal_density) + (3000 * peripheral_scale)^2.
Examples:
- Original Mono: 9.00 M pixels.
- Crop .50 x .50, density 1.5: 2250x2250 + 600x600 = 5.4225 M (~40% fewer).
- Crop .50 x .50, density 2.0: 3000x3000 + 600x600 = 9.36 M (~4% MORE).
- Crop .30 x .30, density 2.0: 1800x1800 + 600x600 = 3.60 M (60% fewer; 2x linear foveal sampling density).
- Crop .30 x .30, density 3.0: 2700x2700 + 600x600 = 7.65 M (15% fewer).
"Foveal density" is resolution-per-tangent-span, NOT a proven headset-perceived PPD and does not create information if a later upscaler/downsampler removes it.

Theoretical per-view viewport pixels are **NOT GPU time**. Expensive render work in Lumen, shadows, geometry, temporal upscalers, post effects and history buffers may retain full-resolution costs, and two-view overhead may outweigh reductions. Need confirmation through trustworthy on-GPU metrics/captures that heavy passes honor changed view rects and that no hidden second game render occurs. Target: real foveal improvement AND significantly better performance than working Joey Mono, without periodic hitches.

v08 **uses a double-wide 2W x H scene atlas**, even when actual view rectangles are smaller, and its compositor records full-size staging output plus CopyResource back to the same scene atlas. This full-target extra GPU work is a known optimization target, but **do not shrink Joey's core texture or remove required source/queue fences speculatively**. First ensure current composition works and ordering is correct, then optimize resource usage and measure.

## 6. FIRST CODE REVIEW TARGETS BEFORE USER TEST

Do not blindly declare v08 ready because six tests passed. Audit and improve:
1. **Hook ABI and startup:** Confirm exact 101226HELLRAISERp1 executable/binary hash/patch prologues; don't confuse the release tag with Joey's current source HEAD. Confirm STALKER 2 process naming, plugin loader directory, and native-mode setting/value checks. Keep Mode 0 truly non-invasive. Hooks must be installed transactionally, and failure rollback must leave Joey intact.
2. **Thread and frame lifecycle:** v08 uses a thread_local Draw snapshot and a thread_local submitted Packet which is set in frame_hook, read by the xrEndFrame hook, and reset afterward. Prove those hooks execute on the same expected thread and within packet lifetime in actual Joey, or replace with a safe explicit keyed handoff. Same goes for frame-family callbacks and per-frame gaze latching. This is a particular potential black-frame issue, not an established runtime bug.
3. **GPU resource state and timing:** v08 composes before original D3D12Component::on_frame. It assumes source state RENDER_TARGET and copies full atlas through a staging texture before Joey's OpenXR consumer. Verify the actual source resource, producer completion on the graphics queue, barriers, format, descriptor lifetime and source/output ownership. Do not introduce an independent queue or CPU-GPU fence wait if Joey already provides ordered command execution.
4. **Rendering rect effectiveness:** Check whether game-side AdjustViewRect + off-axis projection actually change GPU work on STALKER 2's Lumen, nanite, TAA/TSR/DLSS, shaders. Native stereo two-view families must not be made cross-eyed. Source and per-view history compatibility may be major challenges.
5. **OpenXR corrected Mono optics:** The final two eye projection subimages must map to one shared camera and be valid for runtime-calibrated PSVR2 per-eye fields and asymmetric projections. Do not present a full-range Mono image with standard stereo projection.
6. **Graceful fallbacks:** Unsupported formats / 2-view family mismatches should not repeatedly generate present crash, stale frame, or permanent black screen. Clearly separate disabled plugin / Mode0 from activated DuoView.
7. **Eye gaze:** Keep fixed fovea working before enabling Toolkit gaze; no artificial filter or deadzone; freeze per-frame to avoid reprojection/scene-history instability.
8. **Plugin coexistence:** Cheeky/ReShade module/layer checks exist to protect isolated validation. Don't remove them indiscriminately or ask user to permanently uninstall mods. Avoid modifying unrelated app state.
9. **Shutdown and resets:** Clean resource retire, hook unregister, runtime reload/resolution changes, XR session loss, shutdown, game/profile lifecycle without use-after-free.

There is *no reason to repair the old v07 ordinary Mono black screen in this new Joey-first architecture*: the user's original Joey Mono already works.

## 7. ENGINEERING IMPLEMENTATION STRATEGY

Start from **experiments/duoview-joey-first-v11** (created directly from v08 Joey-first branch). Keep original Joey official packaged backend byte-for-byte and its Native/Mono modes. Only build our plugin/addon and its tests. Do not patch old public Praydog sources. Avoid an expensive series of "instrument and ask user to test" revisions.

A) Inspect v08 plugin source, exact released backend headers/binary adapter and previous tests; fix concrete correctness blockers proactively.
B) Confirm with public source and static/win unit + GPU tests that the two real view rectangles/frusta are used and their frame numbers link to the composited output. Create independent tests for missing callback, changing gaze, wrong frame, resize, hardware shader compilation failure, and resource lifetime.
C) Keep the official asset's checksum validation enforced; reuse packaged Joey frontend/backend unchanged. Update CI push triggers for v11; compile Windows x64, run all six production/policy tests, verify exact DLL hashes and release integrity, package an installable ZIP.
D) Aim for a **single useful user test**: compare unchanged Joey baseline (already reported stable) to the new plugin's fixed central fovea, then optionally enable gaze if fixed fovea works. No need to retest baseline Mode 0 repeatedly. Supply simple installation, toggling and restore instructions; don't claim headset proof before test.
E) If a plugin-only implementation cannot intercept a required private renderer or pass in time, prove the exact limitation in code and adjust architecture minimally. Prefer original Joey backend + a tiny optional binary-adapter hook over rebuilding old UEVR. Binary-signature hooks must be strictly guarded for exact release.
F) Once visuals work, benchmark and reduce fixed compositor overhead, full-atlas copy, and per-view full-target work. GPU and engine render passes matter, not just pixels in viewport.

## 8. DO NOT REPEAT THESE MISTAKES

- Do NOT revert to old Praydog backend and claim it is Joey.
- Do NOT use unverified/private joeyhodge/UESDK submodule as build prerequisite; user cannot access it.
- Do NOT introduce direct startup or frame gating changes into Joey core without evidence.
- Do NOT hide DXGI Present failures with S_OK, random retries or remove necessary waits.
- Do NOT present v08's WARP test success as game/headset acceptance.
- Do NOT promise e.g. "60% more FPS" from 60% fewer viewport pixels.
- Do NOT compromise ordinary Joey Mono or Native Stereo when plugin disabled.
- Do NOT ask user to repeatedly delete their profile or perform many diagnostic tests.
- Do NOT apply arbitrary smoothing/deadzone to gaze or silently add a second scene render.
- Do NOT confuse "the latest Joey release" with 092826MONO source tag embedded in the newer binary; release tag is 101226HELLRAISERp1.

## 9. EXACT LINKS FOR THE NEXT CHAT

- **Primary continuation branch:** https://github.com/liviutrn/OpenNR/tree/experiments/duoview-joey-first-v11
- **This handoff:** https://github.com/liviutrn/OpenNR/blob/experiments/duoview-joey-first-v11/duoview/HANDOFF_JOEY_FIRST_2026-10-13.md
- **Older Joey plugin README:** https://github.com/liviutrn/OpenNR/blob/experiments/duoview-uevr-v08-joey-plugin/duoview/joey_plugin/README.md
- **Exact-release binary adapter:** https://github.com/liviutrn/OpenNR/blob/experiments/duoview-uevr-v08-joey-plugin/duoview/joey_plugin/BINARY_ADAPTER.md
- **Plugin source:** https://github.com/liviutrn/OpenNR/blob/experiments/duoview-uevr-v08-joey-plugin/duoview/joey_plugin/Plugin.cpp
- **Published experimental v08 package:** https://github.com/liviutrn/OpenNR/releases/tag/duoview-joey-plugin-v08-build-3
- **v08 successful Actions:** https://github.com/liviutrn/OpenNR/actions/runs/38360520420
- **Joey latest official release:** https://github.com/joeyhodge/UEVR/releases/tag/101226HELLRAISERp1
- **Joey original Mono ZIP:** https://github.com/joeyhodge/UEVR/releases/download/101226HELLRAISERp1/DIBRMONOUEVR.zip
- **Historical visual-proof injector:** https://github.com/liviutrn/OpenNR/actions/runs/38316421524 (hitches; NOT current foundation).

**New chat starting instruction:** "Continue actual engineering on experiments/duoview-joey-first-v11. Read duoview/HANDOFF_JOEY_FIRST_2026-10-13.md and the current v08 plugin code. Preserve exact latest released Joey Mono backend, implement and optimize DuoView as an optional plugin, fix code issues before Windows CI and a complete downloadable package. Do not ask for repetitive debugging tests or revert to the old substitute backend."

## 10. WHAT HAS AND HAS NOT BEEN DONE ON v11 YET

- New v11 branch created by assistant on 2026-10-13 from v08, NOT from hitching public backend.
- This handoff committed to v11.
- Official latest Joey release verified against GitHub API; its tag matches the existing v08 binary pin.
- Joey/plugin source and its performance architecture reviewed for this handoff.
- **No new v11 functional plugin code, CI or STALKER headset run has been completed yet.** New chat should begin implementing and compiling, not assume completion.

End of handoff.
