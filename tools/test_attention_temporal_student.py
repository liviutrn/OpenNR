"""CPU contract checks for local-window attention refinement."""

from __future__ import annotations

from pathlib import Path
import sys

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from attention_temporal_student import (  # noqa: E402
    AttentionConfig,
    AttentionTemporalStyleContextStudent,
)
from student_v2 import ReconstructionConfig  # noqa: E402
from temporal_student import TemporalConfig, TemporalStyleContextStudent  # noqa: E402


def main() -> None:
    torch.manual_seed(41)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    temporal = TemporalConfig(hidden=16, downsample=8, delta_scale=0.12)
    attention = AttentionConfig(width=16, blocks=1, heads=4, window=4)
    shifted_attention = AttentionConfig(
        width=16, blocks=2, heads=4, window=4, shifted=True
    )
    multi_scale_attention = AttentionConfig(
        width=16, blocks=2, heads=4, window=4, shifted=True, multi_scale=True
    )
    parent = TemporalStyleContextStudent(config, temporal).eval()
    child = AttentionTemporalStyleContextStudent(config, temporal, attention).eval()
    shifted_child = AttentionTemporalStyleContextStudent(
        config, temporal, shifted_attention
    ).eval()
    multi_scale_child = AttentionTemporalStyleContextStudent(
        config, temporal, multi_scale_attention
    ).eval()
    child.initialize_v5(parent.state_dict())
    shifted_child.initialize_v5(parent.state_dict())
    multi_scale_child.initialize_v5(parent.state_dict())
    rgb = torch.rand(2, 3, 64, 64)
    guides = torch.rand(2, 5, 16, 16)
    context = torch.rand(2, 8, 24, 24)
    with torch.no_grad():
        expected, _ = parent.forward_temporal(rgb, guides, context, None)
        actual, state = child.forward_temporal(rgb, guides, context, None)
        shifted_actual, shifted_state = shifted_child.forward_temporal(
            rgb, guides, context, None
        )
        multi_scale_actual, multi_scale_state = multi_scale_child.forward_temporal(
            rgb, guides, context, None
        )
    if not torch.equal(expected, actual):
        raise AssertionError("Attention branch changed the zero-head parent output")
    if not torch.equal(expected, shifted_actual):
        raise AssertionError("Shifted attention changed the zero-head parent output")
    if not torch.equal(expected, multi_scale_actual):
        raise AssertionError("Multi-scale attention changed the zero-head parent output")
    with torch.no_grad():
        next_prediction, _ = child.forward_temporal(rgb, guides, context, state)
        shifted_next, _ = shifted_child.forward_temporal(
            rgb, guides, context, shifted_state
        )
        multi_scale_next, _ = multi_scale_child.forward_temporal(
            rgb, guides, context, multi_scale_state
        )
    if not torch.isfinite(next_prediction).all():
        raise AssertionError("Attention output is not finite")
    if not torch.isfinite(shifted_next).all():
        raise AssertionError("Shifted attention output is not finite")
    if not torch.isfinite(multi_scale_next).all():
        raise AssertionError("Multi-scale attention output is not finite")
    child.train()
    prediction, _ = child.forward_temporal(rgb, guides, context, None)
    prediction.square().mean().backward()
    if not all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in child.parameters()
    ):
        raise AssertionError("Non-finite attention gradients")
    print("attention-temporal student contract tests passed")


if __name__ == "__main__":
    main()
