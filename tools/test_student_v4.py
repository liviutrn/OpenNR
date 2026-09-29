"""Smoke tests for the context-v4 style upgrade."""

import sys
from pathlib import Path

import torch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from student_v3 import ContextStudent, ReconstructionConfig
from student_v4 import StyleContextStudent


def main():
    torch.manual_seed(11)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    base = ContextStudent(config).eval()
    upgraded = StyleContextStudent(config).eval()
    upgraded.initialize_v3(base.state_dict())
    rgb = torch.rand(2, 3, 64, 80)
    guides = torch.rand(2, 5, 16, 20)
    context = torch.rand(2, 8, 96, 96)
    with torch.inference_mode():
        reference = base(rgb, guides, context)
        actual = upgraded(rgb, guides, context)
    delta = (reference - actual).abs()
    if delta.max().item() > 1e-7:
        raise AssertionError(f"zero-initialized style branch changed v3 output: {delta.max().item()}")
    upgraded.train()
    rgb.requires_grad_(True)
    pred = upgraded(rgb, guides, context)
    loss = pred.square().mean()
    loss.backward()
    if not torch.isfinite(loss) or not torch.isfinite(rgb.grad).all():
        raise AssertionError("nonfinite v4 loss or input gradient")
    print({"state": "passed", "max_initial_delta": delta.max().item(), "loss": loss.item()})


if __name__ == "__main__":
    main()

