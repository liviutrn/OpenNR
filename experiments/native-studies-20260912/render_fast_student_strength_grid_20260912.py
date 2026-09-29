"""Render post-composite strength variants of a reduced-native student on a face."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

TOOLS = Path(r"D:\.CODEX_Projects\OpenNR-VR\tools")
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from evaluate_fast_student_trt_full_eye import _load_frame, _metrics, _resize  # noqa: E402
from fast_student_v1 import load_fast_student  # noqa: E402


CHECKPOINT = Path(r"C:\OpenNR\OpenNR_FastStudent16_50NativeMultiSeq_20260912\best.pt")
REPLAY_ROOT = Path(r"C:\OpenNR\NativeReplays50_20260912\seq-1789064397821-5_f1-16")
OUTPUT = Path(r"C:\OpenNR\OpenNR_FastStudent16_50NativeMultiSeq_StrengthGrid_20260912")
FRAME_ID = 8
EYE = 0
STRENGTHS = (0.5, 1.0, 1.5, 2.0, 3.0)
FACE_CROP = (1480, 700, 1980, 1300)


def _to_image(value: torch.Tensor) -> Image.Image:
    array = (
        value.detach().float().clamp(0.0, 1.0)[0]
        .permute(1, 2, 0)
        .mul(255.0)
        .round()
        .byte()
        .cpu()
        .numpy()
    )
    return Image.fromarray(array, mode="RGB")


def _panel(
    images: list[tuple[str, Image.Image]],
    path: Path,
    crop: tuple[int, int, int, int] | None,
    cell_width: int = 560,
) -> None:
    caption_height = 38
    prepared: list[tuple[str, Image.Image]] = []
    for label, image in images:
        if crop is not None:
            image = image.crop(crop)
        ratio = cell_width / image.width
        prepared.append(
            (label, image.resize((cell_width, max(1, round(image.height * ratio))), Image.Resampling.LANCZOS))
        )
    cell_height = caption_height + max(image.height for _, image in prepared)
    result = Image.new("RGB", (cell_width * len(prepared), cell_height), (20, 20, 20))
    draw = ImageDraw.Draw(result)
    for index, (label, image) in enumerate(prepared):
        x = index * cell_width
        result.paste(image, (x, caption_height))
        draw.rectangle((x, 0, x + cell_width - 1, caption_height - 1), fill=(20, 20, 20))
        draw.text((x + 10, 11), label, fill=(245, 245, 245))
    path.parent.mkdir(parents=True, exist_ok=True)
    result.save(path, quality=94, subsampling=0)


def main() -> int:
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    manifest = json.loads((REPLAY_ROOT / "input_manifest.json").read_text(encoding="utf-8"))
    sequence = Path(manifest["sequence"]).resolve()
    work_width, work_height = (int(value) for value in manifest["network_dimensions"])
    device = torch.device("cuda")
    model, checkpoint = load_fast_student(CHECKPOINT, device)
    model.eval()

    outputs: dict[float, torch.Tensor] = {}
    record_values: dict[float, dict[str, float]] = {}
    with torch.inference_mode():
        for strength in STRENGTHS:
            state = None
            selected_item: dict[str, torch.Tensor] | None = None
            selected_prediction: torch.Tensor | None = None
            for frame_id in range(1, FRAME_ID + 1):
                item = _load_frame(
                    REPLAY_ROOT,
                    sequence,
                    frame_id,
                    EYE,
                    work_width,
                    work_height,
                    96,
                    96,
                    device,
                    torch.float32,
                )
                prediction, state = model.forward_temporal(
                    item["work_input"], item["guides"], item["context"], state
                )
                if frame_id == FRAME_ID:
                    selected_item = item
                    selected_prediction = prediction
                else:
                    del item, prediction
            assert selected_item is not None and selected_prediction is not None
            residual = _resize(
                (selected_prediction - selected_item["work_input"]) * strength,
                selected_item["full_input"].shape[-2],
                selected_item["full_input"].shape[-1],
            )
            value = (selected_item["full_input"] + residual).clamp(0.0, 1.0)
            outputs[strength] = value.detach().cpu()
            full_stats = _metrics(
                value.float().cpu(),
                selected_item["full_teacher"].float().cpu(),
                selected_item["full_input"].float().cpu(),
            )
            top, left, bottom, right = FACE_CROP[1], FACE_CROP[0], FACE_CROP[3], FACE_CROP[2]
            face_stats = _metrics(
                value[:, :, top:bottom, left:right].float().cpu(),
                selected_item["full_teacher"][:, :, top:bottom, left:right].float().cpu(),
                selected_item["full_input"][:, :, top:bottom, left:right].float().cpu(),
            )
            record_values[strength] = {
                "full_mae_vs_teacher": float(full_stats["mae"]),
                "full_identity_mae_vs_teacher": float(full_stats["identity_mae"]),
                "full_improvement_vs_identity": float(full_stats["identity_mae"] - full_stats["mae"]),
                "face_mae_vs_teacher": float(face_stats["mae"]),
                "face_identity_mae_vs_teacher": float(face_stats["identity_mae"]),
                "face_improvement_vs_identity": float(face_stats["identity_mae"] - face_stats["mae"]),
            }
            del selected_item, selected_prediction, value

    reference_item = _load_frame(
        REPLAY_ROOT,
        sequence,
        FRAME_ID,
        EYE,
        work_width,
        work_height,
        96,
        96,
        device,
        torch.float32,
    )
    full_input = reference_item["full_input"].float().cpu()
    full_teacher = reference_item["full_teacher"].float().cpu()
    native_residual = _resize(
        (reference_item["native_work"] - reference_item["work_input"]).float().cpu(),
        full_input.shape[-2],
        full_input.shape[-1],
    )
    native50 = (full_input + native_residual).clamp(0.0, 1.0)
    student_images = [("Raw input", _to_image(full_input))]
    student_images.extend((f"Student S={strength:.1f}x", _to_image(outputs[strength])) for strength in STRENGTHS)
    student_images.extend(
        [("Native 50% residual", _to_image(native50)), ("Full native teacher", _to_image(full_teacher))]
    )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _panel(student_images, OUTPUT / "frame_00000008_eye0_face_strength_grid.jpg", FACE_CROP, 500)
    _panel(student_images, OUTPUT / "frame_00000008_eye0_strength_references.jpg", None, 360)
    result = {
        "schema": "opennr-fast-student-post-strength-grid-v1",
        "checkpoint": str(CHECKPOINT.resolve()),
        "replay_root": str(REPLAY_ROOT.resolve()),
        "sequence": str(sequence),
        "frame_id": FRAME_ID,
        "eye": EYE,
        "face_crop_xyxy": list(FACE_CROP),
        "strengths": list(STRENGTHS),
        "records": [{"strength": strength, **record_values[strength]} for strength in STRENGTHS],
        "model_config": checkpoint.get("config"),
        "parameters": sum(value.numel() for value in checkpoint["model"].values()),
        "note": "Post-compositor student residual multiplier; it changes look only and adds no inference speed.",
        "promotion": False,
        "live_runtime_tested": False,
    }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
