# OpenNR photorealism side experiment — 2026-09-09

## Decision

The released HyPER-GAN and REGEN checkpoints do not produce a convincing
photorealistic Skyrim result when used zero-shot. They are useful research
references, but their released GTA-V/CARLA street-scene priors are too far out
of domain. Neither should be integrated into OpenNR or used to generate
Skyrim training targets in its current form.

The best result in this tranche remains the small, Skyrim-trained paired
control arm: SVDLUT reached test MAE `0.0256113`, and Adaptive 3D LUT reached
`0.0256993`. These are meaningful teacher-directed improvements over the
input, but neither is near the requested `0.005` MAE target and neither
reconstructs the teacher's local face/material identity. The models are useful
controls for tone and stability, not proof of independent photorealism.

No candidate passed both gates required for runtime consideration:

1. visibly more realistic Skyrim imagery than the input/teacher context; and
2. promising measured RTX 5070 Ti latency at the representative per-eye
   resolution.

The experiment therefore ends this tranche with no runtime change and no
checkpoint promotion. It does, however, establish reproducible negative OOD
results and a clean basis for a future Skyrim-specific photorealism-target
experiment.

## Scope and provenance

The new immutable study manifest is:

`C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\manifest.json`

Manifest SHA-256 at evaluation time:

`8490ff039cf6445bb827d86d12b22b76c201a2c24c77f0eda9f75aa4e99a13e48`

It references the existing byte-validated RGB cache
`C:\OpenNR_Cache_StrictAllCohortsVariedHighEffect_0.5.5_20260907` without
rewriting it. The cache has 40,832 paired rows from 291 prior/cohort captures
and 28 varied high-effect captures, with sequence, frame, eye, reset, and
provenance metadata retained. The test split remained protected from training
and checkpoint selection.

The released-model evaluation used only input RGB during inference:

- Quality: frame 32 from all 66 held-out test sequences, both eyes — 132 rows.
- Temporal/stereo sanity: frames 31, 32, and 33 from all 66 sequences, both
  eyes — 396 rows.
- Quality arithmetic: FP32.
- GPU benchmark arithmetic: FP16, input-resident GPU timing plus a separate
  CPU-to-GPU-copy-inclusive timing.
- Models are stateless. Reset metadata is preserved in the manifest but no
  released model consumes a reset token or temporal history.
- The teacher is used only after inference for MAE/PSNR and side-by-side
  context; it is never passed to a released model.

This is an unseen-Skyrim test relative to the released HyPER-GAN/REGEN
training domains. It is not a claim that the released models were trained on
Skyrim.

## Official models audited

| Model | Official source and license | Released architecture / checkpoint | Parameters |
|---|---|---|---:|
| HyPER-GAN GTA2Cityscapes | [official repository](https://github.com/stefanos50/HyPER-GAN), [paper](https://arxiv.org/abs/2603.10604); MIT | Lightweight U-Net, 64 base channels, 4 residual blocks; `gta2cs.pth` | 6,172,291 |
| HyPER-GAN GTA2Vistas | [official repository](https://github.com/stefanos50/HyPER-GAN), [paper](https://arxiv.org/abs/2603.10604); MIT | Same generator; `gta2vistas.pth` | 6,172,291 |
| REGEN GTA2Cityscapes | [official repository](https://github.com/stefanos50/REGEN), [paper](https://arxiv.org/abs/2508.17061); BSD 2-Clause root license plus included upstream notices | Pix2PixHD `GlobalGenerator`, 64 base channels, 4 downsampling layers, 9 residual blocks; official Drive checkpoint | 182,443,267 |
| EPE / Enhancing Photorealism Enhancement | [official repository](https://github.com/isl-org/PhotorealismEnhancement), [project page](https://isl-org.github.io/PhotorealismEnhancement/); archived/discontinued, code snapshot MIT | Conceptually justified heavy photorealism teacher, but no usable pretrained checkpoint was present in the official clone | Not run |

The EPE audit matters: the project README explicitly announces that Intel no
longer maintains it, and the clone contains code and result-dataset links but
no generator checkpoint. Reproducing it for Skyrim would require rebuilding
the required semantic/gbuffer training data and training the teacher. It was
not silently replaced with an unrelated model.

The earlier guide candidates were also audited and run as controls:

- [Image-Adaptive 3D LUT](https://github.com/HuiZeng/Image-Adaptive-3DLUT),
  Apache-2.0.
- [SVDLUT](https://github.com/WontaeaeKim/SVDLUT), Apache-2.0.
- [Zero-DCE++](https://github.com/Li-Chongyi/Zero-DCE_extension),
  non-commercial attribution license in the source snapshot.
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN), BSD-3-Clause; tested
  separately because the released `realesr-general-x4v3` model changes
  resolution by 4x.

## Held-out teacher-similarity results

All values below are RGB values normalized to `[0, 1]`. The fixed-frame
quality baseline for the HyPER/REGEN pass is input MAE `0.0304723` and input
PSNR `26.4662 dB`. A negative improvement means the model moved farther from
the DLSS5-NR teacher than the untouched input.

| Released model | Quality rows | Teacher MAE | Teacher PSNR | Change vs input MAE | Temporal output Δ L1 | Teacher temporal Δ L1 | Stereo output Δ L1 | Teacher stereo Δ L1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HyPER-GAN GTA2Cityscapes | 132 | 0.0452989 | 23.8803 | -0.0148265 | 0.0146570 | 0.0325999 | 0.0690919 | 0.1043404 |
| HyPER-GAN GTA2Vistas | 132 | 0.0457299 | 23.4411 | -0.0152576 | 0.0208120 | 0.0325999 | 0.1031159 | 0.1043404 |
| REGEN GTA2Cityscapes | 132 | 0.1169973 | 16.8225 | -0.0865250 | 0.0326976 | 0.0325999 | 0.1347812 | 0.1043404 |

Interpretation:

- HyPER-GAN GTA2Cityscapes is the best of the three on direct teacher
  similarity, but it suppresses temporal variation and stereo separation. Its
  output is visibly darker/greener than the Skyrim input.
- HyPER-GAN GTA2Vistas has slightly worse MAE but much better stereo magnitude
  than GTA2Cityscapes. It still imposes the wrong dark street-scene prior and
  does not improve believable Skyrim materials or faces.
- REGEN preserves approximately the teacher's three-frame temporal magnitude,
  but its stereo delta is too large and its spatial output is soft, green, and
  strongly mismatched. Matching motion magnitude is not enough to establish
  temporal correctness.

For reference, the previously trained Skyrim-specific paired controls were
evaluated on the complete 8,448-row test split:

| Skyrim-trained control | Parameters | Test MAE | Test PSNR | Test temporal Δ MAE | 512² FP16 median / p95 | Exact-area per-eye median |
|---|---:|---:|---:|---:|---:|---:|
| SVDLUT | 17,048 | 0.0256113 | 27.5455 dB | 0.0114328 | 0.573 / 0.601 ms | 4.640 ms |
| Adaptive 3D LUT | 92,900 | 0.0256993 | 27.6616 dB | 0.0116891 | 0.456 / 0.604 ms | 1.062 ms |
| Zero-DCE++ supervised | 10,561 | 0.0266698 | 27.0883 dB | 0.0109474 | 1.358 / 35.721 ms | 22.286 ms |
| Same-resolution SRVGG | 169,347 | 0.0281431 | 26.9332 dB | 0.0118347 | 3.444 / 3.650 ms | 103.370 ms |

The control results are not interchangeable with the 132-row fixed-frame
OOD results above; they are reported separately to avoid pretending that
different evaluation scopes are the same experiment.

## RTX 5070 Ti results

Benchmark GPU: NVIDIA GeForce RTX 5070 Ti, Torch `2.7.1+cu128`. Timings are
network-only, input already resident on the GPU, unless explicitly marked
total. “Total” includes the host-to-device copy and forward pass but not CPU
readback. The representative per-eye shape was `1x3x2496x2688`, the same pixel
area as the earlier control benchmark.

| Model | 512² single median / p95 | 512² stereo batch-2 median | 512² total median | 2496x2688 single median | Peak VRAM 512² / full |
|---|---:|---:|---:|---:|---:|
| HyPER-GAN GTA2Cityscapes | 1.821 / 1.971 ms | 2.828 ms | 1.892 ms | 40.185 ms | 0.067 / 1.395 GiB |
| HyPER-GAN GTA2Vistas | 1.773 / 1.841 ms | 2.825 ms | 1.903 ms | 40.192 ms | 0.067 / 1.395 GiB |
| REGEN GTA2Cityscapes | 10.975 / 10.993 ms | 20.880 ms | 11.092 ms | 251.982 ms | 0.438 / 2.840 GiB |

The HyPER timing is attractive in isolation, but it is not a usable runtime
candidate because the output fails the visual/semantic gate. REGEN fits in
the card but is approximately 252 ms per full eye, before any integration
overhead, which rules it out as a direct VR filter even if its domain were
correct. It remains potentially useful only as an offline reference if a
Skyrim-specific target-generation route can be established.

## Visual realism assessment

The fixed side-by-side gallery was inspected across faces/skin, hair, armor,
cloth, wood, stone, foliage, highlights, shadows, and distant scenery.

| Branch | What the unseen Skyrim gallery shows | Independent photorealism decision |
|---|---|---|
| HyPER-GAN GTA2Cityscapes | Coherent scene layout but dark green cast, reduced local contrast, loss of material/color identity, and occasional colored output spots. | Reject. Fast, but not a believable Skyrim photographic style. |
| HyPER-GAN GTA2Vistas | Retains somewhat more contrast and stereo magnitude, but still dark/green and not materially more photographic. | Reject. Slightly preferable to GTA2Cityscapes as an OOD probe, not a candidate. |
| REGEN GTA2Cityscapes | Strongest global “camera/photo” prior, but it softens wood, cloth, foliage, and face structure; green cast and stereo differences are conspicuous. | Reject for Skyrim and runtime. Interesting offline reference only. |
| Native Adaptive LUT weights | Broad color/contrast remap, sometimes plausible, but released photographic-domain weights move farther from the teacher than the input. | Reject as released zero-shot weights; the Skyrim-trained paired branch remains a useful control. |
| Native SVDLUT FiveK/PPR experts | Large magenta/yellow/green casts and severe spatial/color distortions on Skyrim. | Reject. No realism value. |
| Native Zero-DCE++ | Brightens aggressively and lifts/bleaches dark Skyrim areas; no convincing detail recovery. | Reject. Exposure change is not photorealism. |
| Real-ESRGAN general x4 | Adds a resolution-changing super-resolution pass, but it is not a same-resolution NR filter and downsampled output remains close to the input rather than a clear teacher-like or independently photographic change. | Keep only as a separate x4 experiment, not OpenNR NR. |
| Skyrim-trained paired controls | Mostly artifact-free broad tone/color movement toward the teacher; they do not recreate teacher identity-level facial/material detail. | Best current control family, but not independent photorealism proof. |

The gallery generated by the new pass is saved at:

`C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\photorealism_eval_v1\photorealism_gallery.png`

The native released-weight gallery is saved at:

`C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\native_pretrained_v7\native_other_gallery.png`

and

`C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\native_pretrained_v7\native_lut_gallery.png`

## Reproducible artifacts

- New evaluator: `tools/tiny_enhancement/photorealism_eval.py`.
- Native released-weight evaluator: `tools/tiny_enhancement/native_transfer.py`.
- Full photorealism result:
  `C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\photorealism_eval_v1\photorealism_eval.json`.
- Full native released-weight result:
  `C:\OpenNR_TinyEnhancementStudy_20260909\realism_pilot_v1\native_pretrained_v7\native_transfer.json`.
- HyPER GTA2Cityscapes checkpoint SHA-256:
  `DB535F7B34B722DC83A9D02DB5D86DD59530C06D7EB77B96C8455C9AA14D0185`.
- HyPER GTA2Vistas checkpoint SHA-256:
  `1B1DC321068AF189D5834FB14B703447E67A7DA954F35AA1651681FFC4418412`.
- REGEN GTA2Cityscapes generator SHA-256:
  `46258537FB99B04C9BC891691361F38C59F3FDFF79EE9F495E69402AA58C6A69`.
- Real-ESRGAN x4v3 checkpoint SHA-256:
  `8DC7EDB9AC80CCDC30C3A5DCA6616509367F05FBC184AD95B731F05BECE96292`.

## Best next step

Do not spend Runpod credit or integrate a released OOD checkpoint. If the
independent-photorealism objective remains important, the next bounded
experiment should be Skyrim-specific target generation:

1. Define a small, manually reviewed target gallery first, with explicit
   acceptance criteria for face/skin, cloth/armor, wood/stone, foliage,
   highlights/shadows, stereo, and temporal stability.
2. Use the existing DLSS5-NR teacher as the fidelity control, not as the only
   realism oracle.
3. Investigate a licensed image-to-image teacher that can operate on Skyrim
   imagery without hallucinating geometry or identity. EPE is not currently
   usable because its official checkpoint is absent; REGEN is too expensive
   and wrong-domain as released.
4. If a teacher passes the gallery review, generate targets only for a new
   immutable training root, then distill into an NR-sized student and measure
   both teacher similarity and independent realism on a sequence-level held-out
   cohort.
5. Require the student to show a real visual improvement before considering
   an RTX 5070 Ti/runtime path; a low MAE alone is insufficient.
