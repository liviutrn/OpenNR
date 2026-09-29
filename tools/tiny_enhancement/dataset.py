"""Read-only access to an immutable OpenNR paired RGB cache.

The study cache is deliberately not copied or rewritten.  A generated study
manifest records the source cache hashes and absolute row indices; this module
re-checks those identities before opening the arrays.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
import torch


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


class TinyPairedCache:
    """A memory-mapped RGB pair cache with sequence-aware groups."""

    def __init__(self, manifest: str | Path, split: str):
        self.manifest_path = Path(manifest).resolve()
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != "opennr-tiny-enhancement-manifest-v1":
            raise ValueError("unsupported tiny-enhancement manifest schema")
        if split not in {"train", "validation", "test"}:
            raise ValueError(f"invalid split: {split}")
        self.split = split
        self.source = Path(self.manifest["source_cache"]).resolve()
        if not (self.source / "complete.json").exists():
            raise FileNotFoundError(self.source / "complete.json")
        expected_complete = self.manifest["source_complete_sha256"]
        actual_complete = sha256_file(self.source / "complete.json")
        if actual_complete != expected_complete:
            raise ValueError(
                f"source complete.json changed: {actual_complete} != {expected_complete}"
            )
        expected_rows = self.manifest["source_rows_file_sha256"]
        actual_rows = sha256_file(self.source / "rows.json")
        if actual_rows != expected_rows:
            raise ValueError(f"source rows.json changed: {actual_rows} != {expected_rows}")

        self.rows = json.loads((self.source / "rows.json").read_text(encoding="utf-8"))
        self.rgb = np.load(self.source / "rgb.npy", mmap_mode="r")
        expected_shape = tuple(self.manifest["rgb_shape"])
        if tuple(self.rgb.shape) != expected_shape or str(self.rgb.dtype) != self.manifest["rgb_dtype"]:
            raise ValueError(
                f"RGB array contract changed: shape={self.rgb.shape}, dtype={self.rgb.dtype}"
            )
        self.indices = np.asarray(self.manifest["row_indices"][split], dtype=np.int64)
        if len(self.indices) != self.manifest["split_counts"][split]:
            raise ValueError("manifest split count does not match row indices")
        if len(self.indices) and (self.indices.min() < 0 or self.indices.max() >= len(self.rows)):
            raise ValueError("manifest has an out-of-range source row index")
        if any(self.rows[int(i)].get("split") != split for i in self.indices[: min(256, len(self.indices))]):
            raise ValueError("source row split disagrees with study manifest")

        self.groups = self._make_groups()

    def _make_groups(self) -> list[dict]:
        grouped: dict[tuple[str, int], list[int]] = defaultdict(list)
        for absolute_index in self.indices.tolist():
            row = self.rows[absolute_index]
            grouped[(str(row["sequence_id"]), int(row["eye"]))].append(absolute_index)
        result = []
        for (sequence_id, eye), absolute_indices in grouped.items():
            absolute_indices.sort(key=lambda i: int(self.rows[i]["frame_id"]))
            sources = {self.rows[i].get("cache_source") for i in absolute_indices}
            if len(sources) != 1:
                raise ValueError(f"sequence crosses cache sources: {sequence_id}")
            result.append(
                {
                    "sequence_id": sequence_id,
                    "eye": eye,
                    "cache_source": next(iter(sources)),
                    "indices": absolute_indices,
                    "frame_ids": [int(self.rows[i]["frame_id"]) for i in absolute_indices],
                }
            )
        result.sort(key=lambda group: (group["cache_source"], group["sequence_id"], group["eye"]))
        return result

    def __len__(self) -> int:
        return len(self.indices)

    def load_batch(
        self, absolute_indices: Iterable[int], device: torch.device | str | None = None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Load input/teacher rows, optionally moving them to a device.

        The returned tensors are float32 in [0, 1].  Only the requested rows
        are copied from the memory-mapped source array.
        """

        ids = np.asarray(list(absolute_indices), dtype=np.int64)
        if ids.ndim != 1 or not len(ids):
            raise ValueError("load_batch requires at least one row")
        pair = np.asarray(self.rgb[ids], dtype=np.float32) / 255.0
        pair = np.ascontiguousarray(pair)
        inputs = torch.from_numpy(pair[:, 0])
        teachers = torch.from_numpy(pair[:, 1])
        if device is not None:
            inputs = inputs.to(device, non_blocking=True)
            teachers = teachers.to(device, non_blocking=True)
        return inputs, teachers

    def sample_indices(self, rng: np.random.Generator, batch_size: int) -> np.ndarray:
        if self.split != "train":
            raise ValueError("sampling is only permitted for the train split")
        positions = rng.integers(0, len(self.indices), size=batch_size)
        return self.indices[positions]

    def cohort_counts(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for absolute_index in self.indices.tolist():
            counts[str(self.rows[absolute_index].get("cache_source", "unknown"))] += 1
        return dict(sorted(counts.items()))

