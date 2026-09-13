"""Focused tests for the raw-only crop cache bridge."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

import numpy as np

from build_raw_crop_cache import (
    _convert_motion_to_color_pixels,
    _raw_memmap,
    _split_sequence_ids,
)


def test_padded_raw_rows() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "padded.bin"
        rows = [bytes((1, 2, 3, 4, 5, 6)) + b"xx", bytes((7, 8, 9, 10, 11, 12)) + b"yy"]
        path.write_bytes(b"".join(rows))
        values = _raw_memmap(path, width=3, height=2, channels=2, dtype="u1", row_pitch=8)
        assert values.shape == (2, 3, 2)
        assert values.tolist() == [[[1, 2], [3, 4], [5, 6]], [[7, 8], [9, 10], [11, 12]]]


def test_motion_uses_full_source_dimensions() -> None:
    row = {
        "source_color_size": [2496, 2688],
        "source_guide_size": [1664, 1792],
        "motion_scale": [1664.0, 1792.0],
    }
    native = np.array([[[0.05, -0.05]]], dtype=np.float32)
    converted = _convert_motion_to_color_pixels(native, row)
    # 0.05 guide pixels * 2496/128 and 0.05 * 2688/128.
    assert np.allclose(converted[0, 0], [0.97499996, -1.0], atol=1e-6)


def test_sequence_split_is_deterministic() -> None:
    entries = [
        {"sequence_id": f"seq-{index}", "created_utc": index, "expected_frames": 2, "expected_complete": 2, "expected_artifacts": 16}
        for index in range(10)
    ]
    split = _split_sequence_ids(entries)
    assert split["train"] == [f"seq-{index}" for index in range(6)]
    assert split["validation"] == ["seq-6", "seq-7"]
    assert split["test"] == ["seq-8", "seq-9"]


def test_cached_patches(cache_root: Path) -> None:
    import torch
    from torch.utils.data import DataLoader

    from train_student import CachedPatches, batch_to_device

    complete = json.loads(
        (Path(cache_root) / "complete.json").read_text(encoding="utf-8")
    )
    spatial_only = complete.get("training_role") == "spatial_only_auxiliary"
    for split in ("train", "validation", "test"):
        dataset = CachedPatches(cache_root, split)
        if spatial_only and len(dataset) == 0:
            # Auxiliary caches intentionally have no selection split.  They
            # are consumed only as a training regularizer by SpatialCache;
            # strict validation and frozen testing remain elsewhere.
            continue
        assert len(dataset) > 0, split
        sample = dataset[0]
        assert tuple(sample["rgb"].shape) == (3, 512, 512)
        assert tuple(sample["target"].shape) == (3, 512, 512)
        assert tuple(sample["guides"].shape) == (5, 128, 128)
        assert tuple(sample["context"].shape) == (8, 96, 96)
        assert torch.isfinite(sample["rgb"]).all()
        assert torch.isfinite(sample["guides"]).all()
        assert torch.isfinite(sample["context"]).all()
        batch = next(iter(DataLoader(dataset, batch_size=2, shuffle=False)))
        rgb, target, guides, context = batch_to_device(batch, "cpu")
        assert tuple(rgb.shape) == (2, 3, 512, 512)
        assert tuple(target.shape) == (2, 3, 512, 512)
        assert tuple(guides.shape) == (2, 5, 128, 128)
        assert tuple(context.shape) == (2, 8, 96, 96)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, help="also validate CachedPatches against a built cache")
    args = parser.parse_args()
    test_padded_raw_rows()
    test_motion_uses_full_source_dimensions()
    test_sequence_split_is_deterministic()
    if args.cache:
        test_cached_patches(args.cache)
    print("PASS: raw crop cache helpers")


if __name__ == "__main__":
    main()
