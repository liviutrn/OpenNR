"""Audit same-current-frame/different-history state-response pairs.

This is a read-only gate over an already prepared aligned cache. It never
repairs captures, invents a state tensor, or reads frozen-test targets by
default. A passing report means that a bounded state-response distillation
experiment is technically prepared; it is not a model-quality result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def _ref_key(value: Any) -> tuple[str, int, int]:
    if not isinstance(value, dict):
        raise ValueError("row reference must be an object")
    return str(value["sequence_id"]), int(value["frame_id"]), int(value["eye"])


def _same_metadata(reset: dict[str, Any], warm: dict[str, Any]) -> list[str]:
    errors = []
    for field in (
        "eye",
        "crop_index",
        "route",
        "model_resolution_percent",
        "pass_count",
        "motion_vector_contract",
        "source_color_size",
        "source_guide_size",
        "motion_scale",
        "teacher_settings",
    ):
        if reset.get(field) != warm.get(field):
            errors.append(f"metadata mismatch: {field}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-pairs", type=int, default=8)
    parser.add_argument("--minimum-state-response-mae", type=float, default=1e-4)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)

    cache = args.cache.resolve()
    pairs_path = args.pairs.resolve()
    complete_path = cache / "complete.json"
    rows_path = cache / "rows.json"
    required = [complete_path, rows_path] + [cache / f"{name}.npy" for name in ("rgb", "guides", "context", "conditioning")]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing cache files: " + ", ".join(missing))

    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    pairs_doc = json.loads(pairs_path.read_text(encoding="utf-8"))
    if pairs_doc.get("schema") != "opennr-renderer-state-pairs-v1":
        raise ValueError("Unexpected state-pair manifest schema")
    if complete.get("schema") != "opennr-aligned-renderer-pilot-v1":
        raise ValueError("Cache is not an aligned renderer-conditioned cache")
    if int(complete.get("conditioning_channels", 0)) != 17:
        raise ValueError("Cache does not contain the required 17 renderer channels")
    if not isinstance(pairs_doc.get("pairs"), list):
        raise ValueError("State-pair manifest pairs must be an array")
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    index = {_ref_key(row): (position, row) for position, row in enumerate(rows)}
    arrays = {
        name: np.load(cache / f"{name}.npy", mmap_mode="r")
        for name in ("rgb", "guides", "context", "conditioning")
    }

    report: dict[str, Any] = {
        "schema": "opennr-renderer-state-pair-audit-v1",
        "cache": str(cache),
        "cache_complete_sha256": sha(complete_path),
        "pairs": str(pairs_path),
        "pairs_sha256": sha(pairs_path),
        "test_used": False,
        "minimum_pairs": args.minimum_pairs,
        "minimum_state_response_mae": args.minimum_state_response_mae,
        "pair_reports": [],
        "errors": [],
    }

    for ordinal, pair in enumerate(pairs_doc.get("pairs", []), 1):
        pair_report: dict[str, Any] = {
            "ordinal": ordinal,
            "pair_id": pair.get("pair_id"),
            "ready": False,
            "errors": [],
        }
        try:
            reset_key = _ref_key(pair["reset"])
            warm_key = _ref_key(pair["warm"])
            reset_position, reset = index[reset_key]
            warm_position, warm = index[warm_key]
        except (KeyError, TypeError, ValueError) as exc:
            pair_report["errors"].append(f"invalid or missing row reference: {exc}")
            report["pair_reports"].append(pair_report)
            continue

        if reset.get("split") != warm.get("split"):
            pair_report["errors"].append("pair members cross a split boundary")
        if reset_key == warm_key:
            pair_report["errors"].append("reset and warm references are identical")
        if reset.get("split") == "test":
            pair_report["errors"].append("frozen-test pair is not read by this audit")
            pair_report["split"] = "test"
            report["pair_reports"].append(pair_report)
            continue
        if reset.get("history_reset_pair") != [True, True]:
            pair_report["errors"].append("reset member is not [true, true]")
        if warm.get("history_reset_pair") != [False, False]:
            pair_report["errors"].append("warm member is not [false, false]")
        pair_report["errors"].extend(_same_metadata(reset, warm))

        for name in arrays:
            if arrays[name].shape[0] != len(rows):
                pair_report["errors"].append(f"{name}.npy row count does not match rows.json")

        current_equal = {}
        for name in ("rgb", "guides", "context", "conditioning"):
            if name == "rgb":
                reset_value = arrays[name][reset_position, 0]
                warm_value = arrays[name][warm_position, 0]
            else:
                reset_value = arrays[name][reset_position]
                warm_value = arrays[name][warm_position]
            current_equal[name] = bool(np.array_equal(reset_value, warm_value))
            if not current_equal[name]:
                pair_report["errors"].append(f"current {name} is not byte-identical")

        reset_target = arrays["rgb"][reset_position, 1].astype(np.float32) / 255.0
        warm_target = arrays["rgb"][warm_position, 1].astype(np.float32) / 255.0
        state_response_mae = float(np.abs(reset_target - warm_target).mean())
        pair_report.update(
            {
                "split": reset.get("split"),
                "reset": reset_key,
                "warm": warm_key,
                "current_inputs_byte_identical": current_equal,
                "state_response_mae": state_response_mae,
            }
        )
        if state_response_mae < args.minimum_state_response_mae:
            pair_report["errors"].append("teacher history response is below the minimum signal gate")
        pair_report["ready"] = not pair_report["errors"]
        report["pair_reports"].append(pair_report)

    ready_pairs = [item for item in report["pair_reports"] if item["ready"]]
    report["ready_pair_count"] = len(ready_pairs)
    report["ready"] = len(ready_pairs) >= args.minimum_pairs and not report["errors"]
    if len(ready_pairs) < args.minimum_pairs:
        report["errors"].append(
            f"only {len(ready_pairs)} ready pairs; minimum is {args.minimum_pairs}"
        )
    if any(item["errors"] for item in report["pair_reports"]):
        report["errors"].append("one or more state pairs failed the clean-current-frame gate")

    save(args.output / "result.json", report)
    save(args.output / "status.json", {"state": "complete", "ready": report["ready"], "test_used": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
