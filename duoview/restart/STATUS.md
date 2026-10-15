# Build3 restart checkpoint

This branch starts from OpenNR `64432d0442066715fa442660a0848cf4963640b0`, the
exact Build3 source pin. Provenance references:

- Baseline workflow run: `38453012351`
- Baseline artifact: `11842620175` (`Joey-101226-Clean-Baseline-Build-3.zip`)
- Backend: `joeyhodge/UEVR@5ac7edc207866569334175e4ed8a7517971547f6`
- SDK: `joeyhodge/UESDK@3cffbc82429b6165ceec2714f0f0d9ae48f55596`
- Frontend: `joeyhodge/uevr-frontend@60be4b0f9a646109fd9fdf448bacd41477234091`

The prior v48 and v49 runs both fell back to Mono. Neither is evidence about
moving-gaze stability. The original Mono path remains the default.

## This checkpoint

`DuoViewRestartDiagnostics.hpp` supplies deterministic producer-frame replay,
valid-left-half source UV mapping, and a fixed-capacity single-producer /
single-consumer observation ring. `tests/replay_tests.cpp` exercises invalid
inputs, replay patterns, left-half edge clamping, ring wrap/full/drop/order,
concurrent producer-consumer traffic, and producer-boundary effective-path
classification. The core is portable and does not claim rendering behavior.

On the Linux workspace, the replay test passed a direct GCC build with
`-O2 -DNDEBUG -Wall -Wextra -Werror -pthread`. The independent review also ran
the Release configuration and ASan/UBSan successfully (LSAN was disabled in
that sandbox). The local environment does not provide CMake or a Windows/D3D12
runtime, so these results do not validate the backend GPU path.

## Experiment limits

The intended first renderer control is a single stable full-frustum Mono image
used for both outputs, with a replay-driven mask selecting full-detail samples
inside the mask and coarser samples from that same source outside it. This is a
diagnostic image-processing control: it saves no scene-render work and is not
DuoView or two independent engine views. A real identical-two-engine-view
comparison remains gated on proof of distinct engine-owned view state and an
independently-owned shading/history consumer.

The renderer-side D3D12 control is still under review and is not integrated or
available in this checkpoint. No headset, STALKER 2 runtime, or PSVR2
observation has been made in this environment.
