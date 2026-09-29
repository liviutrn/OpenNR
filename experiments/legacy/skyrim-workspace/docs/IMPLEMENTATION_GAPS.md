# Implementation gaps and hypotheses

These are engineering hypotheses to test, not claims of live compatibility.

| Area | Current evidence | What must be verified or changed |
| --- | --- | --- |
| Rendering API | `SkyrimVR.exe` is x64 and imports D3D11 and DXGI. | ReShade must be the actual DXGI module in the prototype process. |
| Existing upscaler | CSX 3.18 exposes NVIDIA DLSS/DLAA through its Streamline-backed path. A prototype run with the CSX native-AA/DLAA setting produced a DLSS/DLAA feature-1 create and evaluate event. | Keep the prototype on DLAA while validating the contract; the direct bridge log remains a separate D3D11 observation path. |
| Open Shaders DLSSNR fork | A local build of `YtzyFvra/skyrim-community-shaders` branch `feature/dlssnr-vr` at `091bfb4d` built successfully and loaded as `CommunityShaders.dll` 2.10.1 in an isolated derived profile. | The first cropped VR test reached Streamline `sl.dlss.dll` and an OpenComposite RT bridge, but did not load `nvngx_dlssnr.dll` before the game stalled on its loading logo. The fork's VR path still needs a successful in-world startup and neural call trace. |
| DLSS5 add-on boundary | The supplied generic add-on is a ReShade `.addon64`; it loaded with the signed `nvngx_dlssnr.dll` reference hash and captured the CSX DLSS/DLAA call on its D3D12 path. The corrected prototype priority was verified in MO2 and the saved-game path was exercised. | Native DLAA is confirmed: feature 18 evaluated successfully for 60 frames at `2496x2688`. The genuine quality-mode path reaches feature 18 with `1468x1580 -> 2496x2688`, then returns `0xBAD00005` (`InvalidParameter`) and latches to native output. |
| Streamline runtime | Prototype stages Streamline 2.13 / DLSS 310.8 over the active CSX 2.12 / DLSS 310.7 files. | If this causes instability, revert the prototype override to the known-good CSX runtime and test only the root add-on/bridge files. |
| Stereo resources | Skyrim VR's shader code documents a side-by-side stereo buffer, with the left and right eyes packed into one 2D texture. The local v1.0.18 prototype build now preserves array dimensions when the caller supplies array resources and dispatches depth/MV conversion per slice. | Check whether Skyrim/CS presents one full SBS DLSS contract or a separate per-eye contract. If the bridge sees full-width SBS resources, verify whether the neural add-on understands that layout; an eye-aware split/evaluate/repack path is still needed if the neural add-on cannot consume packed SBS. |
| Streamline contract | Current Community Shaders source tags color, depth, and motion vectors as `eTex2d` resources and makes one `slEvaluateFeature` call using full input/output extents. `EnableHooks=1` also confirmed that `sl.interposer.dll` exports can be hooked, but it did not improve this test. | The saved-game quality run confirms the remaining failure is at the upscaled feature-18 contract, not MO2 priority: the bridge sees valid color/depth/MV activity and CSX continues rendering, while RenoDX rejects only the non-native feature evaluation. The observed mismatch is `Width/Height=1448x1559` versus `1468x1580` color/depth/MV resources and input subrect. The isolated v1.0.19 build adds `feature_input=1` to create the D3D12 feature at the subrect size; a fresh VR run must verify whether that removes `0xBAD00005`. |
| Temporal data | CSX has VR camera-motion-vector and jitter handling; bridge v1.0.18 forwards the caller's parameter block. | Verify MV scale, jitter, reset events, loading-menu rebuilds, and head-motion behavior. |
| OpenComposite | The current OCU config has its own upscaling disabled; CS owns upscaling in the active profile. | Keep one upscaler enabled, confirm the active OpenXR path, and test with the headset rather than the desktop mirror alone. |
| HRTF deployment | The save-load crash was `No mhr files found in hrtf directory` from the replacement `X3DAudio1_7.dll`; the isolated physical root previously had the DLL but no `hrtf` directory. | RootBuilder Build now deploys all 14 MHR files and the matching DLL. The repaired save-load run passed; the remaining 44200-Hz warning seen in an older HRTF log is not a current crash and should be treated as a follow-up only if audio fails again. |
| VRAM/frame time | Prior MGO observations reached roughly 14.0–14.4 GiB of 16.3 GiB while vision/VR workloads were active. | Measure additional DLSS5 allocation and GPU frame time; stop if the prototype creates paging, compositor starvation, or repeatable hangs. |
| UI/control | The add-on advertises an F5 screenshot mode and a ReShade panel. | Verify overlay access in VR/desktop mirror and capture matched A/B frames without changing the active profile. |

## 2026-08-30 derived-profile test result

The isolated `DLSS5 SkyrimVR Open Shaders DLSSNR` profile was launched through
MO2 with temporary neural rendering enabled, foveated rendering enabled, and a
0.75 crop on both eyes. The OpenComposite log showed the Meta Quest 3 runtime,
DX11 stereo swap-chain creation, and an RT bridge at 2496x1344 for motion and
depth guides. The process loaded the fork and Streamline DLSS plugin, but not
`nvngx_dlssnr.dll`; no feature-18 create/evaluate or neural-output log was
captured. The desktop mirror remained at the Skyrim loading logo and the
startup water hook gave up after 60 attempts. This is a startup/path failure,
not evidence that DLSSNR rendered incorrectly or correctly.

The test process was closed by exact PID, the temporary JSON settings were
restored to the pre-test hash, and the cropped state was backed up. RootBuilder
cleanup remains a separate UI operation because the active test profile may
still have its root deployment materialized.

The likely first hard stop is not the RTX 5070 Ti: it is whether the D3D11
bridge can faithfully carry SkyrimVR's stereo render targets and motion data
through the Streamline-backed CSX call path.

## 2026-08-30 repaired-run update

After RootBuilder repaired the missing HRTF deployment, the derived profile
completed startup and a real saved-game load. The live module list contained
`CommunityShaders.dll`, `sl.dlss.dll`, and `nvngx_dlssnr.dll` from the
isolated mod, and the process remained responsive in-world for the controlled
stability window. No current-run Community Shaders log or neural success
counter was available, so this is now a loader/save-load pass only; neural
output and stereo acceptance remain unverified.
