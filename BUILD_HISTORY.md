# OpenNR build history

This log tracks every package workflow run on `codex/opennr-37769cf`. Each entry records the change, why it was made, the result, and the exact CI run. Successful artifact digests are GitHub's SHA-256 values. GitHub retains workflow artifacts for 14 days.

## Runs

| Run | Change and reason | Result / regression clue | Commit |
|---|---|---|---|
| [#1](https://github.com/liviutrn/OpenNR/actions/runs/36152479480) | Start the installable package workflow. | Failed source verification: the checked-in source patch did not apply cleanly to the upstream shader/runtime files. | [7e7372e](https://github.com/liviutrn/OpenNR/commit/7e7372e) |
| [#2](https://github.com/liviutrn/OpenNR/actions/runs/36153577009) | Retry/trigger the package workflow after the initial setup. | Same source-patch application failure; no compiler/package run. | [cc4f1f6](https://github.com/liviutrn/OpenNR/commit/cc4f1f6) |
| [#3](https://github.com/liviutrn/OpenNR/actions/runs/36154406634) | Fix package source verification. | Failed because the expected source-patch checksum did not match. | [7c5f73c](https://github.com/liviutrn/OpenNR/commit/7c5f73c) |
| [#4](https://github.com/liviutrn/OpenNR/actions/runs/36154631402) | Avoid a patch newline mismatch. | Verification still failed: the published source revision marker was missing. | [eff60be](https://github.com/liviutrn/OpenNR/commit/eff60be) |
| [#5](https://github.com/liviutrn/OpenNR/actions/runs/36154883314) | Validate package inputs before expanding the build. | Configure/package failed in the Streamline runtime CMake setup; no artifact. | [c37b7d3](https://github.com/liviutrn/OpenNR/commit/c37b7d3) |
| [#6](https://github.com/liviutrn/OpenNR/actions/runs/36155908480) | Preserve the local Neural Rendering runtime. | Configure/package failed in FidelityFX runtime setup; no artifact. | [a8a099a](https://github.com/liviutrn/OpenNR/commit/a8a099a) |
| [#7](https://github.com/liviutrn/OpenNR/actions/runs/36155923347) | Attempt a runtime-preserving package build. | Source-contract validation failed during configure/package. | [916e71e](https://github.com/liviutrn/OpenNR/commit/916e71e) |
| [#8](https://github.com/liviutrn/OpenNR/actions/runs/36156030768) | Validate the external-runtime build mode. | Source-contract validation still failed; no artifact. | [82663ef](https://github.com/liviutrn/OpenNR/commit/82663ef) |
| [#9](https://github.com/liviutrn/OpenNR/actions/runs/36156740437) | Skip the external carrier size check when it does not apply. | A later source-contract validation check still failed; no artifact. | [9756e0f](https://github.com/liviutrn/OpenNR/commit/9756e0f) |
| [#10](https://github.com/liviutrn/OpenNR/actions/runs/36157315335) | Remove a stale UI contract. | C++ compile failed with an unmatched brace in `FoveatedRender.cpp` (C1075). | [e44f077](https://github.com/liviutrn/OpenNR/commit/e44f077) |
| [#11](https://github.com/liviutrn/OpenNR/actions/runs/36161591869) | Close the sequential NR scope. | Build succeeded, but upload failed because the expected artifact directory was empty. | [c773f29](https://github.com/liviutrn/OpenNR/commit/c773f29) |
| [#12](https://github.com/liviutrn/OpenNR/actions/runs/36165022096) | Upload from the preset's actual build directory. | **Success.** Artifact `OpenNR-2.15.1-37769cf`; SHA-256 `084b053a8a231d76b263e02ff9a5575c272fe2e09d04a302a1bb0a2a8c425773`; expires 2026-10-09 17:33 UTC. | [b65efb4](https://github.com/liviutrn/OpenNR/commit/b65efb4) |
| [#13](https://github.com/liviutrn/OpenNR/actions/runs/36165473926) | Stage the package in the directory expected by artifact upload. | **Success.** Artifact `OpenNR-2.15.1-37769cf`; SHA-256 `ca8cf16aca2d6fde9c7aea479b13f16eda0010209c034390f6e21742969baf3c`; expires 2026-10-09 17:43 UTC. | [6eedcec](https://github.com/liviutrn/OpenNR/commit/6eedcec) |
| [#14](https://github.com/liviutrn/OpenNR/actions/runs/36180301944) | Add adaptive NR resolution, crop, and pass controls. | Compile failed: settings macro referenced undeclared fields and had malformed syntax. | [4fa4731](https://github.com/liviutrn/OpenNR/commit/4fa4731) |
| [#15](https://github.com/liviutrn/OpenNR/actions/runs/36190546520) | Stabilize native gaze crop and settings; account for the extra NR pass in adaptive FPS. The added-pass estimate is configurable (0–15 ms, 6 ms default when multipass is enabled). | **Success.** Artifact `OpenNR-2.15.1-37769cf`; SHA-256 `cd134ac60d0bd49dd4dad57bb19012b37f2ff5d7eaa3321ec04750fec40df12a`; expires 2026-10-09 21:49 UTC. | [a3e1f0a](https://github.com/liviutrn/OpenNR/commit/a3e1f0a) |
| [#16](https://github.com/liviutrn/OpenNR/actions/runs/36194756138) | Add a second-pass stability blend preset (0.65) to reduce instability in multipass NR. | **Success.** Artifact `OpenNR-2.15.1-37769cf`; SHA-256 `350648d79592506f41a6900f91ef57eed9e651c2833b0c87b7ce44f46841dff2`; expires 2026-10-09 22:36 UTC. | [04dc9d7](https://github.com/liviutrn/OpenNR/commit/04dc9d7) |
| [#17](https://github.com/liviutrn/OpenNR/actions/runs/36227698812) | Add one-eye stereo NR: evaluate the anchor eye, then depth-reproject its NR residual to the other eye. | Compile failed on an unused `sourceTeacher` local (MSVC C4189 treated as error); fixed in #18. | [039a1f1](https://github.com/liviutrn/OpenNR/commit/039a1f1) |
| [#18](https://github.com/liviutrn/OpenNR/actions/runs/36229221798) | Remove the unused stereo fallback resource so the one-eye change passes the warning-as-error build. | **In progress** when this log was written; artifact and final result pending. | [fc837b6](https://github.com/liviutrn/OpenNR/commit/fc837b6) |

## Future run entries

For every package run, add one row with:
- what changed and why;
- the workflow result and the failing step/error if it failed;
- commit link and run link;
- artifact name, SHA-256 digest, and expiry if it succeeded.

Keep failed attempts in the log. They are useful regression evidence and explain why the next build changed.
