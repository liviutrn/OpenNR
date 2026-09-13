# Runtime acceptance matrix

The experiment is successful only when the rows below are evaluated separately.
A loaded add-on or a smooth desktop mirror is not evidence that neural rendering
is active in both VR eyes.

| Gate | Evidence to collect | Pass condition | Stop/fail condition |
| --- | --- | --- | --- |
| Loader | Process module list, `ReShade.log` when applicable, add-on list, game-root manifest | The selected branch's loader and runtime files load without an unexpected root wrapper; for the Open Shaders branch, `CommunityShaders.dll` and Streamline load | Loader fails, duplicate wrapper, unexpected primary-root mutation, or boot crash |
| Native contract | `ReShade.log`, `dlss5-dx11-bridge.log`, and add-on log | Add-ons load, CSX emits a DLSS/DLAA feature, and the DLSS5 add-on captures it | No producer/calls after entering a DLSS-enabled world |
| Resource contract | Bridge/add-on logs and panel | Color/depth/MV are present; dimensions, formats, subrects, and SBS/eye layout are internally consistent | Missing depth/MV, changing shape loop, unsupported format, or zero-sized guides. The corrected-priority quality run still returns `0xBAD00005` for feature 18 and is not a performance pass. |
| Neural output | RenoDX panel/log and F5 pair if available; Open Shaders process/log evidence for the fork | Native DLAA path reaches non-zero output dimensions and repeated successful feature-18 evaluations; the Open Shaders branch must load `nvngx_dlssnr.dll` and show repeated successful neural evaluations; later acceptance still requires headset visual verification | `STANDBY/FAILED`, neural DLL absent, zero successful frames, non-zero result after fallback, or persistent black/garbled output |
| Stereo/VR | Headset observation in both eyes | No eye seam, cross-eye contamination, temporal desync, head-motion instability, or compositor starvation | Any repeatable stereo artifact or unsafe latency spike |
| Performance | Matched baseline/NR samples, bridge timing, VR compositor timing, VRAM | Reportable A/B values from the same scene, refresh, render scale, and CS preset | A/B conditions changed, sample is too short, or VRAM/compositor becomes unstable |
| Rollback | `Compare-GameRootManifest.ps1`, `Validate-Prototype.ps1` | Prototype root files are gone and the active profile returns to the original hashes | Any unexplained root/profile difference |

## Required A/B sequence

1. Capture the baseline with the prototype mod disabled or `stage=0`, `mode=0`.
2. Keep headset refresh, OpenXR runtime, render scale, CS preset, location, and
   camera movement fixed.
3. Enable only the neural toggle after the game is fully in-world.
4. First use the prototype CSX override with `qualityMode=0` (DLAA/native AA), `NeuralUplift=1`, and `EnableHooks=2`; capture the successful native feature-18 path.
5. Only after native DLAA is stable, try a quality preset and treat any `0xBAD00005` as a resource-contract failure requiring investigation.
6. Repeat once with head motion and foliage, then close the game and verify
   rollback.
