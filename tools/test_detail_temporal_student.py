"""CPU contract checks for the half-resolution detail-temporal student."""

from __future__ import annotations

from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from detail_temporal_student import (  # noqa: E402
    DetailConfig,
    DetailTemporalStyleContextStudent,
)
from student_v2 import ReconstructionConfig  # noqa: E402
from temporal_student import TemporalConfig, TemporalStyleContextStudent  # noqa: E402


def main() -> None:
    torch.manual_seed(29)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    temporal = TemporalConfig(hidden=16, downsample=8, delta_scale=0.12)
    detail = DetailConfig(width=16, blocks=1, downsample=2, delta_scale=0.12)
    parent = TemporalStyleContextStudent(config, temporal).eval()
    child = DetailTemporalStyleContextStudent(config, temporal, detail).eval()
    child.initialize_v5(parent.state_dict())
    rgb = torch.rand(2, 3, 64, 64)
    guides = torch.rand(2, 5, 16, 16)
    context = torch.rand(2, 8, 24, 24)
    with torch.no_grad():
        expected, expected_state = parent.forward_temporal(
            rgb, guides, context, None
        )
        actual, actual_state = child.forward_temporal(
            rgb, guides, context, None
        )
    if not torch.equal(expected, actual):
        raise AssertionError("Detail branch changed the temporal parent at step zero")
    if actual_state[0].shape != (2, 16, 8, 8):
        raise AssertionError(f"Unexpected hidden state shape: {actual_state[0].shape}")
    if not torch.equal(expected_state[1], actual_state[1]):
        raise AssertionError("Step-zero recurrent prediction differs from parent")
    child.train()
    prediction, _ = child.forward_temporal(rgb, guides, context, None)
    loss = prediction.square().mean()
    loss.backward()
    if not all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in child.parameters()
    ):
        raise AssertionError("Non-finite detail-temporal gradients")
    print("detail-temporal student contract tests passed")


if __name__ == "__main__":
    main()
