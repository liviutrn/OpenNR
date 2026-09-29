"""CPU contract checks for motion-compensated temporal history."""

from __future__ import annotations

from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from student_v2 import ReconstructionConfig  # noqa: E402
from temporal_student import TemporalConfig, TemporalStyleContextStudent  # noqa: E402
from warp_temporal_student import MotionWarpTemporalStyleContextStudent  # noqa: E402


def main() -> None:
    torch.manual_seed(31)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    temporal = TemporalConfig(hidden=16, downsample=8, delta_scale=0.12)
    parent = TemporalStyleContextStudent(config, temporal).eval()
    child = MotionWarpTemporalStyleContextStudent(config, temporal).eval()
    child.initialize_v9(parent.state_dict())
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
        raise AssertionError("Motion warp changed the zero-head parent output")
    if actual_state[0].shape != (2, 16, 8, 8):
        raise AssertionError(f"Unexpected hidden state shape: {actual_state[0].shape}")
    if not torch.isfinite(actual).all():
        raise AssertionError("Motion-warp output is not finite")
    child.train()
    prediction, _ = child.forward_temporal(rgb, guides, context, None)
    prediction.square().mean().backward()
    if not all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in child.parameters()
    ):
        raise AssertionError("Non-finite motion-warp gradients")
    print("motion-warp temporal student contract tests passed")


if __name__ == "__main__":
    main()
