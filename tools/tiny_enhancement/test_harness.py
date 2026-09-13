"""Fast architectural and identity tests for the tiny enhancement adapters."""

from __future__ import annotations

import json

import torch

from .models import build_model, identity_error, parameter_count


def main() -> None:
    torch.manual_seed(812)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    results = []
    sample = torch.rand(2, 3, 64, 64, device=device)
    for name in ("adaptive_3dlut", "svdlut", "zero_dce_supervised", "srvgg_same_res"):
        model = build_model(name).to(device).eval()
        with torch.inference_mode():
            output = model(sample)
        if output.shape != sample.shape or not torch.isfinite(output).all():
            raise AssertionError(f"invalid output for {name}: {output.shape}")
        error = float((output - sample).abs().mean().item())
        if error >= 0.005:
            raise AssertionError(f"identity initialization too far from input for {name}: {error}")
        results.append({"model": name, "parameters": parameter_count(model), "identity_mae": error})
    print(json.dumps({"device": str(device), "models": results, "passed": True}, indent=2))


if __name__ == "__main__":
    main()

