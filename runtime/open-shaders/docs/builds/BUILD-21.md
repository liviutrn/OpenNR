# Build 21 — gaze crop and per-pass update, compile corrected

Build 21 contains the full gaze stability, fallback handling, dither, and independent per-pass tuning changes documented in [Build 20](./BUILD-20.md).

## Build 20 packaging failure and correction

Windows package run #20 failed during compilation, so it produced no downloadable package. MSVC warning C4458 reported that local `secondPassCropFallback` variables hid a `State` member. The repository builds with warnings treated as errors.

Build 21 only renames the two local result variables to avoid the shadowing warning. This has no intended runtime or settings behavior change.

## Build and test

[Windows package run #21](https://github.com/liviutrn/OpenNR/actions/runs/36237786454)

After a successful build, test the full set of scenarios listed in [Build 20](./BUILD-20.md): fixation, small gaze motion, saccades and reacquisition, crop padding, both eyes, odd crop ratios, adaptive/static routes, rejected-crop fallback, and per-pass presets with and without pre-upscale NR.

