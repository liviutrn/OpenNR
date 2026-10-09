# r10 NR and cropped DLSS review

## Source provenance

The baseline is `build/2.20.1-v06-r7`, commit `1620bde5b9f9f504046c16056fa12c17efac74f1`. The tracked runtime is a reconstruction input, not the final DLL source. The inherited Windows transformation chain was executed and r7 source/hash audits passed before edits. Its review snapshot is `eb712023c77689010559d1ea49c894ddab6d3784`, produced by run `37964857413`.

The new build retains the original reconstruction chain and r7 checks, then applies an exact r10 patch. Every edited generated file has before/after SHA-256 guards. No r8/r9 features are imported.

## Controller and correctness

The six stages are selected crop, four ordered relative crop percentages, then NR off with the selected crop restored. The four defaults are 90/80/70/60. The existing 60% adaptive floor is retained; values use the actuator's 5-point grid. Stage arrays participate in policy-change detection, so live edits clear decision holds and failed-growth guards without rewriting the selected crop.

Settings serialization, clamping, menu controls, developer command validation and developer schemas all use the same four stage fields. Developer commands validate all requested values before any mutation. Legacy resolution/drop fields are absent from the persisted controller settings. Rendering normalizes every NR model request to 100%, even if a caller supplies a stale reduced value.

The old fixed-step actuator could alternate around a configurable target that did not lie on that step's sequence. The new optional exact target selects one legal bucket directly. Its default zero preserves behavior for other callers. It retains the r7 handoff mask, previous geometry while settling, frame ownership, holds and resource-loss fallback. The policy still waits for geometry and NR output transitions before changing stage.

Fresh SteamVR application GPU timing, EMA cap, decision holds/cooldown and failed-growth protection are retained. Stage 5/6 endpoint thresholds remain isolated. Stage 6→5 resume retains the crop commit gate, one history reset and residual fade. NR-off restores the selected crop rather than a full-eye preset.

## Pipeline and practical optimizations

Reviewed the SR crop envelope and renewal ownership, guide coordinate/motion scaling, per-eye color/guide staging, native atlas pack/evaluate/split, model-tier routing, output shaping/history recording, near-black protection, stereo writeback, native failure handling, and D3D11/D3D12 interop boundaries.

Applied:

1. Full-resolution normalization eliminates reduced model texture allocation, downsample and resolve work from the reachable NR path. It also eliminates model-resolution transitions that the user reported as flickering.
2. Exact crop stage targets avoid intermediate geometry commits/neural workloads during a single stage change, retaining the existing transition behavior at the selected endpoint.
3. Combined atlas color/depth/motion preparation removes one compute dispatch, one constant-buffer update and their binding/cleanup sequence per adaptive NR frame. The guide arithmetic is unchanged; color guard pixels retain the split left/right edge replication. Shader execution compares all outputs against the r7 shaders, including untouched padding.

Retained after review:

- Resident atlas/crop allocations and guard reserve: shrinking them can trigger reallocation or history renewal during crop changes. No speculative reduction is included.
- Base/depth history copies: the next crop handoff needs the matching unshaped input and depth. Dropping them would save work by invalidating the transition contract.
- Raw history before output shaping/black protection: feeding the display correction into history would change later NR behavior.
- Native interop synchronization: the D3D11/D3D12 shared-resource producer/consumer boundary requires completion/ownership ordering. Removing waits or flushes without a new scheduling contract risks stale textures and flicker.
- Existing periphery and edge reconstruction: fusing it into unrelated passes would change sampling, blending or writeback ownership and is outside a small stable revision.
- The single native atlas evaluation: its internal neural fixed cost is opaque to this source. No claim is made that these edits remove the user's measured fixed cost or guarantee a particular millisecond gain.

## Validation

Before the new build, Linux C++ tests passed 17,910 stage transition/live-edit cases across every ordered dropdown combination, plus endpoint threshold gates, Force modes, invalid/stale timing, geometry loss and holds. Direct transitions permit only source/target geometry and at most one committed change. Integration checks and six CPU/HLSL constant-buffer layouts passed.

Windows CI repeats the controller/layout checks with MSVC, executes the fused atlas against the original r7 shaders on software D3D11, preserves inherited gaze and near-black/resume tests, validates full runtime source contracts, builds the universal x64 DLL/package, and audits package contents against the compiled r6 reference used by r7. Only the DLL and the two explicitly changed shaders may differ from that reference beyond the already reviewed r7 removals.

Software D3D11 proves shader execution/equivalence for the tested cases; it is not an NVIDIA NR evaluation or hardware performance benchmark. Skyrim/PSVR2 testing cannot run in this workspace. In-game developer testing and headset/GPU measurements remain unperformed here.
