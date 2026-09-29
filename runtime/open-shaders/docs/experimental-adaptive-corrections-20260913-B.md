# OpenNR EXP 2.14.8 correction B

Scope: isolated adaptive experiment; no main-package or profile-settings edits.

## Corrections

- Crop transitions use the current-frame feather mask for both DLSS and NR.
  Rendering retains the union of the outgoing/incoming tier until the mask
  handoff finishes. No prior completed SBS image is composited at the NR hook.
- NR handoff sampling uses allocation dimensions, rejects invalid depth/color,
  clamps history to the current neighborhood, and favors current pixels during
  motion. NR native motion inputs already arrive in pixel units and retain that
  contract. The disconnected legacy crop shader's normalized-motion conversion
  and eye-boundary rejection are corrected too.
- NR visual fades use elapsed time (120–800 ms), smoothstep progress, and
  incremental recursive weights. Runtime tier resolve parameters ease toward
  their target over time; the 70% tier no longer falls into the 100% default.
- Fresh SteamVR pre/post-submit GPU time and the poses-ready-to-submit interval
  replace paced update intervals as decision inputs. The larger value is used.
  The active-submit interval is a conservative elapsed-work proxy, not pure CPU
  execution time. Missing, repeated, invalid or implausible timing holds quality.
- NR recovery cannot overlap a crop handoff. Crop still restores only after NR
  reaches 100% and its own headroom/dwell requirements are satisfied.
- The crop route publishes actual copied guide dimensions after successful
  two-eye dispatch. Allocation dimensions are not valid-region dimensions.
  Adaptive NR with crop requires same-frame guides.
- Reset reasons and exact-cache reuse/eviction events use normal logging.
  Budget diagnostics include workload, GPU, active-submit, freshness, pressure,
  headroom, tier, transition and crop-held state every 300 engine frames.

## Resource safety boundary

The previous run demonstrated a native fixed-envelope dispatch rejection.
This revision does not claim that native feature caching is solved. After
either DLSS or NR rejects the envelope, further adaptive crop tier changes
are held until restart; NR may continue adapting. The existing exact-size
fallback remains for safe rendering, not continued crop oscillation.

## Verification

- MSVC Release DLL build.
- C++ suite: 171 cases / 2357 assertions, including 12 adaptive cases / 54 assertions.
- All three touched compute shaders compile with Windows SDK FXC, cs_5_0.
- git diff --check.
- No game launch, runtime deployment, main installation edit, or profile edit.

Live acceptance remains required: correct two-eye output, boundary motion,
NR appearance, restoration under actual headroom, and workload diagnostics.
The current-frame crop fade avoids old-image trails by construction, but
native DLSS/NR history resets can still make a resource handoff visible.
No claim of imperceptibility or measured performance improvement is made.
