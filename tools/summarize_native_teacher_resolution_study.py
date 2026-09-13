"""Summarize the isolated native Feature 18 resolution study."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np


def stats(rows: list[dict[str, str]], key: str) -> dict[str, float | int]:
    values = np.asarray([float(row[key]) for row in rows], dtype=np.float64)
    return {
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95.0)),
        "min": float(values.min()),
        "max": float(values.max()),
        "count": int(values.size),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.study_root.expanduser().resolve()
    manifest = json.loads((root / "study_manifest.json").read_text(encoding="utf-8"))
    summary = {
        "study": manifest["study"],
        "source_sequence": manifest["source_sequence"],
        "source_frame": manifest["source_frame"],
        "dll_sha256": manifest["dll_sha256"],
        "driver_core_sha256": manifest["driver_core_sha256"],
        "scope": manifest["scope"],
        "scales": [],
    }
    baseline = None
    for item in manifest["scales"]:
        directory = root / f"scale{item['scale_percent']:03d}"
        with (directory / "timings.csv").open(newline="", encoding="utf-8") as handle:
            warm = [row for row in csv.DictReader(handle) if row["warm"] == "1"]
        record = {
            "scale_percent": item["scale_percent"],
            "network_dimensions": item["network_dimensions"],
            "guide_dimensions": item["guide_dimensions"],
            "area_fraction": (item["scale_percent"] / 100.0) ** 2,
            "gpu_pair_ms": stats(warm, "pair_gpu_ms"),
            "wall_pair_ms": stats(warm, "pair_wall_ms"),
            "successful_frames": int((directory / "runtime.txt").read_text(encoding="utf-8").splitlines()[1]),
        }
        if item["scale_percent"] == 100:
            baseline = record
        summary["scales"].append(record)
    if baseline is None:
        raise ValueError("study manifest does not contain the 100% baseline")
    for record in summary["scales"]:
        record["gpu_speedup_vs_100"] = baseline["gpu_pair_ms"]["median"] / record["gpu_pair_ms"]["median"]
        record["wall_speedup_vs_100"] = baseline["wall_pair_ms"]["median"] / record["wall_pair_ms"]["median"]
    output = root / "summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
