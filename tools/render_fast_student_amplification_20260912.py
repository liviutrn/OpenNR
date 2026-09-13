"""Render luminance-residual strength variants for a FastStudent checkpoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from evaluate_fast_student_trt_full_eye import _load_frame, _resize, _save_png
from fast_student_v1 import load_fast_student
from render_fast_student_visuals_20260912 import (
    FACE_CROP,
    SELECTED_FRAMES,
    _native_composite,
    _panel,
    _to_pil,
)


def _composite(item: dict[str, torch.Tensor], prediction: torch.Tensor, multiplier: float) -> torch.Tensor:
    amplified = item["work_input"] + multiplier * (prediction - item["work_input"])
    full_residual = _resize(
        amplified - item["work_input"],
        item["full_input"].shape[-2],
        item["full_input"].shape[-1],
    )
    return (item["full_input"] + full_residual).clamp(0.0, 1.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--context-size", type=int, default=96)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()

    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this visual evaluation")
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError(f"refusing to use non-empty output directory: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)

    replay_root = args.replay_root.resolve()
    manifest = json.loads((replay_root / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"]).resolve()
    frame_ids = [int(value) for value in manifest["frames"]]
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    device = torch.device(args.device)
    model, saved = load_fast_student(args.checkpoint.resolve(), device)
    model.eval()
    multipliers = (1.0, 2.0, 3.0)
    records: list[dict[str, object]] = []

    with torch.inference_mode():
        for eye in (0, 1):
            state = None
            for frame_id in frame_ids:
                item = _load_frame(
                    replay_root,
                    sequence,
                    frame_id,
                    eye,
                    work_width,
                    work_height,
                    args.context_size,
                    args.context_size,
                    device,
                    torch.float32,
                )
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                if eye == 0 and frame_id in SELECTED_FRAMES:
                    input_cpu = item["full_input"].float().cpu()
                    teacher_cpu = item["full_teacher"].float().cpu()
                    native_cpu = _native_composite(item).float().cpu()
                    variants: list[tuple[str, torch.Tensor]] = []
                    for multiplier in multipliers:
                        variant = _composite(item, prediction, multiplier).float().cpu()
                        variants.append((f"Luma student {multiplier:g}x", variant))
                        _save_png(
                            args.output / "student_png" / f"frame_{frame_id:08d}_eye{eye}_luma_{multiplier:g}x.png",
                            variant,
                        )
                    labels = [("Raw input", input_cpu), *variants, ("Native 50% residual", native_cpu), ("Full native teacher", teacher_cpu)]
                    prefix = args.output / "previews" / f"frame_{frame_id:08d}_eye{eye}"
                    pil_labels = [(label, _to_pil(value)) for label, value in labels]
                    _panel(pil_labels, prefix.with_name(prefix.name + "_full_amplification.jpg"), None)
                    _panel(pil_labels, prefix.with_name(prefix.name + "_face_amplification.jpg"), FACE_CROP)
                del item, prediction
                if device.type == "cuda":
                    torch.cuda.empty_cache()
            state = None

    result = {
        "schema": "opennr-fast-student-luma-amplification-visual-evaluation-v1",
        "checkpoint": str(args.checkpoint.resolve()),
        "replay_root": str(replay_root),
        "sequence": str(sequence),
        "frames": frame_ids,
        "eye": 0,
        "selected_frames": list(SELECTED_FRAMES),
        "multipliers": list(multipliers),
        "face_crop_xyxy": list(FACE_CROP),
        "model_config": saved.get("config"),
        "parameters": sum(value.numel() for value in saved["model"].values()),
        "promotion": False,
        "live_runtime_tested": False,
        "scope": "offline style-strength visualization; multipliers scale the learned luma residual only and are not trained checkpoints",
    }
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
