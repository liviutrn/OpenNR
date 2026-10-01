# OpenNR 2.20.1-v05

Base: `build/2.20.1-v04` at `376fc570014d23ca25bd0b8258957d73df2ad517`.

## Purpose

v05 replaces the v04 adaptive decision policy with a deliberately simple, manually configurable SteamVR GPU-frametime controller. It changes only two runtime quality knobs: Neural Rendering pass count and foveated crop scale. Model resolution is never adapted.

## Controller

Default in-game thresholds:

- **Pass +1 below:** 14.0 ms
- **Crop +1 tier below:** 16.0 ms
- **Crop -1 tier above:** 18.0 ms
- **Pass -1 above:** 20.0 ms

All four thresholds are directly editable from **10.0 to 30.0 ms**. Values are not silently reordered. The UI warns if the usual hysteresis ordering `Pass+ < Crop+ < Crop- < Pass-` is not satisfied.

Timing defaults:

- Frametime smoothing: 250 ms
- Decrease hold: 350 ms
- Increase hold: 1200 ms
- Cooldown after a quality change: 1000 ms

These timing values are also configurable in game. One quality action is allowed per cooldown.

## Crop-first behavior

Adaptive crop tiers are fixed to **100%, 80%, 60% of the user's selected crop**. They are multipliers of the chosen crop, not absolute screen coverage.

Example with **Center 60%** selected:

- 100% tier = 60% effective crop
- 80% tier = 48% effective crop
- 60% tier = 36% effective crop

Crop always has priority:

- Under load, crop shrinks first while filtered frametime is above the crop-decrease threshold. A pass can be removed only after the crop has reached the 60% relative floor (or crop adaptation is unavailable).
- During recovery, crop expands first while filtered frametime is below the crop-increase threshold. A pass can be restored only after crop has reached the 100% relative ceiling (or crop adaptation is unavailable).

Adaptive pass range is **0/1/2**. Manual 3x sequential NR remains available when the adaptive controller is disabled.

## Frametime source and robustness

The controller uses SteamVR/OpenVR application GPU timing (`m_flPreSubmitGpuMs + m_flPostSubmitGpuMs`). It uses one time-based EMA, not the v04 fast/slow predictive controller. A single extreme loading sample is capped for filtering, while sustained load above the 30 ms maximum configurable threshold still drives degradation normally.

Removed from adaptive decisions:

- target FPS / headset-refresh budgeting
- predicted DLSS NR pass cost
- CPU/GPU-bound classification
- VRAM pressure forcing
- model-resolution adaptation
- competing fast/slow policy filters

## Live UI

The Adaptive Performance panel shows the actual runtime state used by rendering:

- raw and filtered frametime
- active/configured NR passes
- current and target crop tier
- selected crop and effective crop size
- hold progress and cooldown
- last pass/crop action and frametime

There are no manual hotkeys/buttons in v05.

## Compatibility / regression contracts

### Stereo Atlas

The v04 atlas protections are retained:

- adaptive control remains on the native Stereo Atlas route
- adaptive pass count is limited to 0/1/2
- adaptive model-resolution switching stays disabled
- temporal residual reuse and staggered-eye reuse are forced off while adaptive control is active
- 0-pass mode bypasses NR without disturbing the completed DLSS image

### NR model resolution

The user's chosen Neural Rendering model resolution is held fixed while adaptive control is active. In particular, **100% stays 100%**; the controller never lowers it.

### Gaze / crop history

The adaptive crop scales the user-selected crop around its existing center/origin. Eye tracking continues to own gaze position. Temporal state is invalidated once when a discrete 100/80/60 crop geometry transition commits; ordinary gaze movement at a stable tier does not reset history every frame.

### Retained v03/v04 behavior

v05 keeps the validated sequential renderer, separate second-pass tuning/crop controls, gaze fixation/stability work, crop-motion compensation, zero-pass safety, sharpening range 0-3, and the user's selected crop as the 100% adaptive ceiling.

## Build verification

The v05 workflow reconstructs the validated v00-v04 transform chain, applies `scripts/v05/apply-simple-frametime-controller.ps1`, then checks generated-source invariants before compiling. The checks explicitly cover the 100/80/60 relative crop ladder, crop-first pass gating, fixed model resolution, Stereo Atlas compatibility, 0-pass bypass, gaze stability, and sharpening mapping.
