# OpenNR 2.20.1-v02 transforms

This directory contains only v02-specific transformations layered after the validated v01 chain.

The v01 scripts remain authoritative for the inherited v00/v01 behavior and should not be rewritten for ordinary v02 development.

## v02 functional scope

Only two new functional areas are planned:

1. robust before/after-NR sharpening, with a user range capped at 3.0 and verified execution rather than settings-only plumbing;
2. a substantially more robust adaptive FPS/frametime controller with explicit DLSS/Feature18 pass-cost estimation, stronger timing filtering, hysteresis/headroom controls, fast pressure response, slow recovery, and stable behavior across large workload transitions such as interior/exterior changes.

The following v01 experimental areas are preserved but are not v02 feature-development targets:

- stereo atlas;
- independent P2 model resolution;
- additional P2 shaping/stabilization work.

All v01 do-not-regress invariants remain in force.
