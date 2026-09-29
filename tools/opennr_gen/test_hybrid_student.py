"""CPU smoke tests for the OpenNR-GEN hybrid static student."""

from __future__ import annotations

import torch

from hybrid_student import CAPACITIES, HybridStudent, parameter_count


def test_capacity_ranges_and_shape() -> None:
    expected = {"0.25m": (200_000, 300_000), "1m": (900_000, 1_150_000), "4m": (3_700_000, 4_400_000)}
    for name, (low, high) in expected.items():
        model = HybridStudent(name)
        count = parameter_count(model)
        assert low <= count <= high, (name, count)
        output = model(torch.rand(1, 3, 64, 64))
        assert output.shape == (1, 3, 64, 64)
        assert torch.isfinite(output).all()


def test_identity_safe_initialization() -> None:
    for name in CAPACITIES:
        model = HybridStudent(name)
        source = torch.rand(2, 3, 64, 64)
        with torch.no_grad():
            output = model(source)
        assert torch.equal(output, source)


if __name__ == "__main__":
    test_capacity_ranges_and_shape()
    test_identity_safe_initialization()
    print("OpenNR-GEN hybrid student tests passed")

