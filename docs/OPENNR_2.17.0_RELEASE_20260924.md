# OpenNR 2.17.0 local performance candidate

Date: 2026-09-24. This candidate follows the committed 2.16.0 upstream
refresh and adds fresh VR rendering-cost defaults plus Open Shaders PR #756's
camera reprojection fix. Its build, package, and installation evidence will
be recorded below only after each action succeeds.

## Source

- 2.16.0 upstream refresh commit: `93011a3b`.
- Focused upstream fix: [Open Shaders PR #756](https://github.com/alandtse/open-shaders/pull/756)
  at `7f4672b9e1e4b2b86a0dda50ac611480d27583a7`.
- Community NR review: [DLSS NR community review](DLSS_NR_COMMUNITY_REVIEW_20260924.md).
- Experimental defaults: VR AO 2 slices / 4 steps; incremental Skylighting
  and two-frame update intervals; hardware-gated VR VRS enabled.

## Validation

Pending final build and package verification.

## Local installation and rollback

Pending verified archive and isolated Mod Organizer profile installation.

## Acceptance

No source or package check establishes delivered SkyrimVR Feature 18 frames,
both-eye temporal stability, HMD appearance, frame pacing, or a performance
gain. The user must compare the new profile against the preserved fallback.
