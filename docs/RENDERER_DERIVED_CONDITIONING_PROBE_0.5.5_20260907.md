# Renderer-derived conditioning probe — 2026-09-07

## Purpose

This is a capture-build preparation for testing whether auditable
renderer-owned conditionings reduce the remaining gap between the OpenNR
student and the Feature 18 teacher. The user explicitly requested activation
in the active MGO profile after a rollback backup; the active profile is now
configured for a bounded pilot. This does not claim that a renderer buffer is
semantically equivalent to the teacher's private neural history.

The existing student input contract remains RGB, depth, exact Feature 18
motion vectors, and capture context. The new channels are capture-only at this
stage. No trainer consumes them until a runtime sample proves alignment and a
separate cache schema is created.

## What is available at the renderer boundary

The source audit found real Skyrim deferred G-buffer render targets at the
Neural Rendering call boundary in
`D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d`:

| Capture stage | Renderer source | Runtime format | Interpretation |
| --- | --- | --- | --- |
| `gbuffer_albedo` | `ALBEDO` / `kINDIRECT` | `R10G10B10A2_UNORM` | Deferred base-color buffer |
| `gbuffer_normal_roughness` | `NORMALROUGHNESS` / `kRAWINDIRECT_DOWNSCALED` | `R10G10B10A2_UNORM` | Encoded normal plus roughness/glossiness |
| `gbuffer_masks` | `MASKS` / `kRAWINDIRECT_PREVIOUS` | `R11G11B10_FLOAT` | Deferred material/mask channels, not a semantic ID map |
| `gbuffer_masks2` | `MASKS2` / `kRAWINDIRECT_PREVIOUS_DOWNSCALED` | `R16_UNORM` | Includes vertex-AO data in the current shader contract |
| `gbuffer_specular` | `SPECULAR` / `kINDIRECT_DOWNSCALED` | `R11G11B10_FLOAT` | Deferred specular contribution/input buffer |
| `gbuffer_reflectance` | `REFLECTANCE` / `kRAWINDIRECT` | `R11G11B10_FLOAT` | Deferred reflectance buffer |

The probe captures each available resource as a raw typed texture using the
same per-eye source rectangle as the Feature 18 input. Each sequence metadata
file records the requested flag, the available channels, source/alignment
claims, and explicit non-availability of unsupported signals.

## What is not exposed

- There is no single verified lighting-only/illumination tensor at this call
  boundary. The final composite is not relabeled as illumination.
- There is no renderer material/object semantic-ID buffer in the current
  capture path. The mask buffers must not be treated as semantic labels.
- The exact carried teacher history is opaque. The capture records the exact
  initial reset state and per-frame reset metadata, but not the internal NGX
  history tensor.

These limitations are recorded in `sequence.json` rather than hidden behind
approximate channels. The initial model experiment therefore remains RGB plus
native guides; G-buffer tensors are a future representation experiment only.

## Build and isolation state

The source changes are in:

- `src\Features\OpenNRCapture.h`
- `src\Features\OpenNRCapture.cpp`
- `src\Features\Upscaling\NeuralRendering\Renderer.cpp`

The repository's warm `Dev-Fast` build completed successfully on 2026-09-07.
The isolated DLL is:

`D:\.CODEX_Projects\OpenNR-VR\out\renderer_conditioning_probe_0.5.5_20260907\CommunityShaders.dll`

A ready-to-copy MO2 payload is also present at:

`D:\.CODEX_Projects\OpenNR-VR\out\renderer_conditioning_probe_0.5.5_20260907\MO2_mod\SKSE\Plugins\CommunityShaders.dll`

Its SHA-256 is
`A50B62C955ACE36AC52800921646F53B8500BE6CDBEB7028F6DFB3362EF4D817`.
This payload is also installed as the active MGO `CommunityShaders.dll` owner
after a byte-verified rollback backup. The installed DLL SHA-256 is the same
`A50B62C955ACE36AC52800921646F53B8500BE6CDBEB7028F6DFB3362EF4D817`.

The active production DLL remains:

`E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.5 OpenNR\SKSE\Plugins\CommunityShaders.dll`

The previous production DLL SHA-256 was
`751401C26DF6B9FCD7F6F3DD906EE6D57ED69D6F3C6EE6305D1C445C49E3FFD4` and is
preserved at
`G:\OpenNR_Capture_Setup_Backups\active-renderer-conditioning-pilot-0.5.5-20260907-0210\CommunityShaders.dll`.
The active profile now has renderer conditionings enabled for the bounded pilot
and writes to
`C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`.
The active `SettingsUser.json` SHA-256 is
`F4938BCB975120ECC627A42BDA3EA69C3F3AEE9837EFED6C51203469A2BA6234`.

## Safe pilot recipe

The active MGO profile is already prepared for the pilot. Do not add a second
`CommunityShaders.dll` owner. The rollback backup is retained on G:, and the
pilot output is separate from all established training caches.

1. On the next launch, leave the active profile as-is until Skyrim is at a
   stable scene. `enable_capture=true` enables the feature; use the configured
   capture hotkeys to request the finite burst.
2. Keep the first pilot bounded to 8 frames, one center crop, both eyes, raw
   tensors only, and no previews/full-frame copies.
3. Collect three short bursts in materially different scenes: a static
   material/shadow transition, slow lateral or rotational motion, and a
   high-effect fast/mixed-motion case. Let the game settle before each burst
   so the first frame's `[true, true]` reset is meaningful.
4. Validate the resulting `frames.jsonl` and require per-frame
   `renderer_conditionings_requested=true` plus a non-empty
   `renderer_conditionings_available` list before considering the probe useful.
5. Confirm that every advertised stage has the same sequence/frame/eye/crop
   coverage and source rectangle as the corresponding input/teacher row. Any
   missing stage, stale G-buffer, invalid rectangle, or queue drop quarantines
   the sequence from representation training.

The six extra channels can make a full 64-frame, four-crop burst roughly 2.5x
the current raw stage volume. That is why the pilot is deliberately 8 frames
and one crop. The current C: free-space reading was approximately 68.9 GiB;
do not enable the extra channels in the existing 64-frame output root without
rechecking free space.

## Mixture training prepared but not started

The capacity trainer now supports:

```text
--new-temporal-cache <new-cache>
--new-temporal-prob <0..1>
```

`--cache` is treated as the old domain, while the optional second strict cache
is sampled independently. Validation reports `old_domain`, `new_domain`, and
pixel-weighted `merged` results at every evaluation. It also records separate
best old/new MAEs in the checkpoint metadata. The frozen test split is never
used for selection.

The prepared run recipe is:

```text
parent: E:\OpenNR_Training\fullres_aux_oversample_v65_probe_0.5.5_20260906\best_mae.pt
old temporal cache: E:\OpenNR_TrainingInputs\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906
new temporal cache: E:\OpenNR_RawCropCache_VariedHighEffectTemporalClean_0.5.5_20260907
new temporal probability: 0.35
spatial cache: C:\OpenNR_Cache_VariedHighEffectSpatialAllCrops_0.5.5_20260907
spatial probability: 0.25
output: E:\OpenNR_Training\high_effect_mixture_v75_probe_0.5.5_20260907
```

This gives the new high-effect domain substantially more exposure than its
approximately 9% share under naive stream-uniform mixing while preserving the
old-domain validation guard. Training and GPU evaluation are intentionally
paused in this state because another Codex task is using the GPU.

## Storage and provenance

The old cache was copied from the verified cold archive
`G:\OpenNR_ColdStorage\OpenNR_RawCropCache_StrictAllCohortsNextGrid_0.5.5_20260906`
to the E: staging path above. All 8 files and 65.500 GiB were copied with zero
robocopy mismatches, then size and SHA-256 verified file by file. The G: copy
remains intact as the cold/archive source. No raw capture, selected checkpoint,
or experiment output was deleted.

## Public DLSS 5 research check

The current public NVIDIA description reinforces the capture direction: DLSS 5
is described as a renderer-grounded model conditioned on the current rendered
frame, engine motion vectors, carried temporal state, and artistic-direction
values, with renderer-derived scene-attribute consistency supervision during
training. That is consistent with treating the G-buffers as hypotheses to
audit, not as a substitute for the opaque teacher history or unavailable
artistic-direction values. See the [NVIDIA ADLR DLSS 5 description](https://research.nvidia.com/labs/adlr/DLSS5/)
and [NVIDIA's product description](https://www.nvidia.com/en-sg/geforce/news/dlss5-breakthrough-in-visual-fidelity-for-games/).

Public community projects now describe DLL/kernel extraction and wrapper or
bridge routes, but their claims are not an auditable substitute for our
Feature 18 capture contract. We keep those leads research-only and will not
install or execute untrusted leaked proxy binaries on the known-good MGO
system. The [NVIDIA DLSS SDK license](https://github.com/NVIDIA/DLSS/blob/main/LICENSE.txt)
also contains restrictions on reverse engineering, circumvention, and
redistribution; any future investigation must stay within the user's rights
and the applicable terms.

## Current handoff state — 2026-09-07

The active isolated profile has the renderer-conditioning capture flags enabled
and the bounded pilot configured for eight-frame, one-crop, both-eye sequences.
The output root is
`C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`; it was rechecked
after the local Arm-C follow-up pilots and contains no files yet.

This probe is therefore still a capture prerequisite, not a training result.
The model-side width, depth, scalar calibration, effect-frequency, identity,
conservative-continuation, and style-modulation branches have not produced a
candidate that improves both validation cohorts. Do not rent cloud capacity or
build a conditioning cache until a real capture passes the strict renderer
conditioning gate described above.

## Runtime repair and build boundary — 2026-09-07

The first renderer-conditioning pilot was structurally valid but semantically
empty: all seven eight-frame sequences requested renderer conditionings while
recording none. Those sequences were moved, with their files and byte sizes
preserved, to
`C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907_discarded_no_renderer_conditionings_20260907`.
They are quarantined rather than permanently deleted.

The local OpenNR runtime was rebuilt so the six deferred G-buffer targets are
checked against the engine's current main-target dimensions and recreated before
the deferred geometry pass when the engine has resized or recreated its targets.
The renderer-conditioning definitions and call sites, the per-frame G-buffer
refresh, and the OpenNR capture paths are compiled only when
`OPENNR_CAPTURE_ENABLED` is defined. The live OpenNR mod uses the fresh
`Dev-Fast` root-linked DLL; its SHA-256 is
`81A9C4D34032638AEF912A8FE3C7F8A852DF2F6487C06C5099BE6CA97EBC97E8`.

The public test build is a separate artifact and must remain OpenNR-free:

- `ALL-VS2022` is configured with `BUILD_OPENNR_CAPTURE=OFF` and
  `AIO_INCLUDE_OPENNR_CAPTURE=OFF`.
- The generated public target excludes both `OpenNRCapture.cpp` and
  `OpenNRCapture.h`, has no capture call sites or `OPENNR_CAPTURE_ENABLED`
  definition, and has no OpenNR references in `CommunityShaders.vcxproj`.
- The canonical public `Release` and `aio` DLLs contain no OpenNR strings. Both
  are the same clean build (`SHA-256`:
  `EFED0CA7C8622978CD1B24A83591C32E1B76609AF85C6097FA3D05536CB08A85`).
  The public DLL is kept at `build\ALL-VS2022\Release\CommunityShaders.dll`
  and is never copied into the OpenNR mod.
- CMake filters the OpenNR implementation, feature version/configuration, and
  shader path out of public AIO staging and the final archive. The verified
  archive is
  `dist\CommunityShaders_AIO-2026-09-07T15-53Z.7z` (`SHA-256`:
  `6271B7CBF50F220D82C7447C44D25F86C4A87F16264707AF7D95248896B67D49`),
  with no OpenNR entries.
- Historical generated public-build residue, including the old manual-stage
  and zip output trees, was moved recoverably under
  `D:\.CODEX_Projects\DLSS_5_SKYRIM\vendor\open-shaders-dlssnr-vr-091bfb4d\_quarantine_public_build_stale_20260907`.
  The source tree intentionally retains OpenNR sources for the separate
  OpenNR build; that source presence does not make them part of the public
  target or package.

The active OpenNR DLL matches the root `Dev-Fast` build and the isolated mod;
the MO2 overwrite capture settings were left unchanged. The live SkyrimVR
process started after the repaired DLL was installed, so the fix is loaded and
no second relaunch is needed for this boundary fix. Four new pilot sequence
directories appeared in the active capture root while testing; this boundary
audit did not validate, discard, or otherwise modify them. Close the game before
validating those sequences. Runtime success is not claimed until a sequence
produces a non-empty `renderer_conditionings_available` list and the
corresponding six `gbuffer_*.raw.bin` files.
