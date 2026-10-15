# DuoView v43 — Windows validation checkpoint

Source commit: `ebee6feae18e4dec437ca173b74a67f5fec8f9d5`.
Source tree: `aba6c63f9283c4fc0ff1b652fe98a7421cb8f7ee`.
Branch: `experiments/duoview-gaze-camera-steering-v43`.
Windows run: https://github.com/liviutrn/OpenNR/actions/runs/38649697690

## Verified at checkpoint

- Exact original backend/SDK/frontend pins, guarded source application and generated-source checks passed.
- Pinned production CPU/CAPI/actual compiled raster WARP: 3/3 passed.
- Independent geometry/gaze/frame/config/state/temporal/steering oracle and production WARP: 8/8 passed.
- Complete original Joey compatibility suite: 41/41 passed.
- Total: 52/52 Windows CTest tests passed. Release backend/auxiliary DLLs, matching frontend, strict post-build source verification, CI ZIP/PE audit and independent downloaded-artifact audit ALL PASSED.

This is a documentation-only checkpoint after the tested source commit; no source changes are implied by this later documentation HEAD.

## Implemented mechanism

Tracked gaze rotates the genuine high-resolution camera about the same Mono optical origin while keeping its projection principal point fixed. A matching current-frame perspective homography composites its rays into the canonical Mono image. Fixed-center tracking OFF retains the old projection/camera path. Source pixel counts and atlas allocation remain unchanged. The tracked frustum has constant angular extent, so its projected outline and sampling distribution differ from the old axis-aligned full-image ROI. At eccentric gaze, this can reduce sampling density at the fixation point itself; a representative 32.7-degree horizontal gaze gives about 29% fewer horizontal samples per degree than the old off-axis crop.

A reader-owned sensor timestamp/frame sequence fixes the CAPI false-notification/new-payload ambiguity. Optional fixation guard is one output pixel, with immediate motion outside it. No smoothing, global NGX hook or private UE previous-state write was added.

## Final artifact

- Complete Windows CI: SUCCESS.
- Artifact: [Joey-DuoView-GazeCamera-v43-66](https://github.com/liviutrn/OpenNR/actions/runs/38649697690/artifacts/11935275543).
- Inner ZIP: `Joey-DuoView-GazeCamera-v43-66.zip`.
- ZIP SHA256: `772b5070c3a7d8e7d654daa3d299c8dab2ef535f6a2a09e64a3fcbe4cd2e79a7`.
- Backend DLL SHA256: `bd00c02cd883ed09515bc54a5d3fc63008f4559a59b30fed16cea8e698bf873d`.
- Downloaded outer artifact digest matches GitHub's declared digest. Inner archive digest matches declaration and CI audit; all 14 payload hashes match.
- Five native DLLs verified x64. Eight critical source-header hashes match independently reviewed code (including the intentional generated Config retirement patch).
- The actual backend contains the new gaze-camera UI and compiled homography shader markers, and lacks the obsolete v41 image-shift UI.
- Generated source excerpts show actual source0 output pitch/yaw/roll writes after the original Mono pose is captured. Source1 reads its stored rendered pose; the two source positions remain identical.
- Full independent result: `V43_FINAL_ARTIFACT_AUDIT.json` in this directory.
- Original source-baseline snapshot JSON flags were written BEFORE patching/testing; use final CTest logs for compatibility results. Those early snapshot flags are not final runtime claims.

Normal use: extract into a separate folder, launch `UEVRInjector.exe`, use DuoView Mono ID6 with Eye Tracking ON. Existing original Build3 stays separate.

## Acceptance limits

No STALKER 2/PSVR2 runtime or image-quality acceptance has occurred here. Actual Unreal consumed previous/velocity data have not been captured. A mathematically and CI-validated implementation cannot be represented as a headset-confirmed or bug-free fix. Do not send an intermediate checkpoint build as the final tested artifact.

The earlier `3f70168f` v43 run was superseded/cancelled after the source-backed CAPI fix; use the final run above. v42 `48a9f673` completed full CI successfully but only removed the invalid RGB shift and is not the new gaze-camera implementation.
