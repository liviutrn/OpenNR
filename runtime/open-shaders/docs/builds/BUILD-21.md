# Build 21 — gaze crop and per-pass update, compile corrected

Build 21 contains the full gaze stability, fallback handling, dither, and independent per-pass tuning changes documented in [Build 20](./BUILD-20.md).

## Build 20 packaging failure and correction

Windows package run #20 failed during compilation, so it produced no downloadable package. MSVC warning C4458 reported that local `secondPassCropFallback` variables hid a `State` member. The repository builds with warnings treated as errors.

Build 21 only renames the two local result variables to avoid the shadowing warning. This has no intended runtime or settings behavior change.

## Build and test

Windows package run #21 succeeded, including the configure/package and upload steps. The artifact is `OpenNR-2.15.1-37769cf.zip` (110,877,420 bytes), retained until 2026-10-10 11:40 UTC. [Open the workflow run and download the artifact](https://github.com/liviutrn/OpenNR/actions/runs/36237786454). SHA-256: `07415b14eff70e5069e8472579c0f1d963a65a3eddd1e9952d9ed24fe061988f`.

The successful build confirms compilation and packaging; gameplay behavior still needs runtime testing. Test the full set of scenarios listed in [Build 20](./BUILD-20.md): fixation, small gaze motion, saccades and reacquisition, crop padding, both eyes, odd crop ratios, adaptive/static routes, rejected-crop fallback, and per-pass presets with and without pre-upscale NR.

