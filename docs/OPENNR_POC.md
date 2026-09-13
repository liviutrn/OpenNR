# OpenNR-VR training proof of concept

This is the first small learning experiment on the captured Skyrim VR data. It
is deliberately separate from the Phase 0 capture acceptance gate and does not
modify the teacher checkout, the MGO installation, or the capture directory.

## Question

Can a compact open student learn a measurable part of the spatial mapping from
the captured pre-NR RGB crop to the captured Feature 18 teacher RGB crop? A
second question is whether the native depth and motion-vector inputs help
relative to an RGB-only control.

## Current input

The current sample is 33 sequences and 919 complete frame records, or 7,352
paired 512x512 crops per stage. The paired stages are input RGB, teacher RGB,
raw R32_FLOAT depth, and raw R16G16_FLOAT motion vectors. The capture was made
at Full Eye, 100% model resolution, and one Feature 18 pass.

The runner uses the square crop artifacts for efficient training. Complete
full-resolution artifacts are retained in the capture tree for full-frame and
stereo validation; they are not silently substituted into the crop index.

## Method

The default split is sequence-level:

* 12 earlier sequences for training
* 3 earlier sequences for validation
* the separate latest capture session, 18 sequences, for held-out test

This prevents neighboring frames, eyes, and crops from the same sequence from
appearing in both training and test. The split and a manifest fingerprint are
saved in dataset_audit.json and split_manifest.json.

The guided student is a small residual CNN with six channels: RGB, normalized
depth, and a bounded model-ready motion representation. The captured native
R16G16_FLOAT motion vectors are kept unchanged on disk; training removes
non-finite values and raw outliers, applies the recorded MVecScaleX/Y values,
clips the resulting displacement to 128 pixels, and normalizes it to roughly
[-1, 1]. The RGB-only control has the same network shape with only RGB input. Both predict
the teacher RGB crop at a reduced POC resolution, normally 128x128, and use the
same deterministic seed and optimizer settings. `--input-scale` can now make
the input smaller than the target: convolutions run at the smaller input size,
then one bilinear reconstruction upsamples the RGB base and residual to the
target crop. This is a deliberately simple scale-aware baseline, not yet the
final temporal DLSS-style architecture.

The important baselines are:

* identity RGB versus teacher: how much the teacher changed the captured input
* RGB-only student versus teacher: whether a trainable spatial mapping exists
* guided student versus teacher: whether native guides improve that mapping

The main metrics are MAE, PSNR, p95 per-pair MAE, and mean absolute prediction
change from the input. These are teacher-agreement metrics; they are not a
causal claim that the student is visually superior.

## Run

Use the isolated environment created for this experiment:

    E:\OpenNR-VR-Poc-Venv\Scripts\python.exe tools\train_opennr_poc.py --capture-root E:\MGO-RC3-fresh\overwrite\Root\OpenNR_Captures --output-dir D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc --max-steps 600 --models guided,rgb

For the first scale-aware comparison, keep the same target crop size and use
an input at half the linear resolution:

    E:\OpenNR-VR-Poc-Venv\Scripts\python.exe tools\train_opennr_poc.py --capture-root E:\MGO-RC3-fresh\overwrite\Root\OpenNR_Captures --output-dir D:\.CODEX_Projects\OpenNR-VR\out\opennr_poc_scale50 --resolution 128 --input-scale 0.5 --max-steps 600 --models guided,rgb

The runner writes its reproducible audit, split, configuration, guide
preprocessing metadata, metrics, training history, best/last checkpoints, and
two PNG previews under the output directory. The output directory is ignored by
this repository.

## Interpretation boundary

A positive held-out improvement would be useful evidence that the dataset
contains a learnable per-frame teacher signal and that the pipeline is suitable
for the next modeling step. A scale-aware result additionally tells us whether
the idea survives lower-resolution input. Neither result proves temporal
quality, stereo consistency under motion, live Feature 18 replacement, headset
quality, or real-time VR performance. Those still require contiguous temporal
training, live runtime validation, and a measured inference budget.

The capture history already records queue pressure in the newer run. This POC
keeps the data because complete paired records remain useful for spatial
exploration, but it must not be reported as clean final temporal training data.
