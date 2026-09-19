# OpenNR 2.15.1

Release date: 2026-09-17. Complete AIO update from 2.15.0.

## Native OpenVR eye tracking

- Eye movements bypass the old low-pass delay. Optional smoothing now applies
  only to fixation noise within two input pixels; the new-install default is zero.
  Saved smoothing values remain supported without delaying deliberate movement.
- A small central guard keeps fixation jitter from constantly relocating the crop.
  Leaving the guard recenters immediately. Crop dimensions stay fixed.
- Every crop relocation invalidates both DLSS SR and neural-rendering history.
  This conservative policy avoids reusing history with the wrong crop origin;
  it does not claim continuous moving-crop temporal reconstruction.
- Loss of valid gaze holds briefly, then switches once to the static fallback.
  The previous slow animated return is removed. Gaze/static transitions with
  unchanged dimensions preserve GPU resource identity.
- When VRS is enabled, it shares the native gaze crop decision with DLSS/NR.
- Added query timing, crop/reset counters, clearer freshness wording, and the
  read-only `eyeTrackingStatus` devbench query. Last valid query age is not a
  sensor timestamp or an end-to-end latency measurement.

## Adaptive rendering and runtime reliability

- Includes all current adaptive NR/crop work, including fixed backing envelopes
  with separate valid rectangles, corrected reduced-resolution sampling, bounded
  crop restoration, and existing exact-extent fallback after envelope rejection.
- Includes the session memory-pressure ceiling. Sustained headroom or target-FPS
  changes no longer repeatedly restore tiers rejected under VRAM pressure.
  Explicit Neural Rendering Reset or restart clears the learned ceiling.
- Retains bounded tier residency, directed prewarming, recovery/failure handling,
  VRAM-warning handling, same-frame retry protection, and queued NR reset/status
  devbench actions developed since the initial 2.15.0 package.
- Carries the existing adaptive-budget UI, map/UI follow-ups, capture support,
  native Feature 18 carrier, translations, and the complete AIO feature payload.

## Compatibility and validation boundary

The runtime identity remains `CommunityShaders.dll`. Existing profile settings
are preserved. Installing this update does not enable gaze, VRS, capture, or
adaptive rendering on a user's behalf.

Eye tracking remains optional and experimental. The changes target identified
latency/history/resource problems; they are not a measured FPS improvement or
headset acceptance. Live stereo, gaze response, crop transition quality, frame
time, and tracker/runtime compatibility must still be checked on an eye-tracked
headset. Frequent large movements can still reset temporal history frequently.
