# Exact current Joey SDK recovery

**Current status: original SDK recovered. Reconstruction is paused.**
After the user's EpicGames/GitHub access was activated, the connected tools
could read the exact required SDK commit. All 176 tracked files were
retrieved and each Git blob verified. The root Git tree and complete original
commit object also match exactly. The exact-source baseline workflow now
uses the original SDK; no code from this reconstruction folder is integrated.
The sections below preserve the earlier evidence and isolated tests.

The target remains the official latest release `101226HELLRAISERp1`, Mono
backend `5ac7edc207866569334175e4ed8a7517971547f6`, and original SDK
`3cffbc82429b6165ceec2714f0f0d9ae48f55596`. No other backend revision is used.
The Joey renderer, XR lifecycle, game compatibility and frontend are unchanged.

## Recovered evidence

The exact SDK repository is still inaccessible. Repository-name searches
including forks, exact code searches, direct Git access and the accessible
public SDK's commit lookup did not recover that source.

However, the official successful Windows build published its full symbols:

- [Run 38150970046](https://github.com/joeyhodge/UEVR/actions/runs/38150970046)
- [Artifact 11707171949](https://github.com/joeyhodge/UEVR/actions/runs/38150970046/artifacts/11707171949)
- Artifact SHA-256: `e9b245a6bb53fc0f8545f1f360ca35c6a15d3f40356e5823b98712269603a4d2`
- The archived DLL SHA-256 exactly matches the smooth official baseline:
  `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.
- PDB SHA-256: `9d90e575d3e3d4b131be08809cb232c782afb267b15584c431fcb04ef9143a17`.
- DLL and PDB both identify GUID `b9d7af12-4a42-4336-bdab-dbcb3a011af2`, age 1.

The independent first artifact from run `38196846646` used the same source
commit but had a different DLL hash. It was rejected as the reference for the
official release. Do not substitute its symbols or machine code.

`recover_sdk_symbols.py` verifies the official DLL digest and its actual PE
debug directory, validates the PDB GUID/age, then reads the type and module
symbol streams. It extracted 357 defined SDK types and 5,249 SDK procedure
records from 63 relevant modules. Procedure records include templates and
exception helpers; this is not a count of independent missing functions.
Unrecognized field records remain explicit raw evidence rather than guesses.

`evidence/SDK_CONTRACTS.json` retains the complete type-name inventory and
the detailed core contracts. The full extraction is reproducible from the
matching public artifact. Debug symbols provide types and machine-code
locations; **they are not the original SDK source or proof of equivalence**.

## Architectural findings

The latest SDK publishes immutable layout snapshots. `FamilyLayout`,
`InitOptionsLayout`, `object_array::Layout` and `HeaderLayout` have distinct
publication state. SDK identity records also retain the array-layout and
header-layout pointers, plus registration index, serial and vtable.

Recreating only the old July declarations would therefore miss meaningful
behavior. In particular, stale/recycled objects and readers holding previous
layout snapshots need the current contracts. These behaviors must be recovered
before the SDK is integrated into the backend.

## First reconstructed module

`include/sdk/DiscoveryMemory.hpp` and `src/DiscoveryMemory.cpp` implement the
first module independently. Its memory callback layout matches the PDB:
24 bytes, context/read/executable at offsets 0/8/16. The two process helpers
are reconstructed from the actual official machine code, not from the old SDK.

The original `read_process` rejects addresses below 64 KiB, calls
`ReadProcessMemory(GetCurrentProcess())`, and requires an exact byte count.
The original `executable_image` requires a nonempty, nonoverflowing range,
committed `MEM_IMAGE`, readable executable protection, no guard/no-access,
and a range wholly inside the single `VirtualQuery` region. That last rule
is deliberately preserved; accepting an arbitrary collection of adjacent
regions would change the baseline's discovery behavior.

`Memory::load` is reconstructed from the current callers and their emitted
code. Its ABI is verified, but its full template-level equivalence is still
pending broader original SDK tests.

The standalone module is **not integrated into the backend**. All remaining
missing declarations, original SDK changes and test sources stay visible as
blockers. No empty SDK headers or disabled game compatibility paths are added.

## Differential verification

`generate_memory_reference.py` extracts only the two original memory helpers
from the verified DLL. It fully decodes each slice, checks its imports and
rejects external direct calls/jumps or other RIP-relative dependencies.
It emits the byte arrays and a provenance/disassembly report.

The Windows test maps those two small slices into test-owned memory and
resolves their three Windows imports. It never loads or initializes the UEVR
backend. This is an offline oracle, not a production hook or extension.

The test compares return values and output bytes on real valid, invalid,
unreadable, crossing-page and overflowing addresses. It also compares image
classification against real module code, executable private allocations,
guard/no-access pages, empty ranges and memory-region boundaries. Typed
callback layout and bounds have separate checks.

Run on Windows x64:

```powershell
cmake -S duoview/clean_restart/sdk_reconstruction -B sdk-build -A x64
cmake --build sdk-build --config Release
ctest --test-dir sdk-build -C Release --verbose --output-on-failure
```

This CI uploads **test evidence only**. A green run does not mean a rebuilt
SDK, a rebuilt backend, or a headset-ready baseline. `[sdk-only]` commits
skip unrelated baseline jobs without changing their previously recorded
failed full-build result.

The first Windows run completed successfully: [38442752728](https://github.com/liviutrn/OpenNR/actions/runs/38442752728),
job `115453241336`, source commit `5296d0d70cc2d2335d41c4f4c625c48c793439b3`.
MSVC compiled with `/W4 /WX`; the differential executable passed **52 checks
with zero failures**. Evidence artifact `11837855571` has SHA-256
`14e465539bc1dcfb40377f18c6195da433ed7c54da4b73554afbf63bdab62986`.
The extractor also rejected the same-source, different-DLL first artifact
before reading its symbols, and the exact Joey backend working tree remained
unchanged.

## Remaining work, in dependency order

1. Recover bounded instruction discovery and render-target-manager selection
   using the exact function records, constants and official code.
2. Recover array/header layouts, object identity/liveness and immutable
   scene-layout publication, including layout discovery/retry behavior.
3. Recover reflected-name calls and title-specific contracts without removing
   existing game checks. Audit differences in already-existing SDK headers
   and implementations, not only the 15 absent headers.
4. Recover the original SDK test sources where possible and validate the
   complete original backend compatibility suite. Then compile the complete
   unchanged current Joey backend and matching frontend.
5. Package a clearly labelled reconstructed-SDK baseline for Native Stereo and
   Mono stability testing. Only after that passes can DuoView integration begin.

There is no new installable baseline or DuoView build at this checkpoint.

## Source download route to check before reconstruction

The pinned Joey source's own [COMPILING.md](https://github.com/joeyhodge/UEVR/blob/5ac7edc207866569334175e4ed8a7517971547f6/COMPILING.md)
says UESDK is part of the restricted EpicGames/UnrealEngine fork network
and requires EpicGames GitHub organization access. That inherited guide
links the Praydog SDK; the pinned `.gitmodules` selects Joey's SDK fork.
Consequently, a 404 from public Git or this repository connector does not
establish that an Epic-authorized browser cannot download the real SDK.
The user's Epic organization membership and authenticated SDK access have
not been verified. Joey's particular fork may have additional restrictions.

Before extending the reconstructed SDK, check the normal authorized route:

1. Follow Epic's [official GitHub source-access steps](https://www.unrealengine.com/en-US/ue-on-github),
   linking the intended GitHub account and accepting the organization invite.
2. Confirm that the authenticated account can open `EpicGames/UnrealEngine`.
3. Open [Joey SDK at the exact required commit](https://github.com/joeyhodge/UESDK/tree/3cffbc82429b6165ceec2714f0f0d9ae48f55596).
4. If accessible, download that revision and validate its provenance before
   running the unchanged latest Joey baseline build. Do not replace it with
   the latest default branch or a different SDK revision.

No matching public source archive was found in the expanded searches. The
matching PDB's named source streams embed a JSON Natvis file, not the SDK
source. The two successful official runs upload runtime binaries and PDBs;
neither advertises an SDK source package. These observations do not rule
out the normal authenticated source-download route.
