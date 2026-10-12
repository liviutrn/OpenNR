# DuoView public SDK compilation / independent audit

## Status (2026-10-12 UTC)

Branch: `experiments/duoview-uevr-v06-publicsdk`.
Target Joey UEVR commit: `db6729dd9f5745705b1cdec2ec6f51bdc9570983`.
Public SDK candidate: `elliotttate/UESDK-RenderDoc@418729025bad57b094bf6b2e2b55734454c97de6`.

### Verified Windows CI facts

- First configuration failed due to an SDK-private unit test source:
  `dependencies/submodules/UESDK/tests/DiscoveryValidationTests.cpp`.
- Disabled `UEVR_BUILD_COMPATIBILITY_TESTS` **only in the full public-SDK feasibility probe**.
  Existing standalone regression tests remain enabled and all pass separately.
- Full `uevr` project **successfully configured** using public GitHub checkout and
  Visual Studio 2022 (Windows hosted runner).
- First real C++ compile failed, **not** on DuoView HLSL or the Stage-2 patch
  but on UESDK header ABI declarations required by Joey:
  `IStereoRenderTargetManager_58_Transitional` (missing parent class; cascading override errors)
  and `sdk::FSceneViewInitOptionsUE50To53` (missing type; cascading std::unordered_map errors).
- Actual compiled UEVR binary or a STALKER 2 runtime test is **not available**.
- CI run [38309743472](https://github.com/liviutrn/OpenNR/actions/runs/38309743472)
  contains configuration logs and compile error artifact; tests in followup runs verify
  subsequent standalone regression fixes.

### Static header audit

`duoview/audit_public_sdk.py` checks 66 distinct directly included SDK headers.
56 exist in the public SDK candidate. Ten unavailable:

1. `BoundedDiscovery.hpp`
2. `DiscoveryMemory.hpp`
3. `FSceneViewLayoutPolicy.hpp`
4. `KtjLObjectLayout.hpp`
5. `KtjLSceneViewLayout.hpp`
6. `KtjLStereoBootstrap.hpp`
7. `MafiaDiscovery.hpp`
8. `ObjectLivenessPolicy.hpp`
9. `RtmDiscovery.hpp`
10. `SceneDiscoveryState.hpp`

**This inventory is not exhaustive:** existing public SDK headers omit additional
types, even though their filenames are present. We must avoid falsely treating
the 56/66 ratio as compile compatibility.

### Safety bug identified during independent source review

`DuoViewFrame.hpp::FrameCoordinator::begin` initially rejected older frame
numbers in the same generation but failed to reject lower *generations*.
That could allow late callbacks from an obsolete Mono/DuoView rendering method
to start another packet after a transition. Fixed by rejecting
`new.generation < last_begin.generation`. A frame-policy test asserts the
lower-generation rejection. Linux standalone regressions compile under
`-Wall -Wextra -Werror -pedantic` and pass, including geometry, gaze,
frame/fence and config snapshot.

### Required next work

1. Replace missing SDK declarations based on **verified compatible public implementations**
   or port the Mono backend changes onto a fully buildable public UEVR
   revision. Do not invent Unreal virtual-function layouts or
   `FSceneViewInitOptions` data offsets. STALKER 2 VR can crash or silently
   corrupt pointers if those definitions are incorrect.
2. Get through a complete backend compile **before** integrating the
   UEVR DX12 compositor in `D3D12Component.cpp`.
3. Once the backend compiles, wire the two UE view completions and latched
   gaze, raster shader + BGRA8 output texture, GPU-fence retirement and
   single-width-to-double-wide copy. Current patch is still an
   **uncomposited atlas diagnostic**, not a headset-ready DuoView mode.
4. Validate headset projection/view ordering and Unreal performance in
   STALKER 2 DX12 using PSVR2.

The working Joey Mono installation, OpenNR `main` and private Epic/Joey
repositories are not modified.
