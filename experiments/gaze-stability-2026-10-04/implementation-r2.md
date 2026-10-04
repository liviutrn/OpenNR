# v06-r2 implementation and package verification

Runtime source commit: `fc649f65666137047035c644fca010bfcaf05a6d`, on
`build/2.20.1-v06-adaptive-single-pass`.

[Successful Windows build](https://github.com/liviutrn/OpenNR/actions/runs/37241596759).
[Runtime artifact](https://github.com/liviutrn/OpenNR/actions/runs/37241596759/artifacts/11317942540):
`OpenNR-2.20.1-v06-r2-gaze-grid-carrier-excluded`.

## Scope and causal evidence

The user's current r1 version has no flickering or regeneration. The original
OpenNR regenerated/flickered while moving gaze but did not shake. The initial
gaze-history fix removed flicker/regeneration and introduced trembling.
The retained port of that fix is the source reference; the historical binary
alone is not a complete source comparison.

The correction derives display rectangles from integer input rectangles,
aligns color and guides to the same physical positions, supplies cropped SR
camera transforms, removes the model-dependent legacy crop-motion factor,
anchors the reduced moving strict-atlas grid, and reprojects optional
same-pixel stabilization while the crop can move. Genuine invalidations and
ordinary-movement history retention remain. No additional gaze filtering or
deadzone is introduced. See the r2 section of the build branch README and
`scripts/v06/shaking.patch` for implementation details.

The FPS policy, gaze filters, tuning builder, pre-SR code, and native tuning
forwarding are retained. Pre-SR was explicitly excluded from this revision
by the user's latest instruction.

## Verification completed

- Exact r1 source hashes and reproducible patch application.
- World-marker/crop/guide alignment across Performance 2:1 and other ratios.
  The sweep reproduces 4,566 old Performance geometry mismatches.
- Retained model correspondence at 100/85/70%, model/crop changes, flat resize
  parity, and successful-frame history ownership.
- Existing zero-filter, overlap/rejection, controller and transition tests.
- Six CPU/HLSL constant-buffer layouts and six shader compilations.
- Full universal Windows runtime build and both package manifest gates.
- Downloaded ZIP size, published artifact digest, ZIP CRCs and shipped checksums.
- Read/decompressed every inner archive entry; checked x64 PE DLL identity.
- Compared shipped shaders byte-for-byte with reviewed generated source.
- Compared all 634 package entries with the 633-entry r1 package: no removals,
  one added AlignGuidesCS.hlsl, and only the DLL plus SubrectBlendCS.hlsl,
  LadderAtlasGuidesCS.hlsl and ModelResolutionCS.hlsl changed.

The first build caught three unqualified COM pointer declarations; the final
source uses Microsoft::WRL::ComPtr and the complete rebuild passed.

## Integrity

Artifact ZIP: 111,471,957 bytes.
SHA256: `19576f60feb701ff8756b8a646865433f642053dc8d1b705be0338d980ed5d22`.

Inner package SHA256:
`bdf18afd3661e3077943abf1fe2ebd891b0f1514e1b5833112844daa139d76f6`.

CommunityShaders.dll: 26,636,800 bytes.
SHA256: `d91e63ad0036cecf24484c09393c4e0416e105cf2384d00487180beebeb18c98`.

## Remaining acceptance

No headset or in-game devbench verification was available. The confirmed
coordinate errors are corrected, but CPU/build tests cannot certify that
every visible trembling symptom is eliminated in the proprietary runtime.

Install the complete inner archive, including shaders; keep the existing
nvngx_dlssnr.dll carrier. Test Performance SR, zero deadzone/quantization and
zero fixation smoothing, NR disabled versus legacy versus forced one-pass
atlas, all ladder stages, neural tuning, head rotation/translation, crop
growth/shrink, tracking loss and scene cuts. Check the SR base separately
from the NR residual if any trembling remains.
