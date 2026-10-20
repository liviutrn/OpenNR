# Build 32 crash evidence

Examined on 20 October 2026. This analysis does not establish that the
runtime crash has been fixed.

## Original evidence

- `UEMinidump(10).dmp`: Windows minidump, 1,826,064 bytes.
- `CrashContext(10).runtime-xml`: Unreal crash report.
- `log(20261020-153726).txt`: UEVR log from the same session.
- Runtime source: `67307ea459f7148c5dec0a7064d7696411c72c69`.

The original files contain machine-specific information and are not
redistributed with source or binaries.

## Confirmed exception context

The minidump exception stream identifies thread 14716 (RenderThread 0),
exception `0xc0000005`, write operation, destination address `0x24`.
The faulting instruction is in the game executable, base
`0x7ff68e590000`, RIP `0x7ff690664037`, RVA `0x20d4037`.

```text
41 80 4a 24 04    or byte ptr [r10 + 0x24], 4
R10 = 0
R9  = 0x1714427200
RSI = 0x3edbc430
RCX = 2
RAX = 3
RSP = 0x3edbc390
```

The dump includes 256 code bytes from `0x7ff690663fb7`. Disassembly
shows a loop over metadata records of four bytes each: a 16-bit data
offset and a type byte at offset two. It dispatches types 10 through
23 using a jump table. Two cases load a non-null pointer parameter,
advance it by `0x38` or `0x40`, then load an indirect pointer into R10
and set its flag byte. The direct-pointer case checks for null.
The faulting indirect pointer was null.

RSI points to `{0x1714427120, 0x8c125c0}`. The second allocation has a
metadata pointer at offset `0x30` and count three at `0x38`; the
fault occurs on metadata index two. The metadata allocation and the
referenced naming information are absent from captured memory.

The structure is consistent with shader/render-graph resource parameter
traversal, including a resource-view parent reference. Without symbols,
the exact Unreal function, resource type, pass and owning view cannot
be established. A null parent does not prove use-after-free, an SDK
layout mismatch, or a specific scene-history failure. The crash XML
reports `MemoryStats.bIsOOM=0`; this is not the earlier device-hung crash.

## Independent, confirmed view-count failure

The source gates `GetDesiredNumberOfViews` on
`quadview_begin_frame().has_value()`, returning either four or two.
Thus per-draw transaction readiness controls the Unreal view count.
The log confirms repeated two-view families while ID7 is selected,
approximately 18:36:07 through 18:36:22, with `readable=false`,
`snap=false`, valid pose, and `RenderFamily rejected: count=2 capacity=2`.

The session also switched 7 -> 6 -> 0 -> 7. Valid four-view production
and two-eye submission resumed after the interruption. The final
logged successful submit is at 18:36:34.584, followed by an exception
handler observation at 18:36:34.593. Temporal proximity does not prove
that view-count changes caused the resource-pointer crash.

## Required interpretation of validation

Preserve atomic GT-before-RT source registration. Exercise stable view
count, generation changes, queued RT/RHI owners and teardown. Do not
skip the exception or advance RIP. CI and WARP can verify contracts and
composition, but cannot demonstrate that this in-game null-resource
crash is resolved. Headset validation must include sustained rendering
and repeated 7 -> 6 -> 0 -> 7 transitions, followed by log inspection.
