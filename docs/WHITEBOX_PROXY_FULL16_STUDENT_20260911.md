# White-box recovered-look student expansion — 2026-09-11

## Decision

The all-16-frame offline experiment is complete. It produced a useful, runnable
small approximation of the recovered white-box look, especially in the RGB-only
arm. More frame coverage improved RGB-only imitation on the frozen test set by
about 2.0% relative proxy MAE and 1.5% relative native guardrail MAE. The guided
arm did not improve: its proxy MAE regressed by about 1.5% and its native MAE
was effectively unchanged.

This is an offline research result only. It does not establish native NVIDIA
parity, temporal correctness, stereo correctness in the runtime contract, VR
frame-budget viability, headset quality, or deployment readiness.

`promotion=false` remains in effect. No runtime wrapper or TensorRT export was
attempted.

## Experiment contract

Source capture root:

`C:\OpenNR_Captures_FullEyeTemporalStateTranche_20260910`

The manifest selected all frame IDs 1 through 16 from the same 14 existing
sequence directories:

- 14 sequences
- 224 complete frames
- 448 eye rows
- 256 train eye rows from 8 sequences
- 96 validation eye rows from 3 sequences
- 96 expanded-manifest test eye rows from 3 sequences
- sequence-level chronological 60/20/20 split
- 2,816 student patches after cache construction

The original three-frame test cache was not changed. Final scoring used the
earlier frozen cache containing only frames 1, 8, and 16 from the three held-out
test sequences: 84 eye rows and 528 patches. The expanded-manifest test rows
were generated for completeness but were not used for checkpoint selection.

The recovered model was run on each complete eye at the full 512x512 output
contract, and the result was cropped only after full-eye inference. The native
teacher remains retained separately in `rgb.npy[:,1]`; it was not replaced by
the recovered proxy and was not used as the student loss target.

Recovered target provenance:

- weights: `C:\OpenNR\research\mlx_dlss_feature_distill_20260911\private\weights\dll_E16BCF15\dlssnr-weights-logical.safetensors`
- weights SHA-256: `D64261D8F0173F9266C250F6B6348406EDAE0C8F7297DD6122B30EC5AD5C476C`
- native DLL: `E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll`
- DLL SHA-256: `E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E`
- source commit: `0ca2deab092fe6f3e331bf4f616271dbc64521d0`
- inference device: CUDA on an NVIDIA GeForce RTX 5070 Ti
- recovered target controls: standard profile, local tone 1, local structure 1, skin structure -1, auto-mask disabled, intensity 1, detail 1, colour 1
- target generation time: 2,094.52 seconds

The resulting proxy target array is `2816 x 3 x 512 x 512`, `uint8`, finite,
with values in `[0, 255]`. Its recorded SHA-256 is
`EA163DF5E2E15EC69075760A67E8E3F8FFD269D3788F052F9511178CB7B5121C`.

## Training

Both arms used the same small architecture and recipe as the earlier pilot:

- width: 32
- residual blocks: 2
- scale: 4
- batch size: 8
- learning rate: 0.0002
- 2,000 steps
- validation every 250 steps
- seed: 20260911
- train source: all-16 cache train split only
- selection metric: validation proxy MAE
- native NVIDIA output: independent guardrail only

| Arm | Parameters | Selected checkpoint | Best validation proxy MAE | Native guardrail MAE at selected point |
|---|---:|---:|---:|---:|
| RGB-only | 354,569 | step 500 | 0.01360036 | 0.02292499 |
| Guided | 358,009 | step 500 | 0.01446072 | 0.02328877 |

The guided input did not produce a better recovered-look fit in this run. That
does not prove guides are useless for a future contract; it says this guide
configuration did not help this static proxy target under this recipe.

## Frozen three-frame test

The new checkpoints were evaluated against the original frozen test cache. The
identity value is the raw input versus the corresponding target and is included
to show whether the student is doing useful transformation rather than merely
copying the input.

| Arm | Test proxy MAE | Test proxy PSNR | Test native MAE | Test native PSNR |
|---|---:|---:|---:|---:|
| Earlier RGB-only pilot | 0.01501642 | 32.3766 dB | 0.02063931 | 30.5018 dB |
| All-16 RGB-only | **0.01471096** | **32.3947 dB** | **0.02032378** | **30.6057 dB** |
| Earlier guided pilot | 0.01496283 | 32.2928 dB | 0.02015429 | 30.6397 dB |
| All-16 guided | 0.01519205 | 32.2113 dB | 0.02029057 | 30.5675 dB |
| Raw input identity | 0.01790550 | 31.0533 dB | 0.02242134 | 29.5945 dB |

Relative to the earlier pilot on the exact same frozen rows:

- RGB-only proxy MAE improved 2.03%.
- RGB-only native guardrail MAE improved 1.53%.
- Guided proxy MAE regressed 1.53%.
- Guided native guardrail MAE regressed 0.68%; this is effectively a tie, not a meaningful native-parity win.

RGB-only is therefore the preferred offline approximation from this experiment.
The native result remains materially different from the native teacher; this is
not a recovered native carrier.

Per-sequence frozen-test proxy/native MAE:

| Sequence | RGB proxy | RGB native | Guided proxy | Guided native |
|---|---:|---:|---:|---:|
| `seq-1789071448597-3` | 0.01305215 | 0.01820821 | 0.01350630 | 0.01805353 |
| `seq-1789071604237-4` | 0.01166716 | 0.01785530 | 0.01179513 | 0.01723223 |
| `seq-1789071762719-5` | 0.01941358 | 0.02490783 | 0.02027474 | 0.02558595 |

The third held-out sequence remains the harder case for both arms, which is a
reason not to overinterpret the small aggregate improvement as broad parity.

## Manually tagged visual subsets

The manually reviewed tags were evaluated on the same frozen test cache. The
subset counts are patch samples, and categories may overlap. Tags cover faces,
hair, armor, foliage, dark interiors, and bright exteriors. The tag file is
marked `tagging_complete=true`.

RGB-only proxy/native MAE:

| Category | Samples | Proxy MAE | Native MAE |
|---|---:|---:|---:|
| Faces | 26 | **0.01680746** | 0.02233555 |
| Hair | 17 | **0.01120275** | 0.01797603 |
| Armor | 26 | **0.01449649** | 0.01970776 |
| Foliage | 26 | **0.01376060** | 0.01959263 |
| Dark interiors | 14 | **0.01951106** | 0.02454983 |
| Bright exteriors | 16 | **0.01647905** | 0.02163900 |

Guided proxy/native MAE:

| Category | Samples | Proxy MAE | Native MAE |
|---|---:|---:|---:|
| Faces | 26 | 0.01752038 | 0.02248293 |
| Hair | 17 | 0.01159836 | **0.01753553** |
| Armor | 26 | 0.01507320 | **0.01935686** |
| Foliage | 26 | 0.01410536 | 0.01973337 |
| Dark interiors | 14 | 0.02022829 | 0.02503895 |
| Bright exteriors | 16 | 0.01686820 | 0.02190399 |

RGB-only is the better proxy imitation in five of six categories. Guided is
slightly closer to native in armor and hair, but the differences do not reverse
the overall choice and do not establish native equivalence.

### Face inspection gallery

The fixed 512x512 patch grid does not produce face-detector crops. Therefore the
26 face-tagged patches include some genuine facial views plus adjacent beard,
hair, armor, and a small number of false-positive neighboring patches. The
gallery below renders all 26 tagged patches, while the first four links are
clearer true-face examples for direct inspection. Each sheet contains Input,
RGB-only student, Guided student, White-box proxy, and Native NVIDIA.

- [all 26 face-tagged crops contact sheet](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/faces_contact_sheet.jpg)
- [bald face, patch 0483](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/samples/face_01_patch0483_seq-1789071604237-4_f1_e0.jpg)
- [moustache/lower face, patch 0504](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/samples/face_02_patch0504_seq-1789071762719-5_f1_e0.jpg)
- [upper face and eyes, patch 0507](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/samples/face_08_patch0507_seq-1789071762719-5_f1_e0.jpg)
- [upper face and eyes, patch 0515](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/samples/face_18_patch0515_seq-1789071762719-5_f8_e0.jpg)
- [gallery metadata](../out/whitebox_proxy_full16_20260911/visual_galleries/faces_all/gallery.json)

## Model-only inference timing

Timing was measured separately with CUDA-resident inputs from the frozen test
cache. It excludes game capture, CPU image preparation, runtime interop,
resource registration, transfers, compositor work, headset delivery, and any
temporal state handling.

Hardware/software: NVIDIA GeForce RTX 5070 Ti, Torch 2.7.1+cu128, 2496x2688
full-eye input contract.

| Arm | Warm median per eye | Warm p95 per eye | Warm median sequential stereo | Warm p95 sequential stereo | Peak allocated |
|---|---:|---:|---:|---:|---:|
| RGB-only | 22.42 ms | 22.85 ms | 44.40 ms | 44.68 ms | 1.73 GiB |
| Guided | 22.59 ms | 22.84 ms | 44.61 ms | 44.88 ms | 1.76 GiB |

This is useful for sizing a future implementation, but it is not a live VR
frame-budget result. In particular, a runtime would still need the actual
Feature 18 resource contract, stereo ownership, synchronization, copies or
interop, temporal policy, and headset presentation path.

## Artifacts

Source and cache:

- [all-16 source manifest](../out/whitebox_proxy_full16_20260911/source_manifest.jsonl)
- [manifest summary](../out/whitebox_proxy_full16_20260911/source_manifest.summary.json)
- [cache completion metadata](../out/whitebox_proxy_full16_20260911/cache/complete.json)
- [proxy target metadata](../out/whitebox_proxy_full16_20260911/cache/proxy_complete.json)
- [representative recovered proxy preview](../out/whitebox_proxy_full16_20260911/cache/proxy_previews/row00352_seq-1789071448597-3_f1_e0.jpg)

Students and frozen-test evaluation:

- [RGB-only best checkpoint](../out/whitebox_proxy_full16_20260911/student_rgb_32x2/best.pt)
- [guided best checkpoint](../out/whitebox_proxy_full16_20260911/student_guided_32x2/best.pt)
- [RGB-only frozen-test evaluation](../out/whitebox_proxy_full16_20260911/frozen_test/rgb/evaluation.json)
- [guided frozen-test evaluation](../out/whitebox_proxy_full16_20260911/frozen_test/guided/evaluation.json)
- [RGB-only tagged evaluation](../out/whitebox_proxy_full16_20260911/visual_tags/rgb_full16.json/evaluation.json)
- [guided tagged evaluation](../out/whitebox_proxy_full16_20260911/visual_tags/guided_full16.json/evaluation.json)
- [RGB-only model-only benchmark](../out/whitebox_proxy_full16_20260911/benchmark/rgb.json)
- [guided model-only benchmark](../out/whitebox_proxy_full16_20260911/benchmark/guided.json)
- [manual visual tag file](../out/whitebox_proxy_pilot_20260911/manual_visual_tags/visual_tags.json)
- [RGB-only comparison previews](../out/whitebox_proxy_full16_20260911/frozen_test/rgb/previews)
- [guided comparison previews](../out/whitebox_proxy_full16_20260911/frozen_test/guided/previews)

## Recommendation

Keep the all-16 RGB-only `best.pt` as a research candidate for the “DLSSNR 5
look” branch. Do not merge it into OpenNR’s protected native-teacher/student
lineage and do not install it in Skyrim yet.

The next useful offline step, if desired, is a larger manually reviewed category
set or a small style/control sweep around this RGB student. More raw Skyrim
captures are not required to make the current decision. New data becomes
worthwhile only if we deliberately target a missing visual regime—especially
dark interiors and the hard third sequence—or if a later experiment adds a
real temporal/context contract. Any such data should remain sequence-disjoint
from this frozen test and should not be used to retroactively tune these scores.
