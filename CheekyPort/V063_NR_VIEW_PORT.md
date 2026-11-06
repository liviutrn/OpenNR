# Cheeky 0.6.3 – TriView NR for both native stereo foveas

Date: 2026-11-06. Experiment only: `experiment/cheeky-v063-triview-dual-fovea-nr-20261106`.
Based on v0.6.3 source commit `39bfc96214498e5e21cf861f0eb21f875697b428` and
the user-tested November 3 Dual NR Templates branch, commit `ed4e9da`.
This is a Cheeky-side patch; it does not alter UEVR TriView B14 or its compositor.

## Routing

UEVR menu **NR processing view**:
- **3 – TriView: both foveas only** (recommended): the two equal-output-size
  D3D12 DLSS source evaluations are classified as the real stereo fovea pair;
  the third different-size mono/full-FOV DLSS source bypasses private Cheeky
  processing and runs game-native DLSS.
- **0 – All rendered DLSS views**: permits NR on every source that actually
  produces a hooked DLSS evaluation, including a mono peripheral source *if
  one exists*. It cannot run NR on a synthetic/reprojected peripheral image
  without a real DLSS source call.
- **1/2 – legacy DuoView View 0 / View 1**: retained unchanged.

For OpenXR quad sources that provide verified role mappings, focus role is
authoritative. Otherwise TriView fovea selection requires **exactly three**
recent D3D12 DLSS source IDs: a unique equal-size pair plus a differently sized
third source. Different sizes, extra active handles, a missing periphery DLSS
call, or unresolved mapping fail closed: NR is skipped, never guessed based
on NGX handle order. All mode remains an explicit fallback. The previous
EyeProcessingMode=0 config remains All for compatibility; explicitly choose 3.

## What changed and why

- **Removed independent per-pass crops** altogether, including its NGX
  subrect changes, GPU CopyResource code, settings, UI and regression tests.
  Original shared-crop, multi-pass NR and existing Template 1/2 remain.
- **Reduced model cache from 1 spare per pass to 0**. Old A/B NGX features
  are retired only after their GPU recording leases complete. Expect possible
  temporary native-DLSS fallback during model switching, not hot swapping.
- **GPU scratch reclamation**: after a resize or changed NR working scale,
  old-size scratch sets are freed only when their in-flight GPU work is
  completed. The eight-slot rotating-input cache is *not* reduced so that
  steady-state render pacing is not harmed.
- **NR before SR**: original upstream pre-upscaling pathway retained.
  Excluded periphery avoids NR feature creation, guide/codec scratch,
  inference and input substitution. NR processing scale and pass count
  remain user-configurable; this is not a promised FPS uplift.
- Existing template loading is retained, including the previous limitation:
  load only templates saved by this UI, not arbitrary/empty files.

## Test / validation

CI workflow: `.github/workflows/cheeky-v063-nr-view.yml`.
Tests: TriView pair classification, ambiguity/pass-through, DuoView calibrated
selection, original NVIDIA NR regression suites, UEVR runtime template tests,
full Windows release build and exact ZIP payload verification.

**CI passing is not enough.** The key unknown is real STALKER 2 TriView B14
NGX source geometry and whether three distinct DLSS evaluations are hooked.
Use View=3 and NR before SR, compare both foveas with each eye separately,
then View=0 to see whether the peripheral region also responds. If View=3
silently bypasses all NR, obtain Cheeky support/diagnostic JSON showing live
DLSS source IDs and their input/output dimensions before adjusting routing.
Check headset FPS (same place/settings), GPU usage and VRAM before/after.
Avoid A/B switching in normal gameplay while collecting numbers.
