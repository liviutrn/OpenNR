"""Contract tests for the zero-initialized temporal extension."""

from __future__ import annotations

from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from student_v2 import ReconstructionConfig  # noqa: E402
from temporal_student import TemporalConfig, TemporalStyleContextStudent  # noqa: E402


def main() -> None:
    torch.manual_seed(7)
    model = TemporalStyleContextStudent(
        ReconstructionConfig(width=16, blocks=1, scale=4),
        TemporalConfig(hidden=16, downsample=8),
    ).eval()
    rgb = torch.rand(2, 3, 64, 64)
    guides = torch.rand(2, 5, 16, 16)
    context = torch.rand(2, 8, 24, 24)
    with torch.no_grad():
        base = model(rgb, guides, context)
        temporal, state = model.forward_temporal(rgb, guides, context, None)
    if not torch.equal(base, temporal):
        raise AssertionError("Zero-initialized temporal branch changed step-0 output")
    if state[0].shape != (2, 16, 8, 8):
        raise AssertionError(f"Unexpected hidden state shape: {state[0].shape}")
    if not torch.isfinite(temporal).all():
        raise AssertionError("Temporal smoke output is not finite")
    model.train()
    prediction, state = model.forward_temporal(rgb, guides, context, None)
    loss = prediction.square().mean()
    loss.backward()
    if not all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in model.parameters()
    ):
        raise AssertionError("Temporal smoke gradient is not finite")
    print("temporal student contract tests passed")


if __name__ == "__main__":
    main()

