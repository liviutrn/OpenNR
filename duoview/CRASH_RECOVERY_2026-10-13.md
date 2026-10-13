# Crash recovery — 2026-10-13

The compiled public-backend build `bd74b21` / run `38316421524` crashed on injection. It is superseded for runtime experiments by the Joey-preserving plugin in `duoview/joey_plugin` and workflow `duoview-joey-plugin.yml`. Existing geometry, gaze, frame policy, DX12 compositor and WARP tests are preserved.

Both supplied minidumps were parsed directly using their ModuleListStream. Both contain the failed public-backend `UEVRBackend.dll` image (11,997,184 loaded bytes), CheekyFoveatedDLSS.dll, CheekyFoveatedDLSSRuntime.dll and CheekyOpenXRLayer.dll. The first additionally contains ReShade64.dll; the second does not. Both report UE5.5.4 `PresentInternal` E_ABORT (`0x80004004`). The repeated crash without ReShade means ReShade is not a necessary condition for this observed failure. It does not prove Cheeky or UEVR is the cause. Original machine-specific crash files have not been committed publicly.

The replacement preserves the official latest Joey Mono release binary byte for byte and builds only an adjunct plugin against public API headers. It does not compile a substitute UESDK, edit main, or fabricate private headers. There are four startup modes: diagnostics, same-pose full views, fixed foveal atlas/composite, and Toolkit gaze. Stage 0 deliberately makes no renderer hooks; later stages require the exact inspected DLL hash and isolate Cheeky/ReShade layers.

Release pin and disassembly evidence: `joey_plugin/BINARY_ADAPTER.md`. Exact binary-contract verification passed locally. Windows compilation and game validation must be recorded with actual run results; implementation alone is not a successful crash fix.
