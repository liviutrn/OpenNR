# DuoView v13 — restore proven Injector-5 rendering path

## What this build actually is
This Windows injector is rebuilt from the exact public UEVR and SDK pins used
in the **user-tested DuoView-Experimental-Windows-Injector-5**:
- Source snapshot: `bd74b21f46aa51c6d535680a005682e2572d6965`
- Former Windows Actions run: `38316421524`
- Public base backend: `praydog/UEVR@4ee5c6b6162dee2291fc75f9dfc57667f6d45a2d`
- Public SDK: `elliotttate/UESDK-RenderDoc@418729025bad57b094bf6b2e2b55734454c97de6`

This is **not** a plugin on top of the current official Joey backend and
does not use the Build 69 external copy hooks. Install separately and preserve
your known-good Joey installation.

## Why go back to it?
The old user-tested Injector-5 actually rendered DuoView in STALKER 2 with
higher-density fovea, lower-resolution periphery and responsive PSVR2 gaze,
but it had periodic hitches in every rendering mode, needed Native Stereo
bootstrap, sometimes failed initial Present, and regular Mono ID 5 could
black-screen. Build 69 loaded but produced *zero* actual foveated frames.

The core foveated system, frozen gaze, shared camera view pair, Unreal
projection/rect generation, raster composite and XR stereo copy are
**identical to the proven Injector-5 source**. Only shared Present-path
housekeeping is changed.

## Exactly one runtime fix in this build
The old public Mono patch inserted an early return at the beginning of
`D3D12Component::on_post_present()` during pending/blocked Mono transitions.
That unintentionally prevented `m_graphics_memory->Commit(command_queue)`
from running, leaving DirectX graphics-memory allocation retirement/bookkeeping
skipped whenever the transition guard stayed on, including after mode changes.

The v13 patch ALWAYS executes graphics-memory Commit when the memory manager
exists. Only `clear_backbuffer()` is conditional on Mono/transition state.
This is a source-proven shared path bug, but **its causal role in the reported
periodic hitches has not been measured**. Never claim the hitches are solved
from compiling a DLL.

## Verification
- Source transformation refuses changed or unexpected upstream code.
- Regression tests validate commit cannot be skipped and clear is guarded.
- CI checks the patched real backend source after all transformations.
- CI compiles full UEVR backend, matching frontend/injector, existing policy
  tests and Windows D3D12 WARP compositor.
- Result is an EXPLORATORY candidate until the user validates headset frame pacing.

## Minimal staged STALKER 2 test
1. Extract this **entire** injector build separately from current Joey.
   Do not overwrite your existing released Joey backend. Close the game first.
2. Start SteamVR and PSVR2 Toolkit; launch the game normally. For initial
   injection, select OpenXR and **Native Stereo ID 0**, which was the
   user-observed working bootstrap for this specific old backend.
3. When in-game VR is visible, switch to **DuoView Mono ID 6**.
   Do **not** assume direct cold startup works; this build changes no bootstrap logic.
4. Inspect VR > Unreal > DuoView Mono; compare center/periphery, eye tracking
   and periodic frame pacing in the same scene. Only then compare to original
   Injector-5 in a separate process.
5. If Present E_ABORT, Mono black screen, or multi-mode hitches recur, stop.
   The next evidence target is the shared DX12/OpenXR synchronization and
   transition readiness path, **not** visual crop/gaze redesign.
