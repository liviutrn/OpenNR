# OpenNR-VR capture format

The capture feature is an opt-in tap around the in-process Open Shaders Feature 18
renderer. It copies the per-eye GPU texture before evaluation and the per-eye teacher
texture after evaluation/resolve. It does not inspect the desktop, mirror window, or
presented swap chain.

Each recording creates a directory under the configured output directory:

```text
OpenNR_Captures/
  seq-<timestamp>-<serial>/
    sequence.json
    frames.jsonl
    frames/frame_00000001/
      input_eye0_crop00.png
      input_eye0_crop00.raw.bin
      teacher_eye0_crop00.png
      teacher_eye0_crop00.raw.bin
      depth_eye0_crop00.raw.bin
      motion_vectors_eye0_crop00.raw.bin
```

`sequence.json` records the capture contract and settings snapshot. `frames.jsonl` has
one object per sampled render frame. `sequence_id` plus `frame_id` is unique within the
recording process; `sample_index` is the one-based capture order and `host_frame` is the
Skyrim render-frame counter.

Every artifact records its eye, stage (`input`, `input_source`, `teacher`,
`teacher_raw`, `depth`, or `motion_vectors`), source and
crop rectangles, dimensions, DXGI format, relative PNG/raw paths, row pitch, and write
status. `crop_count` is applied per stage and per eye using the same normalized crop
presets, so input/teacher artifacts remain spatially paired. Normal artifacts are square crops (default 512×512). Periodic validation samples
also contain `full_frame=true` artifacts with the complete per-eye source rectangle.

If a queued GPU query times out or fails, the worker still appends a `status="failed"`
frame record with `failure_reason`, so missing data is distinguishable from an
unrecorded render frame.

PNG files are 8-bit RGB and encoded losslessly. For 8-bit source textures this is a
lossless channel-order conversion; for float/16-bit sources the exact mapped bytes are
also kept in `.raw.bin`, while the PNG is a lossless encoding of a derived RGB8 view.
Depth and motion-vector artifacts are intentionally raw-only so their signed/float
components are never quantized into an image preview. Their `format_name`, packed
dimensions, row pitch, crop rectangle, and raw path are recorded per artifact.

Each frame also records the exact guide dimensions, per-eye `MVecScaleX/Y` values,
per-eye Feature 18 history-reset state, and the active teacher tuning controls. These
describe the resources actually bound as `DLSSNR.Depth` and `DLSSNR.MVec`; no optical
flow is estimated by the capture feature.

The render thread only issues GPU copies and an event query. The writer thread waits for
the query, maps staging textures, compresses PNGs, and appends JSONL. A bounded queue is
checked before any staging allocation; if it is full the frame is dropped and rendering
continues. Queue drops are reported by runtime diagnostics and as `dropped_frames_before`
on later samples.

Validate a completed dataset with:

```powershell
python tools/validate_capture.py D:\OpenNR_Captures
python tools/preview_capture.py D:\OpenNR_Captures --limit 20
```

The validator checks JSON/schema fields, unique IDs and ordering, complete configured
stage/eye/crop sets, safe artifact paths, PNG signatures/dimensions/8-bit RGB encoding,
raw byte sizes, duplicate PNG hashes, and all-zero image or tensor data. A non-zero exit
code means a required file, synchronized artifact, or structural check failed;
duplicate or all-zero data are also listed as warnings.
