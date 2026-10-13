# DuoView clean restart — current handoff

Updated: 2026-10-13. Continue actual work; keep token consumption low.

## Goal and immediate gate

Liviu wants a clean rebuild of his smooth latest Joey Mono baseline before any DuoView integration. DuoView will eventually repurpose the working two native rendering views as high-resolution gaze-following fovea plus lower-resolution periphery, using Mono. Earlier mixed-version implementations hitched in every mode, including ordinary Mono/stereo. Do not reuse that mixed backend or substitute an older SDK. First compile the unchanged original sources, verify the package, and let Liviu test baseline stability.

## Authoritative location

- Repository: https://github.com/liviutrn/OpenNR
- Branch: `experiments/duoview-joey-current-clean-v1`
- Build-trigger commit: `64432d0442066715fa442660a0848cf4963640b0`
- Successful Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38453012351
- Job: `115488463072`; run number 3.
- Workflow: `.github/workflows/duoview-exact-joey-baseline.yml`.
- Inspect the current branch head before writing: API commits may be newer than local Git HEAD. Use expected-SHA leases on updates.

## Exact original source pins

Latest release was rechecked on October 13: `101226HELLRAISERp1`.

| Component | Repository | Commit |
| --- | --- | --- |
| DIBR-capable backend containing original Mono | joeyhodge/UEVR | `5ac7edc207866569334175e4ed8a7517971547f6` |
| Original restricted SDK | joeyhodge/UESDK | `3cffbc82429b6165ceec2714f0f0d9ae48f55596` |
| Matching injector/frontend | joeyhodge/uevr-frontend | `60be4b0f9a646109fd9fdf448bacd41477234091` |

SDK tree: `c958569565e435c8670caec726eece63ac7c317b`. All 176 SDK files were retrieved through the authorized GitHub connector and checked against their Git blob hashes; tree and commit identities were reproduced. All previously missing headers and tests are present. SDK reconstruction is paused and excluded from the build. Native Stereo is ID 0; original Mono is ID 5. Selecting Mono does not run DIBR reconstruction.

Official smooth DIBR DLL SHA-256: `19e91cc8c22a02e2a97996e1523604ab202b4540d954ebc95e07e6b233970966`. `baseline.lock.json` records the exact packages, pins and reference evidence. A fresh source build is not promised to be byte-identical to the release DLL.

## Authorization and CI

User joined Epic's GitHub organization, unlocking SDK access. First exact build run `38448199737` failed at SDK checkout because Actions needed separate credentials. User now reports adding repository Actions secret `UEVR_SOURCE_TOKEN` from his authorized account; run `38450034680` successfully checked out the exact SDK. Never print or retrieve the token. Never commit restricted SDK source into public OpenNR. CI fetches the source privately and archives binaries/logs/provenance only.

Workflow builds on Windows 2022, checks out the three exact commits, initializes their pinned public submodules, and runs `verify_exact_baseline.py`. It builds/runs all original registered compatibility tests, then `uevr`, `vr-plugin-nullifier`, `LuaVR`, and the matching frontend. Final source verification precedes packaging.

Frontend's original build deterministically regenerates tracked `UEVR/FilteredExecutables.json`. The verifier permits ONLY that expected regenerated text (hashes derived from unchanged original plaintext input), rejects all other tracked changes and untracked nonignored files. Original publishing mode is retained (`SelfContained=false`); no forced publishing change. Local source checks passed, including acceptance of the correct generated resource and rejection of an altered resource. Windows compilation succeeded in run `38450034680`; the corrected run `38453012351` also passed package verification. Headset stability remains untested.

That run compiled all original targets, passed all **41 registered tests**, compiled backend/auxiliary DLLs, passed frontend ID tests and published the matching frontend. Final packaging stopped at the strict untracked-files gate. Original `tests/ProSpiCameraTraceAnalyzerTests.py` imports the analyzer, creating `tools/__pycache__/analyze_prospi_camera_trace.cpython-*.pyc`. Locally reproduced that artifact, then verified original analyzer tests and the source gate pass with `PYTHONDONTWRITEBYTECODE=1`. The current workflow sets that environment variable globally; the verifier now reports offending paths. Original source and compatibility checks remain unchanged. Failed-run evidence artifact: `11840404431`, digest `b1cae50e4ba6561a382627ac48bc9c2c35e0a622bc9a018823c6022ba7a9c658`.

The corrected run succeeded: all 41 tests, original backend/auxiliary/frontend compilation, frontend ID checks, final source guard and packaging passed. Both ZIP layers and all package file hashes were independently verified after download.

## Delivered build and next actions

- Download: https://github.com/liviutrn/OpenNR/actions/runs/38453012351/artifacts/11842620175
- Outer artifact SHA-256: `979b6e2560e19c04c8052e58266b4709c9d7917fdfe46e07c15dbf6ad9308b70`.
- Nested installable ZIP: `Joey-101226-Clean-Baseline-Build-3.zip`.
- Installable ZIP SHA-256: `80a09a741f4ccbe4e53400c379058ed227b5a424e873d60c64a1eda8c908e2c8`.
- Rebuilt backend SHA-256: `339b88dcae20c808ed618791bed1fdb1ab41ea0d5dd10416dbe34d84b2db131f`.
- Evidence artifact: `11842068138`, SHA-256 `2b001ddab6f71c6649355e7d4522d16d8dc3feb988433d09159c707bae4cbbdb`.
- Package has 11 files, including injector EXE, backend, OpenVR/OpenXR loaders, LuaVR and nullifier DLLs, source lock/identity and instructions. ZIP CRCs, published archive digests, individual package hashes and source pins are verified. See `BASELINE_BUILD_VERIFIED.json`.
- This is an unchanged-source rebuild, not a promise of byte-identical official release DLL output. The source audit JSON retains a conservative `full_backend_compatibility_verified=false` default because it verifies source only; complete build/test results are recorded separately in run evidence and `BASELINE_BUILD_VERIFIED.json`.

1. Liviu extracts the outer artifact ZIP, then the nested installable ZIP into its own folder. Launch `UEVRInjector.exe` with his usual working runtime/settings and test **original Mono (ID 5)** in Stalker 2 against official smooth Joey. Native Stereo remains ID 0 if he also wishes to compare it. No diagnostic overlays or additional plugins are required for this stability check.
2. Wait for his baseline stability result. Passing offline tests does not prove headset stability. If it hitches, investigate differences between the exact-source rebuild and official binary before adding DuoView.
3. If stable, proceed from this exact source baseline to DuoView. Audit two-view creation, per-view projection/resolution, common camera state, temporal history per view, gaze updates, composition and GPU lifetime/frame handoff. Keep ordinary Mono/native paths intact; do not transplant the older mixed-version backend. Do not implement speculative Unreal offsets or SDK substitutes.
4. Update the handoff as work advances. SDK acquisition/reconstruction is solved; do not spend another chat searching for the SDK.

Other repository Actions workflows may fail at parsing inherited unrelated OpenNR workflows; inspect this named baseline workflow rather than counting every repository run as its result.

## User constraint

Liviu initially reported 22% account allowance remaining, then 18% at 22:08 Bucharest time then 12% at 22:25, and now asks for a handoff at 5%. The assistant cannot read that account meter. Keep output and monitoring economical, persist current state here, and do not launch unnecessary investigations or agents. GitHub API tools support fetch, file/blob fetch, tree/commit creation, expected-SHA ref update, job steps/logs and artifact downloads. No workflow_dispatch or secrets management tool is exposed; a meaningful workflow/verifier change can trigger a new push run. Do not rerun the obsolete earlier workflow revision.
