# OpenNR 2.20.1-v06-r10 stable

Based on **r7**. This revision replaces NR resolution reduction with four independently configurable crop stages and retains one stereo-atlas neural evaluation.

| Stage | Crop relative to your selected crop, per axis | NR resolution |
|---|---:|---:|
| 1 | 100% | 100% |
| 2 | 90% default, configurable | 100% |
| 3 | 80% default, configurable | 100% |
| 4 | 70% default, configurable | 100% |
| 5 | 60% default, configurable | 100% |
| 6 | 100%, selected crop restored | NR off |

Each stage 2–5 has its own in-game dropdown, with 60–100% choices in 5-point increments. Stages stay in descending order; choices that would exceed a neighboring stage are disabled. Equal percentages are permitted. Settings persist through Save Settings. Old crop-drop and reduced-NR-resolution values cannot reactivate the previous ladder.

With a selected 50% crop, the default active stages are 50/45/40/35/30% of each eye's width and height. Stage 6 restores the selected 50% crop with NR off. The percentages describe dimensions, so a 60% relative crop has 36% of the selected crop's rectangular area, before alignment and guards.

Auto and Force stage 1–6 remain. The GPU budget, recovery headroom, timing smoothing, holds, cooldown, and endpoint thresholds retain r7 behavior. Disable NR above applies only at stage 5; Re-enable NR below applies only at stage 6. Resume waits for the stage-5 crop to commit, then resets stale NR history once and fades NR back in.

Changes to rendering and performance:

- NR model resolution is fixed at 100% in settings, integration and renderer normalization. The reduced-model input/resolve path is unreachable through the runtime boundary.
- A crop stage commits its exact configured target in one handoff instead of stepping through intermediate crop geometries. This also prevents arbitrary targets from being overshot by the former fixed-step actuator.
- Adaptive atlas preparation combines color packing and the existing depth/motion packing into one GPU dispatch. It preserves the previous motion/depth calculations and the eye-color guard replication rules.
- The existing resident resource envelope, raw NR history, crop/gaze alignment, near-black protection, result shaping, strict one-pass atlas behavior and failure handling are retained.

The NVIDIA NR carrier remains excluded, as in r7.

Validation records are in the build artifacts and [the technical review](REVIEW.md). Automated source checks, controller tests, shader execution and DLL compilation do not establish headset visual acceptance or measured hardware GPU savings. “Stable” is the requested revision name; on-headset testing remains necessary.
