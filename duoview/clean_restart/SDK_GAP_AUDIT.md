# Current Joey SDK compatibility audit

The smooth official DLL embeds backend `5ac7edc207866569334175e4ed8a7517971547f6`
and SDK `3cffbc82429b6165ceec2714f0f0d9ae48f55596`. The exact SDK repository is
inaccessible. This report compares that backend with public SDK
`418729025bad57b094bf6b2e2b55734454c97de6`; it does not assert equivalence.

## Source-proven gaps

`INITIAL_SOURCE_AUDIT.json` lists all 15 missing direct headers and every
backend/test file that includes them. Missing test sources are
`tests/DiscoveryValidationTests.cpp` and `tests/LayoutSafetyTests.cpp`.
The former caused CMake generation failure in run `38434181805`.

These gaps extend beyond missing filenames. The current backend calls
`FSceneViewFamily::get_layout_snapshot()` and
`FSceneViewFamily::validate_views()`, which are absent from the public
`FSceneViewFamily.hpp`. It also repeatedly calls `sdk::is_current_object()`;
the accessible SDK has no definition of that function. A header-only shim
would not restore the original discovery, validation or liveness behavior.

| Required area | Missing direct headers | Evidence-bearing callers |
| --- | --- | --- |
| Memory and render discovery | `BoundedDiscovery.hpp`, `DiscoveryMemory.hpp`, `RtmDiscovery.hpp`, `SceneDiscoveryState.hpp` | `PluginLoader.cpp`, `UObjectHook.cpp`, `FFakeStereoRenderingHook.cpp`, `SatisfactoryRuntime.cpp`, renderer entry contracts |
| Object identity and lifetime | `ObjectIdentity.hpp`, `ObjectLivenessPolicy.hpp` | `UObjectHook.hpp/.cpp`, `ProSpiCameraProbe.hpp/.cpp`, `FFakeStereoRenderingHook.cpp` |
| Reflected function arguments | `ReflectedNameCall.hpp` | `VR.cpp`, `UObjectHook.cpp` |
| Scene layouts and title-specific discovery | `FSceneViewLayoutPolicy.hpp`, `MafiaDiscovery.hpp`, `TownfallConsoleDiscovery.hpp`, `GalacticRacerRuntime.hpp`, `KingdomHearts3Runtime.hpp`, `KtjLObjectLayout.hpp`, `KtjLSceneViewLayout.hpp`, `KtjLStereoBootstrap.hpp` | Compatibility/diagnostic tests, CVar manager, render/resource hooks |

This is a lower bound. Existing headers may also have changed declarations
or behavior. The full compiler diagnostic and the exact SDK source remain
necessary before claiming a complete compatibility inventory.

## Baseline frame behavior to preserve

All three behaviors highlighted by the old v13/v14 investigation also
exist in the official smooth DLL's current source:

1. `OpenXR::update_poses()` resets Mono evidence before pose publication.
2. `note_mono_main_family()` requires prior projection evidence.
3. `D3D12Component::on_post_present()` can return before graphics-memory
   `Commit()` while Mono is waiting or blocked.

Their presence in a smooth binary does not prove they are harmless in every
callback sequence. It does show that the old source findings alone cannot
establish the cause of the mixed-backend dropouts. Do not transplant v13/v14
changes into this baseline before it is rebuilt and runtime-tested.

The original Mono mode requires DX11/DX12 plus OpenXR; it is not an OpenVR
implementation. Keep SteamVR as the OpenXR runtime for this baseline.
The official normal release at `387ccb...` has modes 0-2 only; the selected
DIBR+Mono source includes Mono ID 5. Mono keeps DIBR reconstruction inactive.

## Existing tests isolated from the missing SDK

The Windows harness builds four unchanged Joey tests: Mono DX11 WARP,
Mono DX12 WARP, STALKER 2 Native policy, and STALKER 2 Native DX12 WARP.
OpenXR/json headers use the same pins as Joey's CMake configuration.
It does not replace the full upstream compatibility suite.

`offline/MonoPolicyMain.cpp` invokes Joey's existing
`tests/MonoRenderingTests.hpp` directly. A local GCC C++23 run passed
**4,769 assertions with zero failures**, including an independent optical
matrix oracle, concurrent mode/generation publication, cancellation,
stale-frame rejection and DIBR exclusion in Mono.

Reproduce that CPU-only test from a directory containing the pinned backend:

```sh
g++ -std=c++23 -O2 -pthread -Ijoey-current/src -Ijoey-current/tests \
  OpenNR/duoview/clean_restart/offline/MonoPolicyMain.cpp -o joey-mono-policy
./joey-mono-policy
```

These checks provide no headset stability, performance or full injection
proof. Source snapshots and logs are retained in the CI evidence artifacts.

## Requirements for an SDK adaptation

- Recover each implementation from authentic public source or grounded
  binary/source evidence, documenting every difference from the exact SDK.
- Preserve existing title checks, bounded memory validation, object serial/
  registration identity, thread ownership and scene-layout publication.
- Validate the complete backend and original compatibility suite; successful
  declarations or isolated GPU tests are insufficient.
- Label the build as an SDK adaptation until equivalent behavior is proven.
- Pass the user's Native Stereo/Mono baseline stability gate before adding
  any DuoView views, compositor or gaze processing.

No SDK stubs, invented vtables, compatibility removals, binary hooks or
renderer modifications have been introduced in this restart.
