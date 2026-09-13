# Full-resolution spatial training input

The September 4 preparation uses `tools/audit_master_capture.py`,
`tools/prepare_master_dataset.py`, and `tools/master_dataset.py`. It keeps the
native capture files immutable. Training references point at the full-frame
masters; no image/tensor repair is written into the source directories.

## Reproduce preparation

Use `E:\OpenNR-VR-Poc-Venv\Scripts\python.exe` from the project root:

```powershell
python tools/audit_master_capture.py C:/OpenNR_Captures_FullRes_Pilot_20260904 out/fullres_audit_20260904 --workers 3
python tools/prepare_master_dataset.py out/fullres_audit_20260904
python tools/test_master_audit.py
python tools/test_master_dataset.py --manifest out/fullres_audit_20260904/training_manifest.jsonl
```

The exhaustive audit is expensive: it reads every referenced raw/PNG file,
verifies PNG decoding and CRCs, compares decoded RGB to raw bytes, compares every
native crop with its full master, calculates SHA-256, and checks finite guide
values. An orphan is hashed and inventoried but is never reconstructed as a
training sample without its committed frame metadata. Inspect `summary.json`
and `prepared_summary.json`; the original dataset may contain failures even
when preparation successfully salvages its valid subset.

## Consume the prepared data

```python
import sys
sys.path.insert(0, 'D:/.CODEX_Projects/OpenNR-VR/tools')
from master_dataset import MasterPatchDataset
dataset = MasterPatchDataset(
    'D:/.CODEX_Projects/OpenNR-VR/out/fullres_audit_20260904/training_manifest.jsonl',
    split='train', patch_size=512, patches_per_eye=4)
sample = dataset[0]
# Float tensors in CHW layout: input, teacher, depth, motion.
# Masks: color_valid, depth_valid, motion_valid.
# Identity: sequence_id, frame_id, eye, box, history_reset.
```

The JSONL is a source-backed dataset, not a copied image cache. The reference
loader favors correctness and auditability over throughput; it decodes the
full color PNGs and samples the native guide tensors for each patch. Cache
derived patches on C: or E: before a long run if data loading becomes the
bottleneck. Do not fill the project D: drive with another full capture copy.

Input and target are native RGB8 UNORM divided by 255, with no assumed sRGB or
linear-light reinterpretation. Full eye color is 2496x2688; depth and motion
are 1664x1792. Native depth stays in its captured [0,1] representation, without
claiming metric distances. The loader uses color pixel-center coordinates to
sample both lower-resolution guides with `align_corners=False`.

The existing 512x512 color crops and 512x512 guide crops span different fields
of view and cannot be stacked directly. The old POC crop index does that, so
its guided-vs-RGB results are not a clean guide usefulness experiment. Its
index also takes both scalar motion values from `motion_vector_scale_x`
instead of selecting X and Y for the requested eye. The new reader selects
`motion_vector_scale_x[eye]` and `motion_vector_scale_y[eye]` separately.
Historical checkpoints and their original readers are retained for provenance;
do not use `train_opennr_poc.py` directly on the new capture tree as the final
guided training path.

The new motion representation is an explicitly bounded *spatial feature*:
mask nonfinite values and native components beyond ±0.25; apply per-eye scale;
convert guide-grid pixel displacement to color-grid displacement; clip to ±128
color pixels and divide by 128. The outlier threshold is conservative policy,
not proof every excluded finite value is corrupted. Invalid values carry a
mask; interpolation cannot silently spread them into apparently valid guides.
Motion direction, jitter convention, occlusion and temporal reprojection remain
uncalibrated. No flow across skipped render frames is fabricated.

## Split and loss contract

Both eyes and all patches from one frame/sequence remain together. Process 2
is test; the final four sequences from process 1 are validation, and the two
preceding sequences form an unused guard band. Exact duplicate stereo-color
samples are excluded. This is a reproducible process/sequence holdout, not a
verified location/character-disjoint benchmark. Repeated environments can
cross the boundaries. Freeze the split before tuning models and do not select
checkpoints on the test set.

Use the same color inclusion policy and examples for the identity, RGB-only,
RGB+depth and RGB+depth+motion comparisons. Mask guide inputs explicitly;
include guide validity channels if the architecture supports them. Report
per-sequence and per-eye metrics, not only a mean over correlated crops.
Teacher agreement measures imitation, not perceptual superiority.

The completed Student v1 experiment includes all RGB pixels for both loss and
evaluation, including black pixels, rather than using the reference loader's
optional color mask. See `STUDENT_V1_RESULT_20260904.md` for the additional audited
supplemental training data, frozen test results and measured runtime.

## Next experiment

1. Train a small single-pass residual student on native 512x512 aligned targets,
   with a 128x128 or 256x256 compute path and a full-resolution RGB skip. Compare
   identical RGB-only and guide-assisted runs; never repeatedly apply a
   checkpoint trained for one pass.
2. Use fixed validation patches for checkpoint selection, then evaluate the
   frozen test session once. Include full-frame stereo results at native
   resolution, faces, fine clothing/hair, low-light areas and landscape detail.
3. Measure warm *stereo* inference including reconstruction, memory transfers
   and compositing. The model budget must fit the remaining renderer budget;
   the entire 90 Hz frame is about 11.1 ms. Earlier full-resolution POC timing
   was around 244 ms for sequential stereo, so that architecture/compute scale
   is not an accepted deployment baseline.
4. For a temporal model, collect genuinely contiguous short clips with stable
   resets and calibrated native MV direction/scale, then add exposure/jitter
   and XR camera metadata. Sampled captures at 1 Hz and burst recordings with
   queue gaps do not replace this data. Preserve the spatial masters as
   pretraining material.

The preparation smoke test exercises finite tensors, alignment, masks, and one
optimizer step. It does not produce a trained checkpoint or imply final image
quality, stereo comfort, headset delivery, or crash resolution.
