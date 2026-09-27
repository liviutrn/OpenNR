# Build 24 — adaptive crop/pass policy cleanup

Run 24 is a focused follow-up to Run 23. It keeps DLSS Neural Rendering model resolution fixed at 100% and changes only adaptive crop/pass coordination, regression tests, and CI validation.

## Changes and reasons

- Removes stale adaptive-resolution assumptions from the adaptive policy tests. Adaptive quality now has only two runtime quality axes: crop size and NR pass count.
- Makes crop-first pressure ordering explicit: reduce crop until the configured minimum is fully committed, then remove extra NR passes, then disable the final P1 only if sustained pressure remains.
- Prevents a pass reduction from starting while an adaptive crop handoff is still visually in progress. The previous crop remains the committed `ActiveScalePercent()` until the handoff completes; `TargetScalePercent()` carries the pending tier.
- Makes crop-first recovery deliberately asymmetric: restore P1 first if NR was fully off, then restore crop toward its configured maximum, then consider P2/P3.
- Extra-pass recovery remains cost-gated by the existing per-pass activation-cost estimates. For example, if P1 is active at an 80% adaptive crop and there is some headroom but not enough estimated headroom for P2, the controller restores crop instead of stalling on the unaffordable P2 request.
- Downshifts remain driven by measured sustained workload after each quality step rather than subtracting estimated pass costs. This is intentional: activation-cost estimates are useful for avoiding an unsafe restore, while actual post-step SteamVR workload is more reliable than guessed savings when deciding whether another reduction is necessary.
- GitHub Actions now compiles and runs the C++ utility tests before packaging so stale policy/test mismatches cannot silently ship in the artifact.

## Intended 2-pass crop-first state sequence

Pressure:

`P1+P2 / max crop -> P1+P2 / smaller crop(s) -> P1 / min crop -> NR off / min crop`

Recovery:

`NR off / min crop -> P1 / min crop -> P1 / crop restored toward max -> P1+P2 / max crop`

P2 is restored only when its configured activation-cost estimate plus current measured work fits below the restore threshold.

## Validation focus

- Verify that no P2/P1 drop begins before the current crop handoff has visually completed.
- Verify the pressure order with 2x NR and `Reduce crop first`, especially with one-step (`100 -> 80`) and multi-step (`100 -> 90 -> 80`) crop ranges.
- Verify recovery from NR-off: P1 first, crop to maximum second, P2 last.
- Verify that P2 stays off when its projected activation cost would exceed the restore threshold while crop still has room to recover.
- Check that gaze tracking and crop geometry remain stereo-consistent through both downshift and recovery handoffs.
