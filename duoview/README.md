# DuoView Mono — UEVR Stage 1 source prototype

**Status:** Source patch and standalone C++ policy/transition smoke tests pass.
**Not yet a compiled or headset-validated UEVR build.**
**Not yet foveated. No performance or PPD improvement is claimed.**

This temporary CI workspace lives on an isolated branch of `liviutrn/OpenNR`;
the OpenNR `main` branch is unchanged. It fetches the real Joey Mono/DIBR
backend rather than replacing the user's working injector.

## Pinned inputs

- UEVR backend: `joeyhodge/UEVR`, commit `db6729dd9f5745705b1cdec2ec6f51bdc9570983`
- UEVR frontend: `joeyhodge/uevr-frontend`, commit `60be4b0f9a646109fd9fdf448bacd41477234091`
- UESDK gitlink: `2ad9fefa67eb69634b9a1252f4b99876f5333671` (restricted)
- Target: STALKER 2 / DX12 / PSVR2 / SteamVR OpenXR.

## Changes in the source patch

- Rendering method **6 = DuoView Mono (Stage 1 Diagnostic)**.
- Preserve original Mono **5** and all historical rendering IDs.
- Include mode 6 in the guarded Mono GPU-retirement / generation transition,
  startup, availability and frame-validation policies.
- Request **two Unreal scene views** instead of one in mode 6.
- Keep the two views in separate side-by-side view rectangles of identical
  size in the existing double-wide render target.
- Reuse the current Mono camera offset and common projection for *both*
  Unreal views, intentionally creating zero inter-view IPD.
- Preserve the current Mono OpenXR copy/submission to both headset eyes.
- Accept **two-view** main families for DuoView frame validation.
- Add smoke tests for ID 6 and transitions mode 6 → 5 → 0.

## Outstanding stages

1. **UEVR full Windows compile:** pending access to the exact matching restricted UESDK.
2. **Actual Unreal rendering proof:** headset tests and GPU capture must verify
   two scene-renderer view passes, same pose, same projection, correct view states,
   stable Lumen/shadows, and no stale OpenXR frames.
3. **Real independent view sizes:** foveal view and peripheral view must receive
   different rendering resolutions *before material/G-buffer/Lumen shading*.
4. **Correct compositor:** combine two view textures into one mono frame, with
   off-axis perspective mapping, stable color, and feathering.
5. **PSVR2 gaze:** reuse working OpenXR gaze, stabilize temporal histories.
6. **Profiling:** compare identical STALKER 2 scenes at 3000×3000 mono and
   DuoView 50%/30%, capturing total GPU cost and individual render passes.

At Stage 1, both engine views render at full per-view resolution. **Frame time
may be worse than ordinary Mono. Do not use this diagnostic for gameplay FPS.**

## CI

Workflow: `.github/workflows/duoview-stage1.yml`

The **source-validation** job does not need the Epic-licensed SDK. It checks out
the pinned backend, applies strict exact-anchor edits, compiles the isolated
`MonoRenderingPolicy.hpp` C++ smoke test, and executes it.

The **build-stage1** job is intentionally gated behind the repository variable
`DUOVIEW_FULL_BUILD=1`. The pinned upstream UEVR backend's
`dependencies/submodules/UESDK` points to `joeyhodge/UESDK`, whose exact
commit is inaccessible through the current GitHub account. A normal checkout
without authorization fails with *Repository not found* before compilation.

Once access to that exact submodule is legitimately available, configure the
GitHub Actions secret `UEVR_SOURCE_TOKEN` with read access, set
`DUOVIEW_FULL_BUILD=1`, and run the workflow. Do not paste tokens into code,
the issue tracker or chat. The full-build CI will only publish the Windows ZIP
after compiling UEVR, compiling auxiliaries, building the frontend, and passing
the existing offline tests. A successful CI ZIP still requires PSVR2 headset
testing.

No user profiles or settings in an existing UEVR installation have been changed.
