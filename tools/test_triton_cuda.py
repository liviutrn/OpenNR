"""Minimal isolated Triton/CUDA smoke test for the OpenNR research venv."""

import torch
import triton
import triton.language as tl


@triton.jit
def add_kernel(x, y, out, n: tl.constexpr, block: tl.constexpr):
    offsets = tl.program_id(0) * block + tl.arange(0, block)
    mask = offsets < n
    tl.store(out + offsets, tl.load(x + offsets, mask=mask, other=0) + tl.load(y + offsets, mask=mask, other=0), mask=mask)


def main() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    x = torch.randn(1 << 20, device="cuda", dtype=torch.float16)
    y = torch.randn_like(x)
    out = torch.empty_like(x)
    add_kernel[(triton.cdiv(x.numel(), 256),)](x, y, out, x.numel(), 256)
    torch.cuda.synchronize()
    print({
        "triton": triton.__version__,
        "torch": torch.__version__,
        "gpu": torch.cuda.get_device_name(0),
        "max_error": float((out - (x + y)).abs().max().item()),
    })


if __name__ == "__main__":
    main()
