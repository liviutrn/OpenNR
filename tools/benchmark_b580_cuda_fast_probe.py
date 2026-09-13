#!/usr/bin/env python3
"""Benchmark the public NR-B580 fused adapter stack on CUDA.

This is an isolated external-research probe.  It uses the hash-verified
serialized resource recovered from the local DLSS-NR DLL, installs the public
project's FP16 fusion adapters, and measures the observed 256x256 reset body.
It does not modify the OpenNR runtime or claim full-resolution/temporal/VR
readiness.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np
import torch
import triton
import triton.language as tl


def _image(path: Path, device: str, *, height: int, width: int) -> torch.Tensor:
    from PIL import Image

    image = Image.open(path).convert("RGB").resize((width, height), Image.Resampling.BOX)
    values = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(values).to(device=device, dtype=torch.float16).contiguous()


def _make_probe_noise_tables(device: str):
    """Create complete synthetic lookup tables for a front-kernel speed probe.

    The public project does not ship its authenticated native table asset. These
    tables have the right shape/device contract and conventional Box-Muller
    contents, but they are not claimed to reproduce NVIDIA's table bit-for-bit.
    """

    n = 1 << 24
    u = (torch.arange(n, device=device, dtype=torch.float32) + 1.0) / float(n)
    angle = u * (2.0 * torch.pi)
    radius = torch.sqrt(-2.0 * torch.log(u)).contiguous()
    sine = torch.sin(angle).contiguous()
    cosine = torch.cos(angle).contiguous()
    del u, angle
    return SimpleNamespace(radius=radius, sine=sine, cosine=cosine)


def _event_ms(callback) -> tuple[float, torch.Tensor]:
    start = torch.cuda.Event(enable_timing=True)
    end = torch.cuda.Event(enable_timing=True)
    start.record()
    output = callback()
    end.record()
    end.synchronize()
    return float(start.elapsed_time(end)), output


@triton.jit
def _fp8_matmul_kernel(A, W, INITIAL, OUT, M: tl.constexpr, N: tl.constexpr,
                       K: tl.constexpr, INITIALIZED: tl.constexpr,
                       BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    """Probe FP8 dot: convert dynamic half activations in-register."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    acc = tl.zeros((BM, BN), dtype=tl.float32)
    for start in range(0, K, BK):
        kk = start + tl.arange(0, BK)
        av = tl.load(A + rows[:, None] * K + kk[None, :],
                     (rows[:, None] < M) & (kk[None, :] < K), other=0.0).to(tl.float8e4nv)
        wv = tl.load(W + kk[:, None] * N + cols[None, :],
                     (kk[:, None] < K) & (cols[None, :] < N), other=0.0)
        acc = tl.dot(av, wv, acc, out_dtype=tl.float32)
    offset = rows[:, None] * N + cols[None, :]
    valid = (rows[:, None] < M) & (cols[None, :] < N)
    if INITIALIZED:
        acc += tl.load(INITIAL + offset, valid, other=0.0).to(tl.float32)
    tl.store(OUT + offset, acc.to(tl.float16), valid)


def _fp8_dot(a, weight, *, chunk_k: int, initial=None, cached_weight=None):
    if a.device != weight.device or weight.ndim != 2 or a.shape[-1] != weight.shape[0]:
        raise ValueError("Expected compatible matrices on one device")
    if chunk_k not in (8, 16) or a.shape[-1] % chunk_k:
        raise ValueError("Expected complete K8/K16 groups")
    shape = (*a.shape[:-1], weight.shape[-1])
    if initial is not None and (initial.device != a.device or initial.shape != shape):
        raise ValueError("Initial accumulator must match output")
    aa = a.half().contiguous().reshape(-1, a.shape[-1])
    ww = cached_weight if cached_weight is not None else weight.half().contiguous().to(torch.float8_e4m3fn)
    init = aa if initial is None else initial.half().contiguous()
    out = torch.empty(shape, device=a.device, dtype=torch.float16)
    m, k = aa.shape
    n = ww.shape[1]
    # CUDA FP8 dot requires N >= 16; mask the extra columns for the final
    # eight-channel head projection.
    bn = 32 if n >= 16 else 16
    # Triton's CUDA FP8 dot path requires a K tile of at least 32. For the
    # recovered K8/K16 logical boundaries, zero-masked padding preserves the
    # same matrix product while allowing the hardware FP8 instruction path.
    block_k = max(32, chunk_k)
    _fp8_matmul_kernel[(triton.cdiv(m, 16), triton.cdiv(n, bn))](
        aa, ww, init, out, m, n, k, initial is not None, 16, bn, block_k,
        num_warps=4, enable_fp_fusion=False)
    return out


@triton.jit
def _k8_matmul_kernel(A, W, INITIAL, OUT, M: tl.constexpr, N: tl.constexpr,
                      K: tl.constexpr, INITIALIZED: tl.constexpr,
                      BM: tl.constexpr, BN: tl.constexpr):
    """Specialized half GEMM for logical reductions made of K8 groups.

    The public FP16 probe used a generic K32 loop with masked lanes for the
    K8/K16 logical boundaries. This kernel removes that padding while retaining
    the ordinary FP16 accumulation used by the speed branch. The recovered
    model uses total K values of 16 and 32 for this dispatch family.
    """

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    valid = (rows[:, None] < M) & (cols[None, :] < N)
    kk = tl.arange(0, K)
    av = tl.load(A + rows[:, None] * K + kk[None, :], rows[:, None] < M, other=0.0)
    wv = tl.load(W + kk[:, None] * N + cols[None, :], cols[None, :] < N, other=0.0)
    acc = tl.dot(av, wv, out_dtype=tl.float32)
    offset = rows[:, None] * N + cols[None, :]
    if INITIALIZED:
        acc += tl.load(INITIAL + offset, valid, other=0.0).to(tl.float32)
    tl.store(OUT + offset, acc.to(tl.float16), valid)


def _k8_dot(a, weight, *, initial=None, bm=16, bn=32, warps=4, stages=1):
    """Run the ordinary FP16 K8 product without a masked K32 loop."""

    if a.device != weight.device or weight.ndim != 2 or weight.shape[0] not in (16, 32):
        raise ValueError("Expected a dense matrix with K8 groups")
    shape = (*a.shape[:-1], weight.shape[-1])
    if initial is not None and (initial.device != a.device or initial.shape != shape):
        raise ValueError("Initial accumulator must match output")
    if bm not in (16, 32, 64) or bn not in (8, 16, 32, 64):
        raise ValueError("Unsupported K8 tile")
    aa = a.half().contiguous().reshape(-1, weight.shape[0])
    ww = weight.half().contiguous()
    init = aa if initial is None else initial.half().contiguous().reshape(-1, shape[-1])
    out = torch.empty(shape, device=a.device, dtype=torch.float16)
    m, n = aa.shape[0], ww.shape[1]
    k = ww.shape[0]
    compiled = _k8_matmul_kernel[(triton.cdiv(m, bm), triton.cdiv(n, bn))](
        aa, ww, init, out, m, n, k, initial is not None, bm, bn,
        num_warps=warps, num_stages=stages, enable_fp_fusion=False,
    )
    return out, compiled


@triton.jit
def _fp16_dense_kernel(A, W, INITIAL, OUT, M: tl.constexpr, N: tl.constexpr,
                       K: tl.constexpr, INITIALIZED: tl.constexpr,
                       BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    """Tunable ordinary FP16 dense product for the K16 dispatch family."""

    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    valid = (rows[:, None] < M) & (cols[None, :] < N)
    acc = tl.zeros((BM, BN), dtype=tl.float32)
    for start in range(0, K, BK):
        kk = start + tl.arange(0, BK)
        av = tl.load(A + rows[:, None] * K + kk[None, :],
                     (rows[:, None] < M) & (kk[None, :] < K), other=0.0)
        wv = tl.load(W + kk[:, None] * N + cols[None, :],
                     (kk[:, None] < K) & (cols[None, :] < N), other=0.0)
        acc = tl.dot(av, wv, acc, out_dtype=tl.float32)
    offset = rows[:, None] * N + cols[None, :]
    if INITIALIZED:
        acc += tl.load(INITIAL + offset, valid, other=0.0).to(tl.float32)
    tl.store(OUT + offset, acc.to(tl.float16), valid)


def _fp16_dense_dot(a, weight, *, initial=None, bm=16, bn=32, bn_small=None,
                    bk=32, warps=4, stages=1):
    """Run a tunable FP16 dense product without the generic provider tile."""

    if a.device != weight.device or weight.ndim != 2 or a.shape[-1] != weight.shape[0]:
        raise ValueError("Expected compatible dense matrices")
    if (bm not in (16, 32, 64) or bn not in (16, 32, 64)
            or (bn_small is not None and bn_small not in (16, 32, 64))
            or bk not in (16, 32, 64, 128)):
        raise ValueError("Unsupported dense tile")
    shape = (*a.shape[:-1], weight.shape[-1])
    if initial is not None and (initial.device != a.device or initial.shape != shape):
        raise ValueError("Initial accumulator must match output")
    aa = a.half().contiguous().reshape(-1, a.shape[-1])
    ww = weight.half().contiguous()
    init = aa if initial is None else initial.half().contiguous().reshape(-1, shape[-1])
    out = torch.empty(shape, device=a.device, dtype=torch.float16)
    m, k = aa.shape
    n = ww.shape[1]
    if k < 16 or k % 16:
        raise ValueError("Tunable dense path expects K divisible by 16")
    selected_bn = bn if bn_small is None or n > 32 else bn_small
    compiled = _fp16_dense_kernel[(triton.cdiv(m, bm), triton.cdiv(n, selected_bn))](
        aa, ww, init, out, m, n, k, initial is not None, bm, selected_bn, bk,
        num_warps=warps, num_stages=stages, enable_fp_fusion=False,
    )
    return out, compiled


@triton.jit
def _fp16_batched_kernel(A, W, INITIAL, OUT, M: tl.constexpr, N: tl.constexpr,
                         K: tl.constexpr, INITIALIZED: tl.constexpr,
                         BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    """Tunable ordinary FP16 product for the batched K16 path."""

    batch = tl.program_id(2)
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    valid = (rows[:, None] < M) & (cols[None, :] < N)
    acc = tl.zeros((BM, BN), dtype=tl.float32)
    for start in range(0, K, BK):
        kk = start + tl.arange(0, BK)
        av = tl.load(A + (batch * M + rows[:, None]) * K + kk[None, :],
                     (rows[:, None] < M) & (kk[None, :] < K), other=0.0)
        wv = tl.load(W + (batch * K + kk[:, None]) * N + cols[None, :],
                     (kk[:, None] < K) & (cols[None, :] < N), other=0.0)
        acc = tl.dot(av, wv, acc, out_dtype=tl.float32)
    offset = (batch * M + rows[:, None]) * N + cols[None, :]
    if INITIALIZED:
        acc += tl.load(INITIAL + offset, valid, other=0.0).to(tl.float32)
    tl.store(OUT + offset, acc.to(tl.float16), valid)


def _fp16_batched_dot(a, weight, *, initial=None, bm=16, bn=32, bk=32,
                      warps=4, stages=1):
    """Run a tunable ordinary FP16 batched product."""

    if (a.device != weight.device or a.ndim < 3 or weight.ndim != a.ndim
            or a.shape[:-2] != weight.shape[:-2] or a.shape[-1] != weight.shape[-2]):
        raise ValueError("Expected compatible batched matrices")
    shape = (*a.shape[:-1], weight.shape[-1])
    if initial is not None and (initial.device != a.device or initial.shape != shape):
        raise ValueError("Initial accumulator must match output")
    aa = a.half().contiguous().reshape(-1, a.shape[-2], a.shape[-1])
    ww = weight.half().contiguous().reshape(-1, weight.shape[-2], weight.shape[-1])
    init = aa if initial is None else initial.half().contiguous().reshape(-1, a.shape[-2], weight.shape[-1])
    out = torch.empty(shape, device=a.device, dtype=torch.float16)
    batches, m, k = aa.shape
    n = ww.shape[-1]
    if k < 16 or k % 16:
        raise ValueError("Tunable batched path expects K divisible by 16")
    compiled = _fp16_batched_kernel[(triton.cdiv(m, bm), triton.cdiv(n, bn), batches)](
        aa, ww, init, out, m, n, k, initial is not None, bm, bn, bk,
        num_warps=warps, num_stages=stages, enable_fp_fusion=False,
    )
    return out, compiled


def _cublas_fp16_dot(a, weight, *, initial=None):
    """Use the framework's native FP16 GEMM as a library control."""

    if a.device != weight.device or weight.ndim != 2 or a.shape[-1] != weight.shape[0]:
        raise ValueError("Expected compatible dense matrices")
    shape = (*a.shape[:-1], weight.shape[-1])
    aa = a.half().contiguous().reshape(-1, a.shape[-1])
    ww = weight.half().contiguous()
    if initial is None:
        out = torch.mm(aa, ww)
    else:
        init = initial.half().contiguous().reshape(-1, shape[-1])
        out = torch.addmm(init, aa, ww)
    return out.reshape(shape)


def _cublas_fp8_dot(a, weight, *, initial=None, cached_weight, scales):
    """Use cuBLASLt's scaled FP8 GEMM where its shape contract permits it."""

    shape = (*a.shape[:-1], weight.shape[-1])
    aa = a.half().contiguous().reshape(-1, a.shape[-1]).to(torch.float8_e4m3fn)
    if cached_weight is None:
        logical = weight.half().contiguous().to(torch.float8_e4m3fn)
        cached_weight = torch.empty_strided(
            logical.shape, (1, logical.shape[0]), device=logical.device,
            dtype=torch.float8_e4m3fn
        )
        cached_weight.copy_(logical)
    scale = scales.get(aa.device)
    if scale is None:
        scale = torch.ones((1,), device=aa.device, dtype=torch.float32)
        scales[aa.device] = scale
    result = torch._scaled_mm(aa, cached_weight, scale_a=scale, scale_b=scale,
                              out_dtype=torch.float16)
    out = result[0] if isinstance(result, tuple) else result
    if initial is not None:
        out = (out + initial.half().contiguous().reshape(-1, shape[-1])).half()
    return out.reshape(shape)


def _baseline(model, rgb, front, *, warmup: int, iterations: int):
    from nr_backend.execution import use_arithmetic_backend

    times = []
    output = None
    with torch.inference_mode(), use_arithmetic_backend("triton"):
        for _ in range(warmup):
            output = model._forward_front(rgb, front)
        torch.cuda.synchronize()
        for _ in range(iterations):
            elapsed, output = _event_ms(lambda: model._forward_front(rgb, front))
            times.append(elapsed)
    return times, output


def _install_fast_stack(model, snapshots: Path, branch_mode: str, k8_mode: str, *,
                        c32_mode: str,
                        c32_bm: int, c32_warps: int, c32_stages: int,
                        swin_bm: int, swin_warps: int, swin_stages: int,
                        head_bm: int, head_warps: int, head_stages: int,
                        head_normalize: bool, head_swin: bool,
                        branch_pair_warps: int, branch_project_warps: int,
                        branch_project_stages: int, branch_pair_bm: int | None,
                        branch_project_bm: int | None, branch_project_bn: int | None,
                        vit_bm: int, vit_bn: int, vit_large_bn: int,
                        vit_stages: int, k8_bm: int, k8_bn: int,
                        k8_warps: int, k8_stages: int, dense_mode: str,
                        dense_bm: int, dense_bn: int, dense_bk: int,
                        dense_bn_small: int | None, dense_warps: int,
                        dense_stages: int, batched_mode: str,
                        batched_bm: int, batched_bn: int, batched_bk: int,
                        batched_warps: int, batched_stages: int):
    """Return a provider plus scoped adapters for ExitStack."""

    if str(snapshots) not in sys.path:
        sys.path.insert(0, str(snapshots))

    from fast_matrices_v3 import FastMatrices, dot as fast_dot
    if c32_mode == "direct":
        from fused_c32_mlp_v1 import FusedC32
    elif c32_mode == "lut":
        _make_lut(model)
        from fused_c32_mlp_lut_v1 import FusedC32
    else:
        raise ValueError(f"unsupported C32 mode: {c32_mode}")
    from fused_branched_pairs_v1 import FusedPairs
    from batched_branched_mlp_v2 import FusedBatched
    from fused_split_ffwd_v2 import FusedSplit
    from fused_vit_projection_v3 import FusedVitProjection
    from fused_swin_native_half_v1 import FusedSwin
    from native_half_head_layout_v1 import HeadLayout

    if k8_mode == "fp16":
        class K8FastMatrices(FastMatrices):
            """Probe-only ordinary FP16 replacement for exact K8 arithmetic."""

            def dense(self, a, w, *, chunk_k, initial=None, **kwargs):
                if self.mode == "fp16_xmx" and chunk_k == 8:
                    out, compiled = fast_dot(a, w, initial=initial)
                    self.record("fp16_dense_k8")
                    if "fp16_dense_k8" not in self.compiled:
                        self.compiled["fp16_dense_k8"] = compiled
                    return out
                return super().dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider = K8FastMatrices()
    elif k8_mode == "specialized":
        class SpecializedK8FastMatrices(FastMatrices):
            """Probe-only FP16 K8 kernel with no masked K32 padding."""

            def dense(self, a, w, *, chunk_k, initial=None, **kwargs):
                if self.mode == "fp16_xmx" and chunk_k == 8:
                    out, compiled = _k8_dot(
                        a, w, initial=initial, bm=k8_bm, bn=k8_bn,
                        warps=k8_warps, stages=k8_stages,
                    )
                    self.record("fp16_specialized_k8")
                    if "fp16_specialized_k8" not in self.compiled:
                        self.compiled["fp16_specialized_k8"] = compiled
                    return out
                return super().dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider = SpecializedK8FastMatrices()
    elif k8_mode == "fp8":
        class FP8FastMatrices(FastMatrices):
            """Probe-only FP8 dot path; weights are cached per buffer identity."""

            def __init__(self):
                super().__init__()
                self.fp8_weights = {}

            def dense(self, a, w, *, chunk_k, initial=None, **kwargs):
                if self.mode == "fp16_xmx" and chunk_k in (8, 16):
                    item = self.fp8_weights.get(id(w))
                    if item is None or item[0] is not w:
                        item = (w, w.half().contiguous().to(torch.float8_e4m3fn))
                        self.fp8_weights[id(w)] = item
                    out = _fp8_dot(a, w, chunk_k=chunk_k, initial=initial,
                                   cached_weight=item[1])
                    self.record("fp8_dense_k" + str(chunk_k))
                    return out
                return super().dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider = FP8FastMatrices()
    elif k8_mode == "cublas-fp8":
        class CublasFP8FastMatrices(FastMatrices):
            """Mixed probe: cuBLASLt FP8 for supported K16 GEMMs, FP16 K8."""

            def __init__(self):
                super().__init__()
                self.fp8_weights = {}
                self.scales = {}

            def dense(self, a, w, *, chunk_k, initial=None, **kwargs):
                if self.mode == "fp16_xmx" and chunk_k == 8:
                    out, compiled = fast_dot(a, w, initial=initial)
                    self.record("fp16_dense_k8")
                    if "fp16_dense_k8" not in self.compiled:
                        self.compiled["fp16_dense_k8"] = compiled
                    return out
                if (self.mode == "fp16_xmx" and chunk_k == 16 and
                        w.ndim == 2 and w.shape[1] >= 16 and w.shape[1] % 16 == 0):
                    item = self.fp8_weights.get(id(w))
                    if item is None or item[0] is not w:
                        logical = w.half().contiguous().to(torch.float8_e4m3fn)
                        packed = torch.empty_strided(
                            logical.shape, (1, logical.shape[0]),
                            device=logical.device, dtype=torch.float8_e4m3fn
                        )
                        packed.copy_(logical)
                        item = (w, packed)
                        self.fp8_weights[id(w)] = item
                    out = _cublas_fp8_dot(a, w, initial=initial,
                                          cached_weight=item[1], scales=self.scales)
                    self.record("cublas_fp8_dense_k16")
                    return out
                return super().dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider = CublasFP8FastMatrices()
    else:
        provider = FastMatrices()
    if dense_mode == "tuned":
        original_dense = provider.dense

        def tuned_dense(a, w, *, chunk_k, initial=None, **kwargs):
            if provider.mode == "fp16_xmx" and chunk_k == 16:
                out, compiled = _fp16_dense_dot(
                    a, w, initial=initial, bm=dense_bm, bn=dense_bn,
                    bn_small=dense_bn_small, bk=dense_bk,
                    warps=dense_warps, stages=dense_stages,
                )
                provider.record("fp16_tuned_dense")
                if "fp16_tuned_dense" not in provider.compiled:
                    provider.compiled["fp16_tuned_dense"] = compiled
                return out
            return original_dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider.dense = tuned_dense
    elif dense_mode not in ("snapshot", "cublas"):
        raise ValueError(f"unsupported dense mode: {dense_mode}")
    if dense_mode == "cublas":
        original_dense = provider.dense

        def cublas_dense(a, w, *, chunk_k, initial=None, **kwargs):
            if provider.mode == "fp16_xmx" and chunk_k == 16:
                out = _cublas_fp16_dot(a, w, initial=initial)
                provider.record("cublas_fp16_dense")
                return out
            return original_dense(a, w, chunk_k=chunk_k, initial=initial, **kwargs)

        provider.dense = cublas_dense
    if batched_mode == "tuned":
        original_batched = provider.batched

        def tuned_batched(a, w, *, initial=None, **kwargs):
            if provider.mode == "fp16_xmx":
                out, compiled = _fp16_batched_dot(
                    a, w, initial=initial, bm=batched_bm, bn=batched_bn,
                    bk=batched_bk, warps=batched_warps, stages=batched_stages,
                )
                provider.record("fp16_tuned_batched")
                if "fp16_tuned_batched" not in provider.compiled:
                    provider.compiled["fp16_tuned_batched"] = compiled
                return out
            return original_batched(a, w, initial=initial, **kwargs)

        provider.batched = tuned_batched
    elif batched_mode != "snapshot":
        raise ValueError(f"unsupported batched mode: {batched_mode}")
    provider.select("fp16_xmx")
    adapters = [
        FusedC32(model, provider, bm=c32_bm, warps=c32_warps, stages=c32_stages),
        FusedSplit(model, provider, bm=16, bn=64, stages=1),
        FusedVitProjection(model, provider, bm=vit_bm, bn=vit_bn,
                           large_bn=vit_large_bn, stages=vit_stages),
        HeadLayout(model, provider, normalize=head_normalize, swin=head_swin,
                   head_bm=head_bm, head_warps=head_warps, head_stages=head_stages),
        FusedSwin(provider, bm=swin_bm, warps=swin_warps, stages=swin_stages),
    ]
    if branch_mode == "pairs":
        adapters.append(FusedPairs(model, provider, channels=(64, 128, 256), bm=16, warps=4, stages=1))
    elif branch_mode == "batched":
        if not hasattr(model, "_cubic_fp8_lut_bits"):
            _make_lut(model)
        branch_adapter = FusedBatched(
            model, provider, workload="full",
            pair_warps=branch_pair_warps,
            project_warps=branch_project_warps,
            project_stages=branch_project_stages,
        )
        for channels, options in branch_adapter.configurations.items():
            if branch_pair_bm is not None:
                options["pair_bm"] = branch_pair_bm
            if branch_project_bm is not None:
                options["project_bm"] = branch_project_bm
            if branch_project_bn is not None:
                options["project_bn"] = branch_project_bn
        adapters.append(branch_adapter)
    elif branch_mode == "none":
        pass
    else:
        raise ValueError(f"unsupported branch mode: {branch_mode}")
    return provider, adapters


def _fast(model, rgb, front, *, snapshots: Path, branch_mode: str, k8_mode: str, c32_mode: str,
          cuda_graph: bool,
          profile_stages: bool, warmup: int, iterations: int,
          c32_bm: int, c32_warps: int, c32_stages: int,
          swin_bm: int, swin_warps: int, swin_stages: int,
          head_bm: int, head_warps: int, head_stages: int,
          head_normalize: bool, head_swin: bool,
          branch_pair_warps: int, branch_project_warps: int,
          branch_project_stages: int, branch_pair_bm: int | None,
          branch_project_bm: int | None, branch_project_bn: int | None,
          vit_bm: int, vit_bn: int, vit_large_bn: int, vit_stages: int,
          k8_bm: int, k8_bn: int, k8_warps: int, k8_stages: int,
          dense_mode: str, dense_bm: int, dense_bn: int, dense_bk: int,
          dense_bn_small: int | None, dense_warps: int, dense_stages: int,
          batched_mode: str,
          batched_bm: int, batched_bn: int, batched_bk: int,
          batched_warps: int, batched_stages: int):
    from nr_backend.execution import use_arithmetic_backend

    provider, adapters = _install_fast_stack(
        model, snapshots, branch_mode, k8_mode,
        c32_mode=c32_mode,
        c32_bm=c32_bm, c32_warps=c32_warps, c32_stages=c32_stages,
        swin_bm=swin_bm, swin_warps=swin_warps, swin_stages=swin_stages,
        head_bm=head_bm, head_warps=head_warps, head_stages=head_stages,
        head_normalize=head_normalize, head_swin=head_swin,
        branch_pair_warps=branch_pair_warps,
        branch_project_warps=branch_project_warps,
        branch_project_stages=branch_project_stages,
        branch_pair_bm=branch_pair_bm,
        branch_project_bm=branch_project_bm,
        branch_project_bn=branch_project_bn,
        vit_bm=vit_bm,
        vit_bn=vit_bn,
        vit_large_bn=vit_large_bn,
        vit_stages=vit_stages,
        k8_bm=k8_bm,
        k8_bn=k8_bn,
        k8_warps=k8_warps,
        k8_stages=k8_stages,
        dense_mode=dense_mode,
        dense_bm=dense_bm,
        dense_bn=dense_bn,
        dense_bk=dense_bk,
        dense_bn_small=dense_bn_small,
        dense_warps=dense_warps,
        dense_stages=dense_stages,
        batched_mode=batched_mode,
        batched_bm=batched_bm,
        batched_bn=batched_bn,
        batched_bk=batched_bk,
        batched_warps=batched_warps,
        batched_stages=batched_stages,
    )
    times = []
    output = None
    with ExitStack() as stack:
        stack.enter_context(provider.installed())
        for adapter in adapters:
            stack.enter_context(adapter.installed())
        with torch.inference_mode(), use_arithmetic_backend("triton") as dispatches:
            for _ in range(warmup):
                output = model._forward_front(rgb, front)
            torch.cuda.synchronize()
            profile = []
            if profile_stages:
                previous = time.perf_counter()

                def mark(name):
                    nonlocal previous
                    torch.cuda.synchronize()
                    now = time.perf_counter()
                    profile.append({"stage": name, "elapsed_ms": (now - previous) * 1000.0})
                    previous = now

                output = model._forward_front(rgb, front, progress=mark)
                torch.cuda.synchronize()
            if cuda_graph:
                static_rgb = rgb.clone(memory_format=torch.contiguous_format)
                static_front = front.clone(memory_format=torch.contiguous_format)
                graph = torch.cuda.CUDAGraph()
                with torch.cuda.graph(graph):
                    captured_output = model._forward_front(static_rgb, static_front)
                torch.cuda.synchronize()
                for _ in range(iterations):
                    elapsed, _ = _event_ms(graph.replay)
                    times.append(elapsed)
                output = captured_output
            else:
                for _ in range(iterations):
                    elapsed, output = _event_ms(lambda: model._forward_front(rgb, front))
                    times.append(elapsed)
    return times, output, dict(dispatches), provider, adapters, profile


def _make_lut(model):
    """Build an in-memory cubic+FP8 table for the batched branch path.

    The published snapshot's LUT asset is intentionally absent from the public
    release. This probe does not silently claim that a generated table has the
    publisher's authenticated hash; it is only a portability/performance
    control for this experiment.
    """

    if hasattr(model, "_cubic_fp8_lut_bits"):
        return getattr(model, "_cubic_fp8_lut_bits")

    from nr_backend.execution import use_arithmetic_backend
    from nr_backend.pre_mlp import cubic_quantize

    bits = torch.arange(65536, dtype=torch.int32).to(torch.int16).view(torch.float16)
    device = model.pre.front_weight.device
    # Generate the probe table with the same Triton cubic+FP8 kernel used by
    # the direct fused path.  The public authenticated LUT asset is absent;
    # this is therefore a local, reproducible control rather than a parity
    # claim about the publisher's table.
    if device.type in ('xpu', 'cuda'):
        with use_arithmetic_backend('triton'):
            table = cubic_quantize(bits.to(device)).view(torch.int16).clone()
    else:
        table = cubic_quantize(bits).view(torch.int16).clone().to(device)
    model.register_buffer("_cubic_fp8_lut_bits", table)
    return table


def _apply_skip_policy(model, policy: str) -> list[str]:
    """Install probe-only identity blocks for a structural ablation.

    The skipped modules are intentionally limited to shape-preserving blocks.
    Downsample and upsample boundaries, the final C512->C1024 transition, and
    the post block remain active.  Inputs already sit at an FP8 boundary, so an
    identity preserves the executor's tensor contract while removing the
    selected learned transform.  This is an approximation experiment, not a
    claim that NVIDIA skips these blocks.
    """

    if policy == "none":
        return []

    skipped: list[str] = []

    def skip_forward(module, label: str) -> None:
        module.forward = lambda features: features
        skipped.append(label)

    def skip_outputs(module, label: str) -> None:
        module.forward = lambda features: features
        module.forward_outputs = lambda features: (features, None)
        skipped.append(label)

    def skip_boundaries(module, label: str) -> None:
        module.forward = lambda features: features
        module.forward_boundaries = lambda features: (features, features, features, features)
        skipped.append(label)

    if policy in ("vit-half", "half"):
        for index in (1, 3, 5, 7):
            skip_forward(model.vit[index], f"vit[{index}]")

    if policy in ("body-half", "half"):
        for group_index, group in enumerate(model.encoder):
            for block_index, block in enumerate(group):
                # The last member performs the group's downsample and must stay.
                if block_index % 2 == 1 and block_index != len(group) - 1:
                    skip_outputs(block, f"encoder[{group_index}][{block_index}]")
        for block_index, block in enumerate(model.encoder512):
            # The final member produces the C1024 transition and must stay.
            if block_index % 2 == 1 and block_index != len(model.encoder512) - 1:
                skip_boundaries(block, f"encoder512[{block_index}]")
        for block_index, block in enumerate(model.decoder512):
            if block_index % 2 == 1:
                skip_boundaries(block, f"decoder512[{block_index}]")
        for group_index, group in enumerate(model.decoder):
            # group[0] is the learned upsample/skip boundary; only body blocks
            # after it are eligible for the identity ablation.
            for block_index, block in enumerate(group[1:], start=1):
                if block_index % 2 == 1:
                    skip_forward(block, f"decoder[{group_index}][{block_index}]")

    if policy not in ("none", "vit-half", "body-half", "half"):
        raise ValueError(f"unsupported skip policy: {policy}")
    return skipped


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--rgb-png", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--branch-mode", choices=("pairs", "batched", "none"), default="pairs")
    parser.add_argument("--c32-mode", choices=("direct", "lut"), default="direct")
    parser.add_argument("--k8-mode", choices=("exact", "fp16", "specialized", "fp8", "cublas-fp8"), default="exact")
    parser.add_argument("--front-mode", choices=("analytic", "dynamic-probe"), default="analytic")
    parser.add_argument("--skip-policy", choices=("none", "vit-half", "body-half", "half"), default="none")
    parser.add_argument("--c32-bm", type=int, choices=(16, 32), default=32)
    parser.add_argument("--c32-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--c32-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--swin-bm", type=int, choices=(16, 32, 64), default=32)
    parser.add_argument("--swin-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--swin-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--head-bm", type=int, choices=(16, 32, 64), default=32)
    parser.add_argument("--head-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--head-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--head-normalize", choices=("native", "old"), default="native")
    parser.add_argument("--head-swin", choices=("native", "old"), default="native")
    parser.add_argument("--branch-pair-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--branch-project-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--branch-project-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--branch-pair-bm", type=int, choices=(16, 32), default=None)
    parser.add_argument("--branch-project-bm", type=int, choices=(16, 32), default=None)
    parser.add_argument("--branch-project-bn", type=int, choices=(32, 64), default=None)
    parser.add_argument("--vit-bm", type=int, choices=(16, 32), default=32)
    parser.add_argument("--vit-bn", type=int, choices=(32, 64), default=32)
    parser.add_argument("--vit-large-bn", type=int, choices=(32, 64), default=64)
    parser.add_argument("--vit-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--k8-bm", type=int, choices=(16, 32, 64), default=16)
    parser.add_argument("--k8-bn", type=int, choices=(8, 16, 32, 64), default=32)
    parser.add_argument("--k8-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--k8-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--dense-mode", choices=("snapshot", "tuned", "cublas"), default="snapshot")
    parser.add_argument("--dense-bm", type=int, choices=(16, 32, 64), default=16)
    parser.add_argument("--dense-bn", type=int, choices=(16, 32, 64), default=32)
    parser.add_argument("--dense-bn-small", type=int, choices=(16, 32, 64), default=None)
    parser.add_argument("--dense-bk", type=int, choices=(16, 32, 64, 128), default=32)
    parser.add_argument("--dense-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--dense-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--batched-mode", choices=("snapshot", "tuned"), default="snapshot")
    parser.add_argument("--batched-bm", type=int, choices=(16, 32, 64), default=16)
    parser.add_argument("--batched-bn", type=int, choices=(16, 32, 64), default=32)
    parser.add_argument("--batched-bk", type=int, choices=(16, 32, 64, 128), default=32)
    parser.add_argument("--batched-warps", type=int, choices=(4, 8), default=4)
    parser.add_argument("--batched-stages", type=int, choices=(1, 2), default=1)
    parser.add_argument("--cuda-graph", action="store_true")
    parser.add_argument("--profile-stages", action="store_true")
    parser.add_argument("--height", type=int, default=256)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    if args.warmup < 0 or args.iterations < 1:
        raise ValueError("warmup must be non-negative and iterations must be positive")
    contracts = {
        (256, 256): (320, 320),
        (512, 512): (512, 576),
        (480, 864): (512, 896),
        (1080, 1920): (1152, 1920),
        (1439, 2559): (1472, 2560),
    }
    contract_key = (args.height, args.width)
    if contract_key not in contracts:
        raise ValueError(f"unsupported published contract: {contract_key}; choose one of {sorted(contracts)}")
    padded_size = contracts[contract_key]

    backend_root = args.backend.resolve()
    snapshots = args.snapshots.resolve()
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    from nr_backend.executor import ResetNR
    from nr_backend.weights import load_pinned_records

    weights_path = args.weights.resolve()
    records = load_pinned_records(weights_path)
    rgb = _image(args.rgb_png.resolve(), "cuda", height=args.height, width=args.width)
    if args.front_mode == "dynamic-probe":
        if str(snapshots) not in sys.path:
            sys.path.insert(0, str(snapshots))
        from fused_dynamic_front_v1 import forward as dynamic_front
        noise = _make_probe_noise_tables("cuda")
        front_fn = lambda: dynamic_front(
            rgb, padded_size=padded_size, seed=args.seed, noise_source=noise
        )
    else:
        from nr_backend.front import reset_front_features
        noise = None
        front_fn = lambda: reset_front_features(
            rgb, padded_size=padded_size, seed=args.seed, noise_source=None
        )
    with torch.inference_mode():
        # Exclude one-time Triton compilation from the steady-state front
        # producer measurement, just as the network section is warmed up.
        _ = front_fn()
        torch.cuda.synchronize()
        front_ms, front = _event_ms(front_fn)

    baseline_model = ResetNR(records, None).eval().to("cuda")
    torch.cuda.synchronize()
    baseline_times, baseline_output = _baseline(
        baseline_model, rgb, front, warmup=args.warmup, iterations=1
    )
    baseline_values = baseline_output.detach().float()
    del baseline_model, baseline_output
    torch.cuda.empty_cache()

    fast_model = ResetNR(records, None).eval().to("cuda")
    skipped_blocks = _apply_skip_policy(fast_model, args.skip_policy)
    torch.cuda.synchronize()
    fast_times, fast_output, dispatches, provider, adapters, profile = _fast(
        fast_model,
        rgb,
        front,
        snapshots=snapshots,
        branch_mode=args.branch_mode,
        k8_mode=args.k8_mode,
        c32_mode=args.c32_mode,
        cuda_graph=args.cuda_graph,
        profile_stages=args.profile_stages,
        warmup=args.warmup,
        iterations=args.iterations,
        c32_bm=args.c32_bm,
        c32_warps=args.c32_warps,
        c32_stages=args.c32_stages,
        swin_bm=args.swin_bm,
        swin_warps=args.swin_warps,
        swin_stages=args.swin_stages,
        head_bm=args.head_bm,
        head_warps=args.head_warps,
        head_stages=args.head_stages,
        head_normalize=args.head_normalize == "native",
        head_swin=args.head_swin == "native",
        branch_pair_warps=args.branch_pair_warps,
        branch_project_warps=args.branch_project_warps,
        branch_project_stages=args.branch_project_stages,
        branch_pair_bm=args.branch_pair_bm,
        branch_project_bm=args.branch_project_bm,
        branch_project_bn=args.branch_project_bn,
        vit_bm=args.vit_bm,
        vit_bn=args.vit_bn,
        vit_large_bn=args.vit_large_bn,
        vit_stages=args.vit_stages,
        k8_bm=args.k8_bm,
        k8_bn=args.k8_bn,
        k8_warps=args.k8_warps,
        k8_stages=args.k8_stages,
        dense_mode=args.dense_mode,
        dense_bm=args.dense_bm,
        dense_bn=args.dense_bn,
        dense_bk=args.dense_bk,
        dense_bn_small=args.dense_bn_small,
        dense_warps=args.dense_warps,
        dense_stages=args.dense_stages,
        batched_mode=args.batched_mode,
        batched_bm=args.batched_bm,
        batched_bn=args.batched_bn,
        batched_bk=args.batched_bk,
        batched_warps=args.batched_warps,
        batched_stages=args.batched_stages,
    )
    fast_values = fast_output.detach().float()
    diff = (fast_values - baseline_values).abs()
    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "baseline.npy", baseline_values.cpu().numpy())
    np.save(output_dir / "fast.npy", fast_values.cpu().numpy())
    result = {
        "schema": "opennr-public-b580-cuda-fast-probe-v1",
        "status": "passed",
        "branch_mode": args.branch_mode,
        "c32_mode": args.c32_mode,
        "k8_mode": args.k8_mode,
        "front_mode": args.front_mode,
        "skip_policy": args.skip_policy,
        "skipped_blocks": skipped_blocks,
        "launch_config": {
            "c32": {"bm": args.c32_bm, "warps": args.c32_warps, "stages": args.c32_stages},
            "swin": {"bm": args.swin_bm, "warps": args.swin_warps, "stages": args.swin_stages},
            "multihead": {"bm": args.head_bm, "warps": args.head_warps, "stages": args.head_stages},
            "head_math": {"normalize": args.head_normalize, "swin": args.head_swin},
            "branches": {
                "pair_warps": args.branch_pair_warps,
                "project_warps": args.branch_project_warps,
                "project_stages": args.branch_project_stages,
                "pair_bm": args.branch_pair_bm,
                "project_bm": args.branch_project_bm,
                "project_bn": args.branch_project_bn,
            },
            "vit": {"bm": args.vit_bm, "bn": args.vit_bn,
                    "large_bn": args.vit_large_bn, "stages": args.vit_stages},
            "k8": {"bm": args.k8_bm, "bn": args.k8_bn,
                   "warps": args.k8_warps, "stages": args.k8_stages},
            "dense": {"mode": args.dense_mode, "bm": args.dense_bm,
                       "bn": args.dense_bn, "bn_small": args.dense_bn_small,
                       "bk": args.dense_bk,
                       "warps": args.dense_warps, "stages": args.dense_stages},
            "batched": {"mode": args.batched_mode, "bm": args.batched_bm,
                         "bn": args.batched_bn, "bk": args.batched_bk,
                         "warps": args.batched_warps, "stages": args.batched_stages},
        },
        "cuda_graph": args.cuda_graph,
        "profile_stages": args.profile_stages,
        "contract": {"rgb": [args.height, args.width, 3], "padded_front": [padded_size[0], padded_size[1], 16]},
        "weights": str(weights_path),
        "weights_sha256": hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        "backend": str(backend_root),
        "snapshots": str(snapshots),
        "rgb": str(args.rgb_png.resolve()),
        "gpu": torch.cuda.get_device_name(0),
        "torch": torch.__version__,
        "cuda": torch.version.cuda,
        "warmup": args.warmup,
        "iterations": args.iterations,
        "front_prepare_ms": front_ms,
        "front_compile_warmup": 1,
        "baseline_network_ms_one_sample": baseline_times,
        "fast_network_ms": fast_times,
        "fast_network_median_ms": float(np.median(fast_times)),
        "fast_network_p95_ms": float(np.percentile(fast_times, 95)),
        "speedup_vs_baseline_sample": float(baseline_times[0] / np.median(fast_times)),
        "dispatches": dispatches,
        "provider_calls": provider.calls,
        "provider_compiled_kinds": sorted(provider.compiled),
        "adapter_calls": {type(adapter).__name__: adapter.calls for adapter in adapters if hasattr(adapter, "calls")},
        "profile_stages": profile,
        "output_shape": list(fast_output.shape),
        "output_finite": bool(torch.isfinite(fast_values).all().item()),
        "output_min": float(fast_values.min().item()),
        "output_max": float(fast_values.max().item()),
        "drift_vs_baseline_mae": float(diff.mean().item()),
        "drift_vs_baseline_max": float(diff.max().item()),
        "scope": "offline CUDA execution of the public independent fused adapters at a published fixed contract; no temporal, stereo, Feature 18, or VR acceptance",
    }
    (output_dir / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
