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
- Total: 52/52 Windows CTest tests passed. Release backend/auxiliary DLL compilation is in progress; frontend/package/independent downloaded-artifact audit remain pending.

This is a documentation-only checkpoint after the tested source commit; no source changes are implied by this later documentation HEAD.

## Implemented mechanism

Tracked gaze rotates the genuine high-resolution camera about the same Mono optical origin while keeping its projection principal point fixed. A matching current-frame perspective homography composites its rays into the canonical Mono image. Fixed-center tracking OFF retains the old projection/camera path. Source pixel counts and atlas allocation remain unchanged. The tracked frustum has constant angular extent, so its projected outline and edge sampling distribution differ from the old axis-aligned full-image ROI.

A reader-owned sensor timestamp/frame sequence fixes the CAPI false-notification/new-payload ambiguity. Optional fixation guard is one output pixel, with immediate motion outside it. No smoothing, global NGX hook or private UE previous-state write was added.

## Acceptance limits

No STALKER 2/PSVR2 runtime or image-quality acceptance has occurred here. Actual Unreal consumed previous/velocity data have not been captured. A mathematically and CI-validated implementation cannot be represented as a headset-confirmed or bug-free fix. Do not send an intermediate checkpoint build as the final tested artifact.

The earlier `3f70168f` v43 run was superseded/cancelled after the source-backed CAPI fix; use the final run above. v42 `48a9f673` completed full CI successfully but only removed the invalid RGB shift and is not the new gaze-camera implementation.
