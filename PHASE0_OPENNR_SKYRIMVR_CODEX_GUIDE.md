# OpenNR-VR — Phase 0 Codex Implementation Guide

## Purpose

Phase 0 exists to answer one question:

> Can we reliably capture synchronized Skyrim VR rendering data immediately before and after DLSS 5 Neural Rendering, in a form suitable for later black-box distillation?

Implementation status: the M0.2 capture feature is now present in the pinned teacher
checkout. The hotkey, queue, GPU crop/readback, writer, and metadata behavior described
below are implemented; live Skyrim VR/headset acceptance is still pending.

Do **not** train a model in Phase 0. Do **not** build the final OpenNR runtime. Do **not** optimize for production performance yet.

The only goal is a trustworthy capture pipeline.

---

# 1. Target Environment

Primary target:

- Windows 11
- Skyrim VR
- Quest 3
- OpenXR / OpenComposite or the currently working VR runtime path
- NVIDIA RTX 5070 Ti for capture
- DLSS 5 Neural Rendering already working in Skyrim VR
- Existing Skyrim VR DLSSNR/Open Shaders integration or equivalent renderer hook
- Fast NVMe SSD with at least 250 GB free for Phase 0 testing

Training hardware such as an RTX PRO 6000 is **not required** for Phase 0.

---

# 2. Phase 0 Success Criteria

Phase 0 is complete only when all of the following are true:

1. Skyrim VR launches normally with DLSS 5 enabled.
2. Capture can be toggled on/off without restarting the game.
3. For a selected stereo frame, the system can save:
   - pre-DLSS5 left-eye color
   - pre-DLSS5 right-eye color
   - post-DLSS5 left-eye teacher output
   - post-DLSS5 right-eye teacher output
4. The capture contains enough metadata to prove the left/right frames correspond to the same rendered VR frame.
5. The output images are not black, corrupt, stale, duplicated, or accidentally taken from the desktop mirror.
6. Capturing 100 consecutive stereo frames does not crash Skyrim VR.
7. Capturing 1,000 sampled stereo frames produces a dataset that can be enumerated and validated offline.
8. An offline validation script reports:
   - number of samples
   - missing files
   - duplicate hashes
   - dimensions
   - data types
   - frame ordering
   - obvious all-black/all-zero images
9. We can visually compare:
   - input left vs DLSS5 left
   - input right vs DLSS5 right
10. The capture pipeline can later be extended with depth, motion vectors, exposure, jitter, and XR pose data without redesigning the dataset format.

---

# 3. Non-Goals

Do not spend Phase 0 time on:

- neural-network training
- LoRA
- TensorRT
- FP8/FP4
- foveated neural rendering
- final stereo consistency loss
- final OpenNR model architecture
- replacing `nvngx_dlssnr.dll`
- optimizing for 90 Hz gameplay while capture is active
- capturing 500K samples
- automating Skyrim camera movement
- perfect compression
- every possible Skyrim mod configuration

Those belong to later phases.

---

# 4. Recommended Starting Point

Use the existing Skyrim VR DLSS 5 integration as the capture location.

Preferred strategy:

1. Find the code path that owns or receives the texture/resource **immediately before** DLSS Neural Rendering.
2. Find the resource containing the final Neural Rendering result **immediately after** the DLSSNR evaluation/composite stage.
3. Insert a capture tap around those resources.
4. Keep capture code isolated from the DLSSNR implementation.

Do not guess function names.

Codex must inspect the actual codebase and identify the real execution path before changing anything.

If the working implementation is based on Open Shaders, add the capture module there.

If the working implementation instead passes through OptiScaler or another bridge, adapt the same design to that codebase.

---

# 5. Architecture

Use this conceptual layout:

```text
Skyrim VR
   |
   v
VR renderer
   |
   +-------------------------------+
   |                               |
   | pre-DLSSNR resources          |
   v                               |
OpenNRCapture::CapturePreNR()       |
   |                               |
   v                               |
DLSS 5 Neural Rendering            |
   |                               |
   v                               |
post-DLSSNR output                 |
   |                               |
   v                               |
OpenNRCapture::CapturePostNR()      |
   |                               |
   +-------------> async GPU readback
                       |
                       v
                  staging queue
                       |
                       v
                  writer thread
                       |
                       v
                    NVMe SSD
```

The render thread must not synchronously wait for image compression or file writes.

---

# 6. Phase 0 Repository Layout

If adding a new module to an existing project, keep it self-contained.

Suggested layout:

```text
src/
  opennr_capture/
    CaptureManager.h
    CaptureManager.cpp

    GpuReadback.h
    GpuReadback.cpp

    CaptureWriter.h
    CaptureWriter.cpp

    CaptureMetadata.h
    CaptureMetadata.cpp

    CaptureValidation.h
    CaptureValidation.cpp

tools/
  validate_capture.py
  preview_capture.py

docs/
  OPENNR_CAPTURE_FORMAT.md

config/
  opennr_capture.ini
```

Codex may adapt naming to the host repository conventions.

Do not scatter capture-specific logic throughout unrelated rendering code.

---

# 7. Capture Modes

The implementation exposes these settings through the Open Shaders feature JSON
(see `config/opennr_capture.example.json`); the following is the intended contract:

```json
{
  "OpenNR Capture": {
    "enable_capture": false,
    "capture_rate_fps": 3.0,
    "max_samples": 1000,
    "capture_pre_nr": true,
    "capture_post_nr": true,
    "capture_left_eye": true,
    "capture_right_eye": true,
    "crop_size": 512,
    "crop_count": 4,
    "queue_capacity": 8,
    "full_frame_every_samples": 100,
    "output_directory": "D:\\OpenNR_Captures"
  }
}
```

Required modes:

### Single

Capture exactly one stereo frame when triggered.

Use this first.

### Burst

Capture N consecutive stereo frames.

Example:

```ini
Mode=Burst
BurstFrames=8
```

This is needed later for temporal training.

### Sampled

Capture stereo samples at a configurable wall-clock rate so the capture remains
predictable across different render rates.

Example JSON setting:

```json
{ "capture_rate_fps": 3.0 }
```

This prevents Phase 0 from filling the disk with near-identical frames.

---

# 8. Runtime Controls

Implement simple runtime controls.

Minimum:

- hotkey: toggle capture enabled
- hotkey: capture one stereo sample
- hotkey: start/stop an 8-frame burst
- log current capture state

Do not bind keys that conflict with common Skyrim VR controls.

Prefer configurable virtual-key bindings.

Example configuration only:

```ini
ToggleCaptureKey=F9
SingleCaptureKey=F10
BurstCaptureKey=F11
```

---

# 9. Dataset Directory Format

Use a versioned format immediately.

Example:

```text
D:\OpenNR_Captures\
  dataset.json

  clip_000001\
    frame_000000\
      pre_left.bin
      pre_right.bin
      teacher_left.bin
      teacher_right.bin
      metadata.json

    frame_000001\
      ...

  clip_000002\
      ...
```

Do not encode critical metadata only in filenames.

---

# 10. Phase 0 Tensor Format

For initial reliability testing, prefer simple raw binary tensors plus JSON metadata.

Avoid EXR/PNG inside the render thread.

Suggested Phase 0 color format:

- linear RGB
- FP16
- 3 channels
- row-major
- little-endian

Example metadata:

```json
{
  "schema_version": 1,
  "clip_id": 1,
  "frame_id": 42,
  "capture_index": 128,

  "render_frame_number": 81293,
  "timestamp_ns": 0,

  "width": 2064,
  "height": 2208,

  "color_format": "RGB16F",
  "color_space": "linear",

  "left_eye_valid": true,
  "right_eye_valid": true,

  "pre_left_file": "pre_left.bin",
  "pre_right_file": "pre_right.bin",

  "teacher_left_file": "teacher_left.bin",
  "teacher_right_file": "teacher_right.bin"
}
```

The exact resolution must come from the runtime.

Never hardcode Quest 3 dimensions.

---

# 11. Preserve GPU Resource Information

For every captured resource, also record:

- width
- height
- DXGI or equivalent native format
- mip level
- array slice
- sample count
- resource state if relevant
- whether resource is HDR/linear
- whether it was copied before or after any composite stage

For Phase 0, save this under a `debug_resources` object in metadata.

Example:

```json
{
  "debug_resources": {
    "pre_left": {
      "native_format": "DXGI_FORMAT_R16G16B16A16_FLOAT",
      "width": 2064,
      "height": 2208,
      "array_slice": 0
    }
  }
}
```

This information will save enormous debugging time later.

---

# 12. Stereo Pairing

A Phase 0 sample must represent a valid stereo pair.

Create an internal `StereoCaptureRecord`.

Conceptually:

```cpp
struct StereoCaptureRecord
{
    uint64_t renderFrameNumber;

    EyeCapture left;
    EyeCapture right;

    bool preNRComplete;
    bool postNRComplete;
};
```

Only write a sample when:

```text
left pre-NR exists
AND
right pre-NR exists
AND
left teacher exists
AND
right teacher exists
AND
all belong to the same render-frame identity
```

Never silently combine left/right buffers from different frames.

If pairing fails:

- drop the sample
- increment a counter
- log the reason

---

# 13. GPU Readback

This is a critical implementation rule.

Do not perform:

```text
GPU texture
-> blocking CPU read
-> disk write
```

inside the render call.

Instead:

```text
GPU texture
-> copy to staging/readback resource
-> fence/event
-> enqueue pending capture
-> return to game
```

Then on another thread:

```text
wait until GPU copy complete
-> map staging resource
-> copy to host buffer
-> enqueue write
```

A writer thread then saves the sample.

Use a bounded queue.

If the queue is full:

- drop capture frames
- never stall Skyrim VR indefinitely
- log dropped-sample count

Correctness is more important than capturing every frame.

---

# 14. Initial Capture Strategy

Do not immediately capture at 72/90 FPS.

Use the following bring-up order.

## Test A — one frame

Capture:

```text
pre_left
pre_right
teacher_left
teacher_right
```

Validate visually.

Do not proceed until they are correct.

## Test B — ten-frame burst

Capture 10 consecutive stereo frames.

Check:

- eye ordering
- temporal progression
- no stale buffer reuse

## Test C — 100-frame burst

Check stability.

## Test D — sampled 1,000-frame dataset

Example:

```text
capture one frame every 30 rendered frames
```

Walk through multiple locations manually.

Do not automate Skyrim yet.

---

# 15. Offline Validation Tool

Create:

```text
tools/validate_capture.py
```

It must accept:

```bash
python tools/validate_capture.py D:\OpenNR_Captures
```

Minimum checks:

### Structure

- valid `dataset.json`
- supported schema version
- every metadata file parses
- all referenced tensor files exist

### Tensor size

Expected bytes must equal:

```text
width * height * channels * bytes_per_channel
```

### Content

Check:

- NaN count
- Inf count
- percentage zeros
- min
- max
- mean
- standard deviation

Flag likely black/empty captures.

### Hashes

Calculate a fast content hash for every tensor.

Report:

- exact duplicate frames
- suspiciously repeated teacher outputs
- left/right files that are unexpectedly identical

### Ordering

Check:

```text
renderFrameNumber[n+1] > renderFrameNumber[n]
```

unless intentionally capturing multiple eye resources belonging to the same frame.

### Summary

Print:

```text
Samples:            1000
Valid:               996
Invalid:               4
Duplicate pairs:       7
Black tensors:         0
Missing files:         0
Dropped captures:     13
```

Return non-zero exit status on structural corruption.

---

# 16. Preview Tool

Create:

```text
tools/preview_capture.py
```

It should convert selected FP16 binary captures into easy-to-view images.

Generate a 2x2 preview:

```text
PRE LEFT        TEACHER LEFT

PRE RIGHT       TEACHER RIGHT
```

Also generate:

```text
abs(teacher - pre)
```

for each eye.

This is essential for confirming that the supposed teacher output actually contains the DLSS 5 changes.

---

# 17. Logging

Create a dedicated log file:

```text
OpenNRCapture.log
```

Log at startup:

- capture module version
- host project version if available
- GPU
- detected renderer
- capture directory
- configured modes
- discovered pre-NR resource formats
- discovered post-NR resource formats

During capture log only meaningful events.

Example:

```text
[INFO] Capture enabled
[INFO] Stereo sample 42 queued
[WARN] Capture queue full; sample dropped
[ERROR] Right-eye teacher resource missing for render frame 81293
```

Do not spam one line for every normal frame unless debug logging is enabled.

---

# 18. Dataset Manifest

At the root, create:

```text
dataset.json
```

Example:

```json
{
  "dataset_schema": "OpenNR-VR-Capture",
  "schema_version": 1,

  "game": "Skyrim VR",
  "capture_stage": "Phase0",

  "dlssnr_enabled": true,

  "total_samples": 1000,

  "contains": {
    "pre_color": true,
    "teacher_color": true,
    "depth": false,
    "motion_vectors": false,
    "xr_pose": false
  }
}
```

Update it safely.

Prefer writing a temporary file then atomically renaming it.

---

# 19. Important Phase 0 Design Rule

The dataset format must already be extensible.

Later phases will add fields such as:

```text
depth_left
depth_right

motion_left
motion_right

exposure

jitter_x
jitter_y

left_view_matrix
right_view_matrix

left_projection
right_projection

head_pose

predicted_display_time

gaze_x
gaze_y
```

Do not design Phase 0 in a way that requires rewriting the entire reader later.

Use optional fields and a schema version.

---

# 20. Phase 0 Milestones for Codex

Codex should implement these sequentially.

## M0.1 — Repository reconnaissance

Before coding:

1. identify renderer API
2. locate DLSSNR invocation
3. locate pre-NR input resources
4. locate post-NR output resources
5. determine how left/right eyes are represented
6. document findings in:

```text
docs/PHASE0_RECON.md
```

Do not modify rendering behavior yet.

Acceptance:

- specific source files/functions identified
- exact texture/resource handles identified
- explanation of eye handling written

---

## M0.2 — Single-frame capture (implemented; live acceptance pending)

The teacher worktree now implements one-frame manual capture through `OpenNRCaptureFeature`
(F10 or the `single` action), including paired per-eye input/teacher resources and
metadata. A live Skyrim VR run still needs to confirm the four expected artifacts.

Only:

```text
pre left/right
teacher left/right
```

Acceptance:

- four valid tensors saved
- metadata saved
- preview tool renders them correctly

---

## M0.3 — Async readback (implemented; live acceptance pending)

The implementation issues only GPU copies and an event query on the render thread;
query wait, mapping, PNG encoding, raw writes, and JSONL append run on a bounded worker
queue. The queue/drop counters still need a live stress check.

Acceptance:

- single-frame capture no longer performs disk I/O on render thread
- bounded queue exists
- capture drop counter exists

---

## M0.4 — Burst capture (implemented; live acceptance pending)

F11 and the `burst` action implement the default eight-frame and configurable N-frame
bursts. Ordering and eye pairing remain runtime acceptance checks.

Acceptance:

- all frames ordered
- no eye cross-pairing
- no stale resources

---

## M0.5 — Sampled dataset (implemented; live acceptance pending)

The capture rate is configurable in frames per second, with periodic full-frame
validation samples and a configurable sample limit. The 1,000-stereo-sample run is
still a live validation task, not a completed result.

Acceptance:

- collect 1,000 stereo samples
- Skyrim VR remains stable
- validation tool succeeds

---

## M0.6 — Phase 0 validation report

Produce:

```text
docs/PHASE0_RESULTS.md
```

Include:

- captured sample count
- game/runtime configuration
- resource formats
- dimensions
- average disk MB/sample
- approximate capture overhead
- dropped sample count
- screenshots/previews
- known limitations
- recommendation for Phase 1

Phase 0 is not complete without this report.

---

# 21. Phase 0 Testing Matrix

Run at least:

### Test 1

Static interior.

Purpose:

- easy image comparison
- detect wrong resource/surface

### Test 2

Outdoor daylight.

Purpose:

- foliage
- sky
- shadows
- DLSS5 appearance difference

### Test 3

NPC close-up.

Purpose:

- faces/skin
- verify DLSS5 teacher effect

### Test 4

Head rotation.

Purpose:

- verify temporal frame progression

### Test 5

Walking/strafing.

Purpose:

- verify stereo sequence capture

### Test 6

Scene transition.

Purpose:

- make sure resources are reacquired correctly after loading/interior transition

---

# 22. Failure Conditions

Stop and fix the pipeline if any of these occur:

- desktop mirror captured instead of eye render target
- left/right captures are identical when they should not be
- teacher image is actually pre-NR image
- capture only works for one eye
- buffers alternate between stale/new frames
- dimensions change without metadata reflecting it
- capture causes persistent VR stutter even when sampling sparsely
- Skyrim crashes during a 100-frame burst
- dataset contains silent corruption
- readback queue can grow without limit

Do not proceed to depth/MV capture until Phase 0 color capture is trustworthy.

---

# 23. Phase 1 Boundary

Phase 1 begins only after Phase 0 passes.

Phase 1 will add:

```text
depth L/R
motion vectors L/R
exposure
jitter
XR poses/projection/FOV
predicted display time
temporal clip integrity checks
```

Phase 1 will also define the first actual training-ready schema.

Phase 0 should not implement model training.

---

# 24. Codex Working Rules

Codex should follow these rules while implementing Phase 0:

1. Inspect before editing.
2. Never invent host-project function names.
3. Keep capture code isolated.
4. Avoid synchronous disk writes from the render thread.
5. Preserve current DLSS 5 behavior.
6. Preserve normal Skyrim VR behavior when capture is disabled.
7. Prefer small compilable commits.
8. Build after each milestone.
9. Add logs around discovered resources.
10. Treat left/right synchronization as correctness-critical.
11. Do not silently fall back when expected resources are missing.
12. Do not optimize compression until correctness is proven.
13. Do not start training code in Phase 0.
14. Document every resource format actually observed at runtime.
15. Keep the dataset schema versioned.

---

# 25. First Prompt to Give Codex

Use this after opening the actual Skyrim VR DLSSNR/Open Shaders source repository in Codex:

```text
Implement OpenNR-VR Phase 0 according to PHASE0_OPENNR_SKYRIMVR_CODEX_GUIDE.md.

Start with milestone M0.1 only.

Inspect the repository and identify the exact code path for Skyrim VR DLSS Neural Rendering. Determine:

1. where the pre-DLSSNR left/right color resources are available,
2. where the post-DLSSNR teacher output is available,
3. how the renderer distinguishes the two VR eyes,
4. which graphics API/resources are involved,
5. the safest insertion points for an isolated capture module.

Do not modify rendering behavior yet.

Create docs/PHASE0_RECON.md with concrete file names, function names, resource formats when discoverable, call ordering, and the proposed capture insertion points.

Do not guess identifiers. Verify them from the source.
```

---

# 26. Definition of Done

Phase 0 is done when the following command can be run on a captured dataset:

```bash
python tools/validate_capture.py D:\OpenNR_Captures
```

and it reports a valid dataset containing at least **1,000 synchronized stereo pre-NR/post-DLSS5 samples**, while Skyrim VR remains stable and the visual preview clearly demonstrates that the teacher outputs are the correct DLSS 5 Neural Rendering results.

At that point, proceed to Phase 1.
