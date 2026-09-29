"""Contract and identity tests for the isolated FastStudent-v1 architecture."""

from __future__ import annotations

import math

import torch

from fast_student_v1 import FastStudentConfig, FastStudentV1, ScaleConditionedFastStudent


def main() -> None:
    torch.set_num_threads(2)
    torch.manual_seed(1200)
    config = FastStudentConfig(
        base_width=16,
        mid_width=32,
        temporal_hidden=16,
        blocks=1,
    )
    model = FastStudentV1(config).eval()
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    if parameter_count >= 5_000_000:
        raise AssertionError(f"smoke model is unexpectedly large: {parameter_count:,} parameters")

    batch, height, width = 2, 65, 67
    rgb = torch.rand(batch, 3, height, width)
    guides = torch.randn(batch, 5, 17, 19)
    context = torch.randn(batch, 8, 24, 25)
    with torch.no_grad():
        prediction, state = model.forward_temporal(rgb, guides, context, None)
        expected_hidden = (
            batch,
            config.temporal_hidden,
            math.ceil(height / config.temporal_downsample),
            math.ceil(width / config.temporal_downsample),
        )
        if tuple(prediction.shape) != tuple(rgb.shape):
            raise AssertionError(f"prediction shape mismatch: {prediction.shape}")
        if tuple(state[0].shape) != expected_hidden:
            raise AssertionError(f"hidden shape mismatch: {state[0].shape} != {expected_hidden}")
        if tuple(state[1].shape) != tuple(rgb.shape):
            raise AssertionError(f"previous shape mismatch: {state[1].shape}")
        if not torch.equal(prediction, rgb):
            raise AssertionError("fresh model must be an exact RGB identity")

        next_rgb = torch.rand_like(rgb)
        next_guides = torch.randn_like(guides)
        next_prediction, next_state = model.forward_temporal(
            next_rgb, next_guides, context, state
        )
        reset_prediction, reset_state = model.forward_temporal(
            rgb, guides, context, None
        )
        if not torch.equal(reset_prediction, rgb):
            raise AssertionError("reset frame is not an RGB identity")
        if not torch.equal(reset_state[1], reset_prediction):
            raise AssertionError("state previous output does not match prediction")
        if tuple(next_prediction.shape) != tuple(rgb.shape):
            raise AssertionError("recurrent prediction shape mismatch")
        if tuple(next_state[0].shape) != expected_hidden:
            raise AssertionError("recurrent hidden shape mismatch")
        if not torch.isfinite(next_prediction).all() or not torch.isfinite(next_state[0]).all():
            raise AssertionError("recurrent output contains non-finite values")

    train_model = FastStudentV1(config)
    train_rgb = rgb.clone().requires_grad_(True)
    train_prediction, train_state = train_model.forward_temporal(
        train_rgb, guides, context, None
    )
    loss = train_prediction.square().mean() + train_state[0].square().mean()
    loss.backward()
    gradients = [parameter.grad for parameter in train_model.parameters() if parameter.grad is not None]
    if not gradients or not all(torch.isfinite(gradient).all() for gradient in gradients):
        raise AssertionError("gradient contract failed")

    scaled = ScaleConditionedFastStudent(FastStudentV1(config), 0.5).eval()
    with torch.no_grad():
        scaled_prediction, scaled_state = scaled.forward_temporal(
            rgb, guides, context, None
        )
    if not torch.equal(scaled_prediction, rgb):
        raise AssertionError("fresh scale-conditioned model must be an exact RGB identity")
    expected_scaled_hidden = (
        batch,
        config.temporal_hidden,
        math.ceil(round(height * 0.5) / config.temporal_downsample),
        math.ceil(round(width * 0.5) / config.temporal_downsample),
    )
    if tuple(scaled_state[0].shape) != expected_scaled_hidden:
        raise AssertionError(
            f"scale-conditioned hidden mismatch: {scaled_state[0].shape} != {expected_scaled_hidden}"
        )

    print(
        {
            "status": "passed",
            "architecture": "fast_student_v1",
            "parameters": parameter_count,
            "input": [batch, 3, height, width],
            "hidden": list(expected_hidden),
            "identity": True,
            "finite_recurrent_step": True,
            "finite_gradients": True,
            "scale_conditioned_identity": True,
        }
    )


if __name__ == "__main__":
    main()
