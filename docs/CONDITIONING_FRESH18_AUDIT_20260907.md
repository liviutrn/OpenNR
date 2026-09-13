# Fresh renderer-conditioning audit — 2026-09-07

## Outcome

The 18 new eight-frame captures pass structural validation and decoded-buffer health checks. Preserve them. They do not yet satisfy the planned contiguous 64-frame pilot.

Scope: `C:\OpenNR_Captures_RendererConditioningPilot_0.5.5_20260907`, sequences `seq-1788802891824-1` through `seq-1788803150598-18`. No training, cloud activity, runtime/configuration changes, or capture deletion was performed.

## Evidence

- 144 stereo frames; 2,880 capture artifacts. All 18 sequences passed `validate_capture.py` with no errors or warnings and `validate_temporal_capture.py --mode crop` with temporal_ready=true.
- Each sequence has eight complete frames, contiguous frame/host/sample indices, initial reset [true,true], no mid-sequence reset, and no reported dropped frames or backpressure.
- Decoded all six G-buffer stages for both eyes: 1,728 conditioning payloads. No nonfinite values, wholly spatially constant payloads, or uncovered native-to-teacher crop mappings.
- Every stage/eye combination has eight distinct payload hashes in its sequence. This excludes exact stale-buffer repeats, but does not independently prove precise capture timing.
- Native crops were resampled into teacher coordinates before comparison. Representative first/last-frame and timeline sheets show corresponding geometry in color, albedo, decoded normals and roughness. Appearance differences between lit color and G-buffer material channels are expected; these remain partial renderer observations.
- Same-eye/current-frame mean edge correlation exceeded opposite-eye correlation in all 18 clips, and neighboring-frame mean correlation in 17. Sequence 18 is nearly static: current 0.377415 versus neighboring-frame mean 0.377945, so its timing comparison is inconclusive. These heuristics and representative visual inspection are not subpixel or exact-frame synchronization certification.

## Next collection gate

The saved configuration still has both `burst_frames=8` and `max_samples=8`. It was not changed by this validation. Configure both for the intended 64-frame pilot before recording three varied, controlled sequences: modest face/character motion, outdoor vegetation and pan, and an indoor material/lighting scene. Validate that pilot before a large collection. Independent eight-frame clips cannot be concatenated into continuous 64-frame temporal evidence.

## Reproducible artifacts

The existing `tools/audit_conditioning_content.py` generated `out/conditioning_content_fresh18_20260907/audit.json` and `index.html`, plus aligned, six-channel, and eight-frame timeline sheets for every sequence. Derived outputs are separate from original captures.

This is capture-health evidence, not proof of training improvement, MAE, live VR performance, or a complete material representation.
