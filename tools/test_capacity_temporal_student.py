"""CPU contract checks for the capacity-temporal student."""

from __future__ import annotations

import torch

from capacity_student import CapacityConfig
from capacity_temporal_student import CapacityTemporalStyleContextStudent
from student_v2 import ReconstructionConfig
from temporal_student import TemporalConfig
from train_capacity_temporal_student import effect_high_frequency_loss, effect_power_loss


def main() -> None:
    torch.manual_seed(19)
    config = ReconstructionConfig(width=16, blocks=1, scale=4)
    temporal = TemporalConfig(hidden=16, downsample=8, delta_scale=0.12)
    capacity = CapacityConfig(width=32, blocks=1, delta_scale=0.12)
    parent = CapacityTemporalStyleContextStudent(config, temporal, capacity)
    child = CapacityTemporalStyleContextStudent(config, temporal, capacity)
    child.initialize_v5(parent.state_dict())
    # Loading a complete state is exact; separately test zero-initialized
    # capacity output by comparing against a temporal-only parent.
    from temporal_student import TemporalStyleContextStudent

    temporal_parent = TemporalStyleContextStudent(config, temporal)
    child = CapacityTemporalStyleContextStudent(config, temporal, capacity)
    child.initialize_v5(temporal_parent.state_dict())
    rgb = torch.rand(1, 3, 64, 64)
    guides = torch.rand(1, 5, 16, 16)
    context = torch.rand(1, 8, 12, 12)
    with torch.no_grad():
        expected, expected_state = temporal_parent.forward_temporal(
            rgb, guides, context, None
        )
        actual, actual_state = child.forward_temporal(rgb, guides, context, None)
    if not torch.equal(expected, actual):
        raise AssertionError("Capacity branch changed the temporal parent at step zero")
    if actual_state[0].shape != (1, temporal.hidden, 8, 8):
        raise AssertionError(f"Unexpected hidden state shape: {actual_state[0].shape}")
    actual_with_grad, _ = child.forward_temporal(rgb, guides, context, None)
    loss = actual_with_grad.square().mean()
    loss.backward()
    if not all(torch.isfinite(parameter.grad).all() for parameter in child.parameters() if parameter.grad is not None):
        raise AssertionError("Non-finite capacity-temporal gradients")
    # The optional second branch must also preserve the inherited function at
    # initialization when it is introduced as a continuation experiment.
    expanded = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(width=32, blocks=1, delta_scale=0.12, extra_width=32, extra_blocks=1),
    )
    expanded.initialize_v5(temporal_parent.state_dict())
    with torch.no_grad():
        expanded_prediction, _ = expanded.forward_temporal(rgb, guides, context, None)
    if not torch.equal(expected, expanded_prediction):
        raise AssertionError("Extra capacity branch changed the temporal parent at step zero")
    effect = torch.rand(1, 3, 32, 32)
    target = torch.rand(1, 3, 32, 32)
    rgb = torch.rand(1, 3, 32, 32)
    zero = effect_high_frequency_loss(effect, effect, rgb)
    if zero.item() != 0.0:
        raise AssertionError("High-frequency effect loss is not zero for an exact target")
    differentiable = effect.clone().requires_grad_(True)
    high_frequency = effect_high_frequency_loss(differentiable, target, rgb)
    high_frequency.backward()
    if differentiable.grad is None or not torch.isfinite(differentiable.grad).all():
        raise AssertionError("High-frequency effect loss did not produce finite gradients")
    mapped_zero = effect_power_loss(effect, effect, rgb)
    if mapped_zero.item() != 0.0:
        raise AssertionError("Power-mapped effect loss is not zero for an exact target")
    mapped_input = effect.clone().requires_grad_(True)
    mapped = effect_power_loss(mapped_input, target, rgb, power=3.0)
    mapped.backward()
    if mapped_input.grad is None or not torch.isfinite(mapped_input.grad).all():
        raise AssertionError("Power-mapped effect loss did not produce finite gradients")
    # Context-FiLM must be an exact parent-preserving opt-in at initialization.
    styled = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(width=32, blocks=1, delta_scale=0.12, style_modulation=True),
    )
    styled.initialize_v5(temporal_parent.state_dict())
    style_rgb = torch.rand(1, 3, 64, 64)
    style_guides = torch.rand(1, 5, 16, 16)
    style_context = torch.rand(1, 8, 12, 12)
    with torch.no_grad():
        expected_style, _ = temporal_parent.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
        styled_prediction, _ = styled.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(expected_style, styled_prediction):
        raise AssertionError("Style modulation changed the temporal parent at step zero")
    # A learned residual gate must also be an exact parent-preserving opt-in.
    gated = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=32,
            blocks=1,
            delta_scale=0.12,
            extra_width=32,
            extra_blocks=1,
            residual_gate=True,
        ),
    )
    gated.initialize_v5(temporal_parent.state_dict())
    with torch.no_grad():
        gated_prediction, _ = gated.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(expected_style, gated_prediction):
        raise AssertionError("Residual gate changed the temporal parent at step zero")
    final_gated = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=32,
            blocks=1,
            delta_scale=0.12,
            extra_width=32,
            extra_blocks=1,
            residual_gate=True,
            final_gate=True,
        ),
    )
    final_gated.initialize_v5(temporal_parent.state_dict())
    with torch.no_grad():
        final_prediction, _ = final_gated.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(expected_style, final_prediction):
        raise AssertionError("Final correction gate changed the temporal parent at step zero")
    # A wider capacity continuation may skip only capacity tensors and must
    # still preserve the inherited base/temporal function at initialization.
    wider = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=48,
            blocks=2,
            delta_scale=0.12,
            extra_width=48,
            extra_blocks=2,
            residual_gate=True,
            final_gate=True,
        ),
    )
    wider.initialize_v5(temporal_parent.state_dict())
    with torch.no_grad():
        wider_prediction, _ = wider.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(expected_style, wider_prediction):
        raise AssertionError("Wider capacity continuation changed the parent at step zero")
    # A same-width depth expansion can preserve the complete learned parent
    # when newly appended block residual scales are explicitly zeroed.
    depth_parent = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=32,
            blocks=1,
            delta_scale=0.12,
            extra_width=32,
            extra_blocks=1,
            residual_gate=True,
            final_gate=True,
        ),
    )
    depth_child = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=32,
            blocks=2,
            delta_scale=0.12,
            extra_width=32,
            extra_blocks=2,
            residual_gate=True,
            final_gate=True,
        ),
    )
    depth_child.initialize_v5(depth_parent.state_dict(), zero_init_missing_blocks=True)
    with torch.no_grad():
        depth_expected, _ = depth_parent.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
        depth_actual, _ = depth_child.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(depth_expected, depth_actual):
        raise AssertionError("Depth expansion changed the parent at step zero")
    expected_zeroed = {
        "capacity_blocks.1.gamma",
        "capacity_extra_blocks.1.gamma",
    }
    if set(depth_child.zero_initialized_missing_capacity_gammas) != expected_zeroed:
        raise AssertionError("Depth expansion did not record the new zero-gamma blocks")
    # The fair width-experiment initializer must preserve only the inherited
    # base/temporal function, leaving every capacity width at fresh seeded
    # constructor state for a common starting function.
    fresh = CapacityTemporalStyleContextStudent(
        config,
        temporal,
        CapacityConfig(
            width=48,
            blocks=2,
            delta_scale=0.12,
            extra_width=48,
            extra_blocks=2,
            residual_gate=True,
            final_gate=True,
        ),
    )
    fresh.initialize_base_temporal(temporal_parent.state_dict())
    with torch.no_grad():
        fresh_prediction, _ = fresh.forward_temporal(
            style_rgb, style_guides, style_context, None
        )
    if not torch.equal(expected_style, fresh_prediction):
        raise AssertionError("Fresh capacity initialization changed the parent at step zero")
    print("capacity-temporal student contract tests passed")


if __name__ == "__main__":
    main()
