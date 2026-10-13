# DuoView clean restart: current Joey baseline

**Current status:** the original required SDK is now accessible and its
complete source has been verified against the exact Git blobs, tree and
commit. The unchanged latest Joey baseline build is being prepared with
the original SDK. No new installable baseline or DuoView build is available yet.

The exact-source workflow is `.github/workflows/duoview-exact-joey-baseline.yml`.
It pins the original backend, SDK and frontend, runs the complete original
compatibility suite and packages only after all source/build gates pass.
Its restricted SDK checkout uses the existing Actions secret
`UEVR_SOURCE_TOKEN` (or `PAT_TOKEN`) when configured.

This branch starts the source restart using the exact official Joey DIBR
backend the user reported smooth. No new DuoView renderer is enabled here.
The existing old `duoview/` implementation is historical reference only; this
workflow neither applies its patches nor compiles it.

## Corrected provenance

The supplied handoff incorrectly called hash `19e91cc8...` a normal Joey
backend. GitHub's release digests and direct ZIP inspection identify it as
the **DIBR-capable** asset in `DIBRMONOUEVR.zip` from release
`101226HELLRAISERp1`. The ZIP stores it under the regular filename
`UEVRBackend.dll`, which likely contributed to the confusion.

The official DLL embeds both backend commit
`5ac7edc207866569334175e4ed8a7517971547f6` and SDK commit
`3cffbc82429b6165ceec2714f0f0d9ae48f55596`. Its SHA-256 is
`19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`.
The normal official DLL is a distinct asset with SHA-256
`ecdaea840b249ac1894775e2ec5667307b2adcad545843660e5d3edad350e08c`.
The normal tag points to `387ccb...` and pins SDK `e667df...`; neither is
the source identity of the smooth DLL identified by the handoff.

The latest release was rechecked on October 13, 2026. Matching original
frontend branch `uevr-dibr-optin-safe` resolves to `60be4b0...`; it is pinned
without changing its rendering IDs. Native Stereo remains 0 and Mono 5.

The normal release source at `387ccb...` lists only Native Stereo (0),
Synchronized Sequential (1), and Alternating/AFR (2). It has no Mono mode.
Direct DLL inspection also finds the Mono label only in the DIBR+Mono
package. The Mono branch's `non_dibr_choices` describes a potential build
option; it is not evidence that the normal release contains Mono.
The chosen baseline includes DIBR capability but DuoView extends **Mono**,
which does not run DIBR depth reconstruction. The user accepted this choice.

## Baseline blocker and diagnostic build

`joeyhodge/UESDK` remains inaccessible (GitHub connector HTTP 404). The exact
SDK commit was not found in the accessible `elliotttate/UESDK-RenderDoc`
repository. Public source searches found no matching source for the first
missing compatibility headers. The pinned July public SDK lacks 15 headers
directly included by the current backend and its tests. This is a minimum
gap count, not a complete SDK API/behavior audit.

The CI workflow:

1. Downloads both official release packages and DLLs, verifies all hashes,
   ZIP CRCs, packaged/standalone identity, and DIBR embedded commit strings.
2. Checks out the entire current Joey backend at the smooth DLL's exact
   source commit, unchanged. It records exact SDK access results.
3. Uses the explicitly labelled public SDK **for compatibility diagnostics**,
   records missing headers and hashes every tracked backend file.
4. Builds and runs original Joey Mono DX11/DX12 WARP and STALKER 2 policy/
   DX12 WARP tests in an independent harness, plus matching frontend ID
   tests. These test existing graphics/lifetime policies; they do not
   exercise full Unreal injection or the headset. The full upstream test
   suite remains blocked by missing SDK test sources.
5. Attempts a complete current backend build to collect compiler evidence.
   An SDK failure fails the job; missing interfaces are not silently stubbed
   or disabled. Matching frontend/package build is gated on backend success.
6. Saves exact current source snapshots, dependency IDs and compiler logs,
   including after a failed build. A successful diagnostic package would
   still be labelled as adapted SDK, with no headset stability claim.

First run `38434181805` verified official release evidence. Its source job
failed at CMake generation because the public SDK also lacks
`tests/DiscoveryValidationTests.cpp` (and `LayoutSafetyTests.cpp` is another
required source). The independent harness avoids changing Joey source;
the full diagnostic backend configure uses the production default
`UEVR_BUILD_COMPATIBILITY_TESTS=OFF` to reach actual backend compilation.
This switches off test target generation only, not runtime compatibility.

The separate CPU-only driver invokes Joey's unchanged Mono policy tests:
4,769 assertions passed with zero failures locally. See
`SDK_GAP_AUDIT.md` for exact gaps, original frame behavior, test scope and
reproduction instructions. This is not a complete source rebuild or a
headset test.

## Completed verification

| Check | Result | Evidence |
| --- | --- | --- |
| Both official release ZIPs and DLLs | All four SHA-256 hashes and package checks passed | Run `38435076991`, official asset archive `11832084328` |
| Original Mono CPU policy | 4,769 assertions, zero failures | Local GCC C++23 execution of unchanged Joey tests via `offline/MonoPolicyMain.cpp` |
| Original Mono DX11/DX12 and STALKER 2 policy/DX12 WARP | All four tests passed | Run `38435425509`, job `115431979148` |
| Original injector rendering IDs | Passed | Same successful offline job; artifact `11833881205` |
| Complete current Joey + diagnostic public SDK | Failed; no installable backend | Run `38435076991`, job `115426842595`, compiler/source artifact `11833226728` |
| Rebuilt baseline in headset | Not available/tested | Requires complete SDK compatibility first |

The successful offline-only run deliberately skipped the already-verified
asset archive and the failed full backend job. Its green result is **not**
a complete baseline build. Backend runtime source is identical across both
verification runs. Documentation-only commits use `[skip ci]`; a harness
correction may use `[offline-only]` to rerun only the affected test job.

Compiler evidence archive SHA-256:
`8f158f4cea170ff64abff1b2d4cc81214baa0eec28b2454a92c06c7de6247879`.
It contains full configure/build logs, exact source ZIPs, source hashes,
SDK access results and submodule revisions. See the
[full source diagnostic run](https://github.com/liviutrn/OpenNR/actions/runs/38435076991)
and [successful offline tests](https://github.com/liviutrn/OpenNR/actions/runs/38435425509).

## Frozen historical evidence

- v14 run `38426715379`: completed successfully; headset result unknown.
- Old exact Mono-only control run `38431096553`: completed successfully;
  release `duoview-mono-only-control-build-3` now exists. ZIP SHA-256:
  `39713c5dc73c3aed8a26bd40608908f60871599e0b4dd4e16b0f140edad6ab38`.
- Original integrated foveation remains user-confirmed; sustained stability
  remains unconfirmed. Old experiment branches and releases are unchanged.

## Next engineering gate

The authenticated source-download gate has now passed. All 176 SDK files,
the SDK tree `c958569565e435c8670caec726eece63ac7c317b`, and the original commit
object `3cffbc82429b6165ceec2714f0f0d9ae48f55596` have been verified.
The missing-header inventory is empty and both missing SDK test sources
are present. See `SDK_SOURCE_VERIFIED.json`.

Use the original SDK for the complete baseline build. The reconstruction
experiment is retained as evidence only and is not integrated.

The prior fallback gate, retained for provenance, was:

Obtain authentic SDK source matching `3cffbc...`, or recover bounded public
implementations for every required interface with source/binary evidence
and tests. Audit behavior changes, not only declarations or successful
compilation. No guessed Unreal vtables/offsets, no compatibility removals to
make the build green. A public SDK adaptation cannot be called the original
Joey build.

Only after the rebuilt baseline passes Native Stereo and Mono on the user's
STALKER 2 scene without SteamVR takeovers may DuoView integration start.
Preserve original XR lifecycle and modes; integrate two same-pose UE views
internally, first with a fixed fovea, then add PSVR2 gaze. This branch does
not request another experimental foveation headset test.

## SDK recovery checkpoint

The exact official DLL's matching PDB was recovered from Joey's successful
run `38150970046`, artifact `11707171949`. Both the release DLL SHA-256 and
the PDB GUID/age were verified. This provides authentic current SDK type
contracts and machine-code locations; it does not recover the original source.

The first isolated memory module has been reconstructed from that evidence.
Windows run `38442752728` passed 52 checks with zero failures, including
differential tests against the original compiled helpers. It is not integrated
into the backend, and no full SDK/full backend build is available yet.

See [exact SDK recovery](sdk_reconstruction/README.md) for the original
artifact identities, implementation, test scope and remaining dependency gates.
