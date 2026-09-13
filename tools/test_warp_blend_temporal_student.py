"""CPU contract checks for the direct warped-history blend."""

from __future__ import annotations

from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from student_v2 import ReconstructionConfig  # noqa: E402
from temporal_student import TemporalConfig, TemporalStyleContextStudent  # noqa: E402
from warp_temporal_student import (  # noqa: E402
    BlendConfig,
    MotionWarpBlendTemporalStyleContextStudent,
)


def main() -> None:
    torch.manual_seed(37)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    temporal = TemporalConfig(hidden=16, downsample=8, delta_scale=0.12)
    parent = TemporalStyleContextStudent(config, temporal).eval()
    child = MotionWarpBlendTemporalStyleContextStudent(
        config, temporal, BlendConfig(scale=0.25)
    ).eval()
    child.initialize_v9(parent.state_dict())
    rgb = torch.rand(2, 3, 64, 64)
    guides = torch.rand(2, 5, 16, 16)
    context = torch.rand(2, 8, 24, 24)
    with torch.no_grad():
        expected, _ = parent.forward_temporal(rgb, guides, context, None)
        actual, state = child.forward_temporal(rgb, guides, context, None)
    if not torch.equal(expected, actual):
        raise AssertionError("Blend gate changed the reset-frame parent output")
    next_rgb = torch.rand_like(rgb)
    with torch.no_grad():
        next_prediction, _ = child.forward_temporal(
            next_rgb, guides, context, state
        )
    if not torch.isfinite(next_prediction).all():
        raise AssertionError("Warped blend output is not finite")
    child.train()
    prediction, _ = child.forward_temporal(rgb, guides, context, None)
    prediction.square().mean().backward()
    if not all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in child.parameters()
    ):
        raise AssertionError("Non-finite warped blend gradients")
    print("motion-warp blend temporal student contract tests passed")


if __name__ == "__main__":
    main()
