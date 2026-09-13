"""Verify whether the trained detail head beats its native-50% base."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch


OPENNR = Path(r"C:\OpenNR")
TOOLS = Path(r"D:\.CODEX_Projects\OpenNR-VR\tools")
for path in (OPENNR, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from train_native50_detail_head_20260912 import (  # noqa: E402
    DetailHead,
    _item,
    _manifest,
    _metrics,
    _panel,
    _to_image,
)


OUTPUT = Path(r"C:\OpenNR\Native50DetailHeadPilot_20260912")
CHECKPOINT = OUTPUT / "best.pt"
TEST_ROOT = Path(r"C:\OpenNR\NativeReplays50_20260912\seq-1789064397821-5_f1-16")
VALID_ROOT = Path(r"C:\OpenNR\NativeReplays50_20260912\seq-1789064544626-6_f1-16")


def mean_metric(records: list[dict[str, float]]) -> dict[str, float | int]:
    if not records:
        raise ValueError("empty record set")
    keys = ("mae", "identity_mae", "improvement", "rmse")
    result: dict[str, float | int] = {
        key: float(np.mean([record[key] for record in records])) for key in keys
    }
    result["sample_count"] = len(records)
    result["better_than_raw_samples"] = int(sum(record["improvement"] > 0 for record in records))
    result["enhanced_minus_base_mae"] = float(
        np.mean([record["enhanced_mae"] - record["base_mae"] for record in records])
    )
    result["enhanced_better_than_base_samples"] = int(
        sum(record["enhanced_mae"] < record["base_mae"] for record in records)
    )
    return result


def evaluate(
    model: DetailHead,
    manifest: dict,
    frame_ids: list[int],
    device: torch.device,
    *,
    save_frame: int | None = None,
) -> tuple[dict[str, float | int], list[dict[str, float]]]:
    records: list[dict[str, float]] = []
    for frame_id in frame_ids:
        for eye in (0, 1):
            full_input, full_teacher, base = _item(manifest, frame_id, eye)
            raw = full_input.to(device)
            teacher = full_teacher.to(device)
            base_gpu = base.to(device)
            with torch.inference_mode():
                correction = model(raw, base_gpu)
                enhanced = (base_gpu + correction).clamp(0.0, 1.0)
            base_stats = _metrics(base_gpu, teacher, raw)
            enhanced_stats = _metrics(enhanced, teacher, raw)
            record = {
                "frame_id": frame_id,
                "eye": eye,
                "base_mae": base_stats["mae"],
                "enhanced_mae": enhanced_stats["mae"],
                "mae": enhanced_stats["mae"],
                "identity_mae": enhanced_stats["identity_mae"],
                "improvement": enhanced_stats["improvement"],
                "rmse": enhanced_stats["rmse"],
                "base_improvement_vs_raw": base_stats["improvement"],
                "enhanced_improvement_vs_base": base_stats["mae"] - enhanced_stats["mae"],
            }
            records.append(record)
            if save_frame == frame_id and eye == 0:
                images = [
                    ("Raw input", _to_image(raw)),
                    ("Native 50% residual base", _to_image(base_gpu)),
                    ("Base + detail head", _to_image(enhanced)),
                    ("Full native teacher", _to_image(teacher)),
                ]
                _panel(images, OUTPUT / "verified_fullframe_comparison.jpg")
                _panel(
                    images,
                    OUTPUT / "verified_detail_crop_comparison.jpg",
                    (700, 500, 1800, 1600),
                )
            del raw, teacher, base_gpu, enhanced
            if device.type == "cuda":
                torch.cuda.empty_cache()
    return mean_metric(records), records


def main() -> None:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable")
    device = torch.device("cuda")
    checkpoint = torch.load(CHECKPOINT, map_location=device, weights_only=True)
    model = DetailHead(channels=int(checkpoint.get("channels", 24))).to(device).eval()
    model.load_state_dict(checkpoint["model"])
    test_manifest = _manifest(TEST_ROOT)
    valid_manifest = _manifest(VALID_ROOT)
    with torch.inference_mode():
        valid_summary, valid_records = evaluate(
            model, valid_manifest, list(range(13, 17)), device
        )
        test_summary, test_records = evaluate(
            model, test_manifest, test_manifest["frames"], device, save_frame=8
        )
    result = {
        "schema": "opennr-native50-detail-head-baseline-verification-v1",
        "checkpoint": str(CHECKPOINT.resolve()),
        "parameters": sum(parameter.numel() for parameter in model.parameters()),
        "validation": {"summary": valid_summary, "records": valid_records},
        "test": {"summary": test_summary, "records": test_records},
        "promotion": False,
        "live_runtime_tested": False,
        "scope": (
            "Full-frame offline comparison of raw input, actual native-50% "
            "residual base, and base plus the trained 2,619-parameter detail "
            "head. The base is the correct comparator; raw-only improvement is "
            "not sufficient."
        ),
    }
    path = OUTPUT / "verified_baseline_comparison.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(path)


if __name__ == "__main__":
    main()
