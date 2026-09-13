# Recovered DLSS5 NR native-kernel investigation

Date: 2026-09-12  
Status: offline research only; `promotion=false`  
Live runtime changed: no  
Training or new Skyrim captures started: no

## Executive outcome

The public search did not find a repository that publishes a standalone set of
the NVIDIA DLSS5-NR PTX, SASS, CUBIN, or a complete kernel-dump package for
redistribution. The public projects generally publish one of the following
instead:

- an extractor/rebuilder that obtains PTX from a DLL supplied by the user;
- an independently written bridge or AMD/HIP implementation;
- a PTX inventory/parser and address-independent trace schema; or
- native-replay source, numerical rules, and evidence summaries without the
  proprietary CUBIN, weights, or capture tensors.

That is not a blocker for this project. The exact NVIDIA carrier already
available on this machine contains the native material we need for a local,
non-redistributive investigation. The important missing component is the
execution contract around that material: the active launch sequence, parameter
ABI, physical tensor layouts, workspace ownership, and the fusion/scheduling
decisions that turn the logical 71-block graph into a small number of fast
GPU kernels.

## Public-artifact search

### `neural-upstream`

The most relevant public work is
[`matiasLombo/neural-upstream`](https://github.com/matiasLombo/neural-upstream).
Its findings explicitly describe extracting compressed PTX from the user’s
`nvngx_dlssnr.dll`, rewriting unsupported instructions, and assembling a
compatibility runtime locally. Its release assets are add-on DLLs and readme
files, not a checked-in standalone PTX/SASS dump. The repository’s source tree
also contains no files with `.ptx`, `.sass`, `.cubin`, `.fatbin`, or `.hsaco`
extensions.

The findings are still highly relevant: they report roughly 35 MB of readable
PTX, explain the `cp.async.bulk`/`mbarrier` translation boundary, and show that
recompiling the same weights is the route to a fast runtime. This is evidence
that our slow PyTorch timing is an implementation problem, not evidence that
the recovered weights are inherently too slow.

### Native-replay and portable-runtime leads

[`gggz114514-oss/dlss5nr-b580`](https://github.com/gggz114514-oss/dlss5nr-b580)
is the strongest newly found lead for our engineering work. It publishes
native-replay source, native-trace source, numerical/layout rules, and a set of
fused-kernel experiments. Its README explicitly says that the preview does not
include the DLL, model weights, CUBIN, captures, or the complete local
experiment database. It is therefore not a raw NVIDIA dump, but it is more
useful to us than a random prebuilt binary because it exposes the kind of
replay and fusion work required to make an independent backend fast.

[`vladbogun1/dlss5-amd`](https://github.com/vladbogun1/dlss5-amd) provides a
clean-room PE/fatbin inspector, PTX parser, and address-independent dispatch
trace design. It explicitly does not contain or download NVIDIA binaries,
weights, PTX, CUBIN, SDK files, or game assets. This confirms that the portable
research community is keeping the same boundary rather than publishing raw
vendor payloads.

[`0x-punk/DLSS-NR-on-AMD-DUMP-`](https://github.com/0x-punk/DLSS-NR-on-AMD-DUMP-)
publishes analysis of a 34-kernel AMD/HIP implementation and simulated-runtime
artifacts. It is useful for operator-family names and host-side relationships,
but it is not the NVIDIA PTX/SASS dump we are looking for.

One Reddit discussion contains an unverified claim that a researcher extracted
176 CUBINs, SASS, and 174 launches. I did not find those files attached to a
public repository or release, so I am treating that as a lead rather than
usable evidence. The public, inspectable sources above are the basis of this
decision.

## Local native carrier inspection

The local carrier is:

```text
E:\MGO-RC3-fresh\mods\Open Shaders DLSSNR VR 0.5.7 OpenNR\Shaders\Upscaling\Streamline\nvngx_dlssnr.dll
```

Identity:

| Property | Result |
| --- | --- |
| SHA-256 | `E16BCF15E16E13F527491CDF7845B2FE6521A738D8F7C9C721866A8496E1FC8E` |
| File size | 165,840,496 bytes |
| GPU used for load test | RTX 5070 Ti, compute capability 12.0 |
| Driver/tool context | NVIDIA driver 616.56; CUDA tools 13.4.49 |
| PE fatbins | 15 |
| Embedded CUDA ELFs | 15, all targeting `sm_120` |
| Neural families | 6 |
| Neural entry points | 218 |

The first six fatbins are the neural families. The other nine are support,
capture, clear, and resolve kernels. The six neural families map cleanly onto
the logical graph exposed by the recovered source:

| Local family | Native naming | Entry points | Logical role |
| ---: | --- | ---: | --- |
| 0 | 1H / 32 | 38 | pre, post, and 1H/32 fused Swin variants |
| 1 | 2H / 64 | 24 | 2H/64 Swin variants |
| 2 | 4H / 128 | 24 | 4H/128 Swin variants |
| 3 | 8H / 256 | 24 | 8H/256 Swin variants |
| 4 | split 16H / 512 | 46 | split-Swin core, projections, pooling, final head |
| 5 | ViT and 1D ViT | 62 | global/1D transformer compound variants |
| **Total** |  | **218** | 71 logical blocks use these families |

For each of the first six embedded fatbins, the official CUDA binary tools
successfully returned ELF listings, PTX listings, symbol dumps, and resource
usage. The PTX dump was summarized in memory and the temporary fatbin slices
were removed; raw PTX was not retained in the repository.

The summarized PTX contains:

- `.version 9.4`, `.target sm_120`, and 64-bit addressing in every neural
  module;
- 36,422,558 characters of readable neural PTX in the six families, or about
  36.423 MB decimal / 34.735 MiB;
- 218 `.entry` functions, matching the ELF/resource inventory;
- `mma.sync` throughout the neural body;
- `cp.async.bulk`, `mbarrier`, and `elect.sync` concentrated in the split-Swin
  and ViT/1D families;
- no `wgmma` in the summarized PTX;
- global reduction operations in the ViT/1D family.

`nvdisasm` also successfully disassembled the first six temporary ELF slices.
The combined SASS inventory is 478,224 instructions. Representative native
patterns include `HMMA.16816.F16` for the non-FP8 paths,
`QMMA.16832.F16.E4M3.E4M3` for FP8 paths, and the paired E4M3 conversion
instructions around those matrix operations. Representative kernels use
around 168 registers, with family-specific shared-memory footprints. This is
not the resource profile of thousands of ordinary eager PyTorch operators.

## Safety and validation boundary

The CUDA driver test created a private context, loaded every local neural ELF
from memory, resolved all 218 functions, queried representative attributes,
unloaded the modules, and destroyed the context. It did not launch a kernel,
touch the game, patch the DLL, or alter the live OpenNR/MGO installation.

The current result proves:

1. the exact local carrier contains readable native PTX and `sm_120` machine
   code;
2. the six native families correspond to the broad structure of the recovered
   71-block graph; and
3. the supplied CUDA tools can inspect the material without retaining raw
   payloads.

It does **not** yet prove the exact active descriptor sequence, pointer/parameter
ABI, weight offset binding, or that an arbitrary standalone launch will produce
the correct image. Blindly launching a native function with guessed arguments
would be unsafe and would not be a valid parity test.

## Relevance of the AMD profiling result

The AMD reconstruction commit
[`02ad50a`](https://github.com/lmxxf/dlss5-on-amd-9070xt-porting/commit/02ad50abb65dd4ce0341a439a5d5fbbdda39e214)
is directly relevant. Its isolated warm-cache measurements found that the
expensive full-resolution pre block was mainly expensive because it processed
about four times as many tokens as the later half-resolution C32 blocks. It
did not find one pathological kernel whose removal fixed the frame. Removing
the pre-stage Gaussian-noise or color/history pieces did not materially save
time, and LDS slimming/queue overlap did not produce a whole-frame win.

That agrees with our local PyTorch profile and changes the optimization
priority:

- ordinary weight casting will not solve the seconds-versus-milliseconds gap;
- isolated cleanup of one small operator is unlikely to solve it;
- the native-style fused schedule and fixed physical layouts are the main
  opportunity;
- resolution reduction, block skipping, or a smaller network are fallback
  structural levers if the full graph cannot meet the budget.

The AMD author also notes an upload-heap artifact in the standalone harness.
That is a useful reminder to separate GPU-resident timing from host/device
transfer timing, but it does not erase the structural conclusion.

## Decision for OpenNR

No new Skyrim captures are required for this speed investigation. New captures
can still help visual validation or a future student, but they cannot turn the
current eager evaluator into a millisecond runtime. More quantization probes of
the same evaluator are also low priority: the existing weight-only branches
dequantize before the matrix multiply, while the activation-FP8 branch still
retains the un-fused graph.

The next worthwhile experiment is a single, isolated native-style backend
slice:

1. Keep the current recovered graph output as the numerical oracle.
2. Use the local PTX/SASS summaries and the public native-replay research as
   references, but do not redistribute or persist the raw NVIDIA payload.
3. Recover the exact input/output and parameter contract for one repeated
   family, preferably a 1H/32 or 2H/64 block with a complete fixed-size test
   region.
4. Implement one fused fixed-layout slice, including its FP8 boundary and
   residual publication, rather than exporting the whole graph to ONNX first.
5. Compare output bytes/MAE and measure with CUDA events while all buffers stay
   GPU-resident.
6. Require a large speed reduction—ideally the previously defined 30–50x
   representative-region gate—before expanding to all 71 blocks.

If that slice does not approach the required scale, stop and evaluate a
structural reduced-resolution/smaller-network route. If it does, continue the
native-style implementation in an isolated research branch. In either case,
keep `promotion=false` until full Feature 18 contract, stereo, temporal,
runtime, and VR frame-budget validation is separately earned.

## Local evidence artifacts

The non-redistributive summaries and tools are stored here:

```text
D:\.CODEX_Projects\OpenNR-VR\out\dlssnr_native_binary_inventory_20260911\inventory.json
D:\.CODEX_Projects\OpenNR-VR\out\dlssnr_native_binary_inventory_20260911\embedded_cuda_elf.json
D:\.CODEX_Projects\OpenNR-VR\out\dlssnr_native_binary_inventory_20260911\fatbin_cuobjdump_metadata.json
D:\.CODEX_Projects\OpenNR-VR\out\dlssnr_native_binary_inventory_20260911\disassembly_summary_0_to_5_with_resources.json
D:\.CODEX_Projects\OpenNR-VR\out\dlssnr_native_binary_inventory_20260911\driver_module_load_test.json
```

The repeatable inspection code is:

```text
D:\.CODEX_Projects\OpenNR-VR\tools\inventory_dlssnr_native_binary.py
D:\.CODEX_Projects\OpenNR-VR\tools\inventory_embedded_cuda_elf.py
D:\.CODEX_Projects\OpenNR-VR\tools\inspect_embedded_fatbins.py
D:\.CODEX_Projects\OpenNR-VR\tools\summarize_embedded_cuda_disassembly.py
D:\.CODEX_Projects\OpenNR-VR\tools\test_embedded_cuda_module_load.py
```

