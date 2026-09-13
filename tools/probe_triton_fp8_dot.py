#!/usr/bin/env python3
"""Small CUDA/Triton FP8 dot capability probe; writes no project state."""

import json
import torch
import triton
import triton.language as tl


@triton.jit
def _kernel(A, B, C, M: tl.constexpr, N: tl.constexpr, K: tl.constexpr,
            BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    acc = tl.zeros((BM, BN), dtype=tl.float32)
    for start in range(0, K, BK):
        kk = start + tl.arange(0, BK)
        av = tl.load(A + rows[:, None] * K + kk[None, :])
        bv = tl.load(B + kk[:, None] * N + cols[None, :])
        acc = tl.dot(av, bv, acc, out_dtype=tl.float32)
    tl.store(C + rows[:, None] * N + cols[None, :], acc.to(tl.float16),
             (rows[:, None] < M) & (cols[None, :] < N))


@triton.jit
def _mixed_kernel(A, B, C, M: tl.constexpr, N: tl.constexpr, K: tl.constexpr,
                  BM: tl.constexpr, BN: tl.constexpr, BK: tl.constexpr):
    rows = tl.program_id(0) * BM + tl.arange(0, BM)
    cols = tl.program_id(1) * BN + tl.arange(0, BN)
    acc = tl.zeros((BM, BN), dtype=tl.float32)
    for start in range(0, K, BK):
        kk = start + tl.arange(0, BK)
        av = tl.load(A + rows[:, None] * K + kk[None, :],
                     (rows[:, None] < M) & (kk[None, :] < K), other=0.0).to(tl.float8e4nv)
        bv = tl.load(B + kk[:, None] * N + cols[None, :],
                     (kk[:, None] < K) & (cols[None, :] < N), other=0.0)
        acc = tl.dot(av, bv, acc, out_dtype=tl.float32)
    tl.store(C + rows[:, None] * N + cols[None, :], acc.to(tl.float16))


def main():
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    result = {"torch": torch.__version__, "triton": triton.__version__, "gpu": torch.cuda.get_device_name(0)}
    a = torch.randn((1024, 32), device="cuda", dtype=torch.float16).to(torch.float8_e4m3fn).contiguous()
    b = torch.randn((32, 64), device="cuda", dtype=torch.float16).to(torch.float8_e4m3fn).contiguous()
    c = torch.empty((1024, 64), device="cuda", dtype=torch.float16)
    try:
        kernel = _kernel[(triton.cdiv(1024, 32), triton.cdiv(64, 32))](a, b, c, 1024, 64, 32, 32, 32, 32,
                                                                        num_warps=4, enable_fp_fusion=False)
        torch.cuda.synchronize()
        result.update({"status": "passed", "output_finite": bool(torch.isfinite(c).all().item()),
                       "kernel": str(kernel)})
        b2 = torch.randn((32, 64), device="cuda", dtype=torch.float16).to(torch.float8_e4m3fn).contiguous()
        c2 = torch.empty((1024, 64), device="cuda", dtype=torch.float16)
        mixed = _mixed_kernel[(triton.cdiv(1024, 32), triton.cdiv(64, 32))](
            torch.randn((1024, 32), device="cuda", dtype=torch.float16).contiguous(), b2, c2,
            1024, 64, 32, 32, 32, 32, num_warps=4, enable_fp_fusion=False)
        torch.cuda.synchronize()
        result.update({"mixed_input_conversion": "passed",
                       "mixed_output_finite": bool(torch.isfinite(c2).all().item()),
                       "mixed_kernel": str(mixed)})
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
