"""Small remote smoke check for staged OpenNR cache contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from train_temporal_student import MultiSpatialCache, StrictTemporalCache


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, required=True)
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--spatial", type=Path, required=True)
    args = parser.parse_args()

    old = StrictTemporalCache(args.old, "validation")
    new = StrictTemporalCache(args.new, "validation")
    spatial = MultiSpatialCache([args.spatial])
    _, old_arrays = next(old.stream_batches(1))
    spatial_arrays = spatial.sample(np.random.default_rng(337), 1)
    result = {
        "old_validation_streams": len(old.streams),
        "new_validation_streams": len(new.streams),
        "spatial_training_patches": int(spatial.ids[0]),
        "old_rgb_shape": list(old_arrays[0].shape),
        "old_guides_shape": list(old_arrays[2].shape),
        "spatial_rgb_shape": list(spatial_arrays[0].shape),
        "spatial_guides_shape": list(spatial_arrays[2].shape),
        "old_rows_sha256": old.rows_sha256,
        "new_rows_sha256": new.rows_sha256,
        "spatial_rows_sha256": spatial.rows_sha256,
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
