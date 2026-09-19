# Adaptive crop / reduced NR sampling correction, September 17

The 11:16–11:21 SkyrimVR session is recorded in
`C:/Users/oleks/OneDrive/Documents/My Games/Skyrim VR/SKSE/CommunityShaders.log`.
The prior search missed this redirected Documents location. Normal info logging
contains the required crop commits, NR tiers, and native feature creation times.

At 11:20:03–07, Steam screenshots show displaced copies of character geometry.
NR was below 100% and rendered crop coverage was 70%. After the user lowered the
target FPS, NR reached 100% at 11:21:07, briefly dropped, returned to 100% at
11:21:17, and crop coverage recovered from 60% to 85% by 11:21:28. The 11:21:35
screenshot is clean. The logged later deadline is 52.63 ms (19 FPS), whereas the
user recalled selecting 15 FPS; the precise selection is not necessary to the
sampling diagnosis.

## Defect and changes

`ModelResolutionCS.hlsl` sampled normalized UVs across each entire SRV. Adaptive
crop uses fixed-size backing textures and fills only the current valid rectangle.
Consequently, bilinear downsampling read outside the current crop; the reduced-NR
resolve also sampled proxy/model coordinates inconsistent with its full-resolution
original pixel. Unused pixels can retain larger crops from previous frames.
100% NR bypasses these two shader operations.

Both bilinear operations now convert normalized valid-image coordinates into
backing-texture coordinates and clamp to valid texel centers. Resolve constants
carry the current rounded model extent, matching the Feature 18 output extent.
Exact-area downsampling already uses valid pixel loads and is unchanged.

The session also shows repeated native Feature 18 creation of roughly 60–560 ms
during play, plus an initial 2.56-second creation. This explains some hitches but
does not establish the cause of every compositor timeout. Prewarming now requests
only the direction indicated by workload pressure/headroom and pauses during crop
handoffs. First-use native creation remains synchronous; no claim of hitch-free
runtime is made. Tier readiness gating and bounded residency remain in place.

## Validation

- Release DLL builds successfully; two existing MSBuild module-dependency warnings.
- C++ suite: 2,479 assertions / 178 cases passed.
- D3D11 WARP executes the actual production cs_5_0 shader against tightly sized
  textures and larger textures with poisoned unused pixels.
- Original shader: 12/16 failures; exact-area input cases already passed.
- Corrected shader: 16/16 passes, zero maximum difference in each case.
- These tests prove valid-rectangle sampling, not native Feature 18 or headset
  acceptance. The game reported devbench absent, so live acceptance is manual.

From an x64 Visual Studio developer command prompt, the standalone shader test
can be built with:

```bat
cl /std:c++20 /EHsc /W4 /WX tests\shaders\model_resolution_envelope_test.cpp d3d11.lib d3dcompiler.lib
model_resolution_envelope_test.exe features\Upscaling\Shaders\Upscaling\NeuralRendering\ModelResolutionCS.hlsl
```

## Deployment and next live test

Only `CommunityShaders.dll` and `Shaders/Upscaling/NeuralRendering/ModelResolutionCS.hlsl`
were replaced in the enabled `E:/MGO-RC3-fresh/mods/OpenNR 2.15.0` mod.
Previous files and the inspected logs are preserved in
`E:/MGO-Installer/Codex-Backups/OpenNR-crop-valid-rect-20260917-1125`.
The deployed DLL SHA-256 is
`2CF5B0AB3DF21C7C95ABD3E2D905311C57366E360C7CF207098E845889754FB0`.

Use the existing fixed MO2 launcher and the same save. Test at the usual target
FPS first, allowing crop and NR to decrease. Check startup, settled reduced tiers,
both transition directions, and the return to 100% NR. Preserve the new log before
another launch overwrites it. Full GPU/native/stereo acceptance remains pending.
