# DuoView v47 UE5.5 Fixed-Crop Safety Handoff — 2026-10-15

## Target and symptom

STALKER 2 reports UE 5.5.4. In v46, eye tracking was enabled by default. The previous-clip writer is guarded by the UE 5.6 version check, but the frame-history gate still requires both per-view overrides on every eye-tracked frame after the first. On UE 5.5.4 those writes are skipped, so the next eye-tracked frame fails closed, falls back to Mono, and quarantines DuoView. Reselecting ID6 clears the quarantine in v46, allowing the same path to repeat. The UEVR log records this repeated mode-6/quarantine pattern before the D3D12 device hang; it does not establish that a particular shader or gaze sample caused the hang.

## v47 changes

- Pass the existing UE 5.6 version capability into each DuoView frame-start hook.
- Mask the eye-tracked setting by that capability. For UE 5.5.4, the effective setting is fixed-center crop.
- Turn off a persisted gaze toggle on an unsupported engine and show a UI/runtime explanation.
- Keep the raw ClipToPrevClipOverride write behind the existing version/layout/runtime checks and require eye tracking to be enabled.
- Latch a DuoView GPU fault quarantine for the current UEVR session. Reselecting ID6 cannot immediately retry the same failed path.
- Leave original rendering method IDs 0 and 5 unchanged.

## Astra handoff and SDK boundary

The pinned SDK classifies UE 5.5 FSceneViewInitOptions, but does not supply a verified UE 5.5 FSceneView offset for ClipToPrevClipOverride. UE 5.5 API documentation confirms the field exists; API existence does not establish a safe runtime byte offset. v47 does not guess an offset and does not modify or copy restricted UESDK source. The known UE 5.6.1 layout remains isolated in the candidate and is not used for STALKER 2 UE 5.5.4.

## Validation and remaining limitation

The Windows workflow must pass exact-source verification, the v47 policy verifier, production contract tests, DuoView CPU/GPU tests, Joey compatibility tests, frontend tests, the full backend/frontend build, PE architecture checks, package round-trip hashes, and the archive SHA256 check.

This is a target-safe fixed-crop build. It does **not** make eye-tracked moving crop work on UE 5.5.4. The actual game/headset run is still needed to confirm fixed-crop stability and that the reported eye-gaze fallback loop is gone. CI cannot prove Unreal TSR history consumption or rule out a game-specific GPU hang.
