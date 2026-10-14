# DuoView Build37 — safe launch recovery (14 October 2026)

## Goal / user evidence

STALKER 2 on RTX 5070, PSVR2, DX12, SteamVR OpenXR. User repeatedly observes Build33-era DuoView ID6 works on launch *only after first selecting Native Stereo ID0*, even though direct ID6 activation fails or is unstable. They can change OpenXR resolution scale inside UEVR and reinitialize rendering. The previous forced-ID6/compact atlas candidates Build34 and Build35 crashed during injection (NVIDIA DLSS/NGX stack); neither is a valid production baseline.

## Protected baselines and rollback

- **Joey Build3 is sacred, untouched**: headset-tested 30 minutes, Mono ID5, run `38453012351`. Original Joey backend `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`, UESDK `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`, matching frontend `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`.
- **Build33 recovery source**: `d6b0a2bcd416073c41475f717aac03265c9687fd` on `experiments/duoview-v24-instant-gaze-temporal-audit`. Build33 Windows CI succeeded, but user rejected gaze/crop jitter; fixed center worked. It was **not** established as a fully working eye-tracked build.
- Current recovery branch: `experiments/duoview-build33-lowres-native-bootstrap-v37`. Built by the original `.github/workflows/duoview-joey-stage234.yml` with exact source pins. The branch applies `duoview/joey_stage1/apply_stage1.py`, then `apply_stage234.py`, then **new** `apply_native_lowres_bootstrap.py`. Code is protected by `verify_stage234.py` checks.
- Experimental Mono5 startup `experiments/duoview-build33-safe-mono-bootstrap-v36` is superseded by the Native0 plan; do not give it to user as a verified fix.

## Changes now made in source (not headset-verified)

1. At initial OpenXR construction and again after persisted OpenXR settings load but before the initial swapchain creation, set UEVR OpenXR resolution scale to **0.30**. Capture original/persisted scale as the desired final resolution; no change is made to SteamVR's setting.
2. Force the initial rendering method to **Native Stereo ID0**, not ID6. Avoid old saved ID6 profile forcing DuoView prematurely. Keep ordinary Native0 view rendering active for at least 8 rendered frames and then 3 seconds of continuous runtime readiness.
3. Request **DuoView ID6** via Joey's regular, GPU-retired, game-frame-boundary Mono-family transition gate. This is intended to reproduce the user's successful manual Native0 -> ID6 sequence instead of forcing ID6 at injection.
4. The older **double-wide noncompact scene atlas** is preserved. No direct NGX/DLSS intercept/historical reset is included. Compositor quality remains the Build33 design, including its known tracked-gaze jitter issue.
5. Correct one original Build33 startup dependency: activate the Unreal SceneView constructor hook directly for ID6 even if Native Fix and compatibility toggles are disabled. No native-stereo render mode is forced after ID6 activation.
6. **Do not restore the original resolution merely on a timer**. Wait until the DuoView renderer has produced and submitted at least three successful composed frames, then for two additional seconds of stable runtime, and attempt one restoration via Joey's existing `on_openxr_resolution_scale_changed` handler. That handler schedules safe D3D12 reset and updates OpenXR scale bookkeeping. Retire DuoView frame state after a successful change. If engine policy rejects the change, remain at the low startup scale and log the failure; no retry loop.
7. Protect the phase ordering through explicit source checks. A profile reload after ID6 activation must not force ID0 again.

## Verification status / constraints

- All commits and workflow changes are on this isolated experiment branch; not on main or Joey Build3.
- **Windows CI must pass before sharing DLL**. Source tests and exact backend/frontend/SDK identity checks execute on GitHub Actions; do not confuse other repository workflow failures with this dedicated workflow.
- Even full CI cannot establish that NVIDIA DLSS remains stable across the low-res Native0 -> ID6 -> high-res reallocation. The user's headset/game test is still the final acceptance criterion.
- Automatic in-game restoration is based on Joey's same scaling callback as the UI, but now invoked from the game tick after successful composition. Its threading and OpenXR frame-lifecycle behavior remain **unverified in the actual headset** and should receive special review. If unsafe, replace with a queued safe-point operation or a user-initiated UEVR scale adjustment, rather than claiming it works.
- Starting with Native0 does not prove the required view histories are reusable across the mode change. Guard against stale source, projection, DLSS feature, and compositor frame-state across both transitions.
- If the next crash reproduces NVIDIA's execute-at-zero in NGX with no added interception, inspect the view/resource bootstrap and temporal history, not merely NVIDIA's driver.
- The goal of Build37 is *launch recovery*, NOT fixing Build33 gaze jitter or introducing new quality features.

## Acceptance checklist

**Required:** game reaches VR with native0 at 0.30 scale; mode6 commits only after ready+retirement; fovea/periphery both really render; no NGX crash; scale restore only after complete DuoView compositions; both XR eye outputs at intended resolution after safe reconfigure; no hitching; no old scene RT sizes; no duplicate DX12 copies; headset-test confirmation. Do not call the build stable merely because GitHub CI passes.
