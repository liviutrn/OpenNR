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
      gbuffer_albedo_eye0_crop00.raw.bin
      gbuffer_normal_roughness_eye0_crop00.raw.bin
      gbuffer_masks_eye0_crop00.raw.bin
      gbuffer_masks2_eye0_crop00.raw.bin
      gbuffer_specular_eye0_crop00.raw.bin
      gbuffer_reflectance_eye0_crop00.raw.bin
```

`sequence.json` records the capture contract and settings snapshot. `frames.jsonl` has
one object per sampled render frame. `sequence_id` plus `frame_id` is unique within the
recording process; `sample_index` is the one-based capture order and `host_frame` is the
Skyrim render-frame counter.

There are two intentional capture roles:

- `dataset_role="sampled_crop_sequence"` keeps the normal low-overhead crop samples and
  may include occasional complete-frame validation artifacts.
- `dataset_role="full_resolution_master_sequence"` writes complete per-eye artifacts for
  every sampled frame and also keeps the configured training crops. This is the preferred
  source recording for later scale-aware training; it does not mean the student should be
  run over the full-resolution frame during training or deployment.

The runtime selects the second role with `capture_full_frame=true` and
`capture_full_frame_sequence=true`. The sequence manifest records the equivalent
`full_frame_capture_policy="every_sample"` value. The older periodic mode remains
available with `full_frame_capture_policy="periodic"`.

Every artifact records its eye, stage (`input`, `input_source`, `teacher`,
`teacher_raw`, `depth`, `motion_vectors`, `gbuffer_albedo`,
`gbuffer_normal_roughness`, `gbuffer_masks`, `gbuffer_masks2`,
`gbuffer_specular`, or `gbuffer_reflectance`), source and
crop rectangles, dimensions, DXGI format, relative PNG/raw paths, row pitch, and write
status. `crop_count` is applied per stage and per eye using the same normalized crop
presets, so input/teacher artifacts remain spatially paired. Normal artifacts are square crops (default 512×512). Periodic validation samples
also contain `full_frame=true` artifacts with the complete per-eye source rectangle.

The optional `capture_renderer_conditionings=true` setting adds the six raw deferred
G-buffer stages listed above at the Neural Rendering call boundary. They use the same
per-eye Feature 18 source rectangle as the input/teacher pair, and the sequence manifest
records the source, alignment, channel names, and unavailable categories. These are
auditable renderer-derived conditionings, not claims of exact teacher history,
lighting-only decomposition, or semantic/object-ID tensors. The probe records per-frame
`renderer_conditionings_requested` and `renderer_conditionings_available` so a missing
render target is visible rather than silently treated as valid conditioning.

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
checked before any staging allocation; if it is full, the due sample is deferred and
retried after capacity returns, so normal queue saturation does not discard a sample or
stall rendering. Runtime diagnostics expose `backpressure_events`; unrecoverable enqueue
failures remain reported as `dropped_frames_before` on later samples.

Validate a completed dataset with:

```powershell
python tools/validate_capture.py D:\OpenNR_Captures
python tools/preview_capture.py D:\OpenNR_Captures --limit 20
```

The validator checks JSON/schema fields, unique IDs and ordering, complete configured
renderer-conditioning crop stages when the opt-in channel is enabled, exact raw byte sizes
for the supported DXGI formats, and file presence. A renderer-conditioned sequence is
not accepted as useful merely because it contains extra files: each frame must record
`renderer_conditionings_requested=true` and a non-empty available-channel list.
stage/eye/crop sets, safe artifact paths, PNG signatures/dimensions/8-bit RGB encoding,
raw byte sizes, duplicate PNG hashes, and all-zero image or tensor data. For a master
sequence it additionally requires every complete frame to contain full-frame input,
teacher, depth and motion resources for each configured eye; renderer conditionings
remain validated at their configured crop size. A non-zero exit code means a required
file, synchronized artifact, or
structural check failed; duplicate or all-zero data are also listed as warnings.

For a temporal training candidate, run the separate contiguous-clip gate after the
normal validator:

```powershell
python tools/validate_temporal_capture.py C:\OpenNR_Captures_Temporal `
  --output out\temporal_audit.json
```

The default gate is the full-resolution master contract. When full-frame
readback cannot sustain contiguous cadence, a separate crop-temporal contract
is available:

```powershell
python tools/validate_temporal_capture.py C:\OpenNR_Captures_Temporal_Crops `
  --mode crop `
  --output out\temporal_audit_crop.json
```

Crop mode requires the same contiguous frame/sample/host ordering, reset and
Feature 18 stability checks, but validates complete non-full input, teacher,
depth, and motion crop resources for both eyes instead of requiring full-frame
artifacts. It does not establish full-frame coverage; keep spatial masters in a
separate master recording.

The temporal gate requires consecutive committed `frame_id`, `sample_index`, and
`host_frame` values, an initial `[true, true]` history reset, no mid-clip reset or
dropped-frame record, stable Feature 18 settings, and complete full-frame input,
teacher, depth, and motion resources for both eyes. It never treats an orphan crash
tail or a missing frame as a valid sample. Passing this gate establishes a usable
clip contract; it does not establish temporal image quality or student equivalence.
