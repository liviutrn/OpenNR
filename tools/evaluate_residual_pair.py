"""Post-selection test evaluation and fixed validation galleries.

This tool is intentionally separate from the trainer.  Candidate checkpoints
are selected from validation history first; this script then reads the frozen
test split exactly once for descriptive reporting and never writes back to the
training view.  Galleries use fixed validation sequences and frame IDs so the
direct and residual arms see identical visual examples.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import torch

from joint_parent_tone_model import load_joint_checkpoint
from prepare_conditioning_pilot import sha
from train_residual_target_pair import (
    ResidualTargetJointModel,
    ResidualTargetToneHead,
    ResidualView,
    _aggregate,
    _sha256_file,
    evaluate_source,
)


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("candidate must be NAME=CHECKPOINT")
    name, raw = value.split("=", 1)
    if not name.strip() or not raw.strip():
        raise argparse.ArgumentTypeError("candidate must be NAME=CHECKPOINT")
    return name.strip(), Path(raw).resolve()


def _load_candidate(name: str, path: Path, runtime_checkpoint: Path):
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("architecture") != "semantic_residual_target_experiment_v1":
        raise ValueError(f"{name}: unexpected candidate architecture")
    if payload.get("test_used") is True or payload.get("run", {}).get("test_used") is True:
        raise ValueError(f"{name}: candidate is marked test-used")
    base, _ = load_joint_checkpoint(runtime_checkpoint)
    arm = str(payload.get("arm"))
    if arm == "direct":
        model = base
        model.parent.load_state_dict(payload["parent_model"], strict=True)
        model.head.load_state_dict(payload["head"], strict=True)
    elif arm == "residual":
        base_state = {key: value.detach().cpu().clone() for key, value in base.head.state_dict().items()}
        residual_head = ResidualTargetToneHead(base_state).cuda()
        parent = base.parent
        del base
        model = ResidualTargetJointModel(parent, residual_head).cuda().eval()
        model.parent.load_state_dict(payload["parent_model"], strict=True)
        model.head.load_state_dict(payload["head"], strict=True)
    else:
        raise ValueError(f"{name}: unsupported arm {arm!r}")
    model.cuda().eval()
    return model, payload


@torch.no_grad()
def _collect_gallery_predictions(model, source, residual_storage, frames: list[int], arm: str):
    sequence = source.validation.sequence_ids[0]
    keys = [(sequence, 0), (sequence, 1)]
    if any(key not in source.validation.streams for key in keys):
        raise ValueError(f"{source.label}: fixed gallery sequence lacks both eyes")
    global_indices = np.stack([source.validation.streams[key] for key in keys])
    local_indices = source.validation.local_from_global(global_indices)
    rgb_np = np.array(source.rgb[local_indices, 0], copy=True)
    target_np = np.array(source.rgb[local_indices, 1], copy=True)
    guides_np = np.array(source.guides[local_indices], copy=True)
    context_np = np.array(source.context[local_indices], copy=True)
    rgb_all = torch.from_numpy(rgb_np).cuda(non_blocking=True).float() / 255.0
    guides_all = torch.from_numpy(guides_np).cuda(non_blocking=True).float()
    context_all = torch.from_numpy(context_np).cuda(non_blocking=True).float()
    wanted = set(frames)
    captured = {}
    state = None
    for frame in range(64):
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            if arm == "direct":
                prediction, state = model.forward_temporal(
                    rgb_all[:, frame], guides_all[:, frame], context_all[:, frame], state
                )
            else:
                prediction, _, state = model.forward_temporal_residual(
                    rgb_all[:, frame], guides_all[:, frame], context_all[:, frame], state
                )
        if frame + 1 in wanted:
            captured[frame + 1] = np.clip(prediction.float().cpu().numpy(), 0.0, 1.0)
    del rgb_all, guides_all, context_all, state
    torch.cuda.empty_cache()
    return {
        "sequence_id": sequence,
        "frames": frames,
        "rgb": {
            frame: rgb_np[:, frame - 1].astype(np.float32) / 255.0 for frame in frames
        },
        "teacher": {
            frame: target_np[:, frame - 1].astype(np.float32) / 255.0 for frame in frames
        },
        "predictions": captured,
    }


def _as_image(array: np.ndarray) -> Image.Image:
    array = np.asarray(array)
    if array.ndim == 3 and array.shape[0] == 3 and array.shape[-1] != 3:
        array = np.moveaxis(array, 0, -1)
    return Image.fromarray(np.clip(array * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="RGB")


def _sheet(images: list[tuple[str, Image.Image]], thumb: int = 256) -> Image.Image:
    font = ImageFont.load_default()
    label_height = 24
    canvas = Image.new("RGB", (thumb * len(images), thumb + label_height), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    for index, (label, image) in enumerate(images):
        image = image.resize((thumb, thumb), Image.Resampling.BILINEAR)
        x = index * thumb
        canvas.paste(image, (x, label_height))
        draw.text((x + 4, 5), label, fill=(255, 255, 255), font=font)
    return canvas


def _render_galleries(
    output: Path,
    view: ResidualView,
    candidate_payloads: dict[str, dict],
    candidate_predictions: dict[str, dict[str, dict]],
    frames: list[int],
) -> dict:
    gallery_root = output / "galleries"
    gallery_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "opennr-fixed-validation-gallery-v1",
        "split": "validation",
        "source_labels": view.source_labels,
        "fixed_frame_ids": frames,
        "eyes": [0, 1],
        "candidates": {
            name: {
                "arm": payload["arm"],
                "step": int(payload["step"]),
            }
            for name, payload in candidate_payloads.items()
        },
        "files": [],
        "test_used": False,
    }
    for source in view.sources:
        source_dir = gallery_root / source.label
        source_dir.mkdir(parents=True, exist_ok=True)
        for frame in frames:
            for eye in (0, 1):
                base = candidate_predictions[next(iter(candidate_predictions))][source.label]["rgb"][frame][eye]
                teacher = candidate_predictions[next(iter(candidate_predictions))][source.label]["teacher"][frame][eye]
                images = [("B", _as_image(base)), ("T", _as_image(teacher))]
                for name, predictions in candidate_predictions.items():
                    prediction = predictions[source.label]["predictions"][frame][eye]
                    error = np.clip(np.abs(prediction - teacher) * 4.0, 0.0, 1.0)
                    images.append((f"{name}:P", _as_image(prediction)))
                    images.append((f"{name}:4xerr", _as_image(error)))
                filename = f"frame_{frame:03d}_eye_{eye}.png"
                path = source_dir / filename
                _sheet(images).save(path)
                manifest["files"].append(
                    {
                        "source_label": source.label,
                        "sequence_id": candidate_predictions[next(iter(candidate_predictions))][source.label]["sequence_id"],
                        "frame_id": frame,
                        "eye": eye,
                        "path": str(path.resolve()),
                        "sha256": sha(path),
                    }
                )
    _write_json(output / "fixed_gallery_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", type=Path, required=True)
    parser.add_argument("--candidate", action="append", type=_parse_candidate, required=True)
    parser.add_argument("--runtime-checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gallery", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verify-view-files", action="store_true")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(output)
    output.mkdir(parents=True, exist_ok=True)
    view = ResidualView(args.view.resolve(), verify_hashes=args.verify_view_files)
    candidate_metadata = {}
    candidates = {}
    for name, path in args.candidate:
        if not path.is_file():
            raise FileNotFoundError(path)
        payload = torch.load(path, map_location="cpu", weights_only=False)
        run = payload.get("run", {})
        if run.get("view_manifest_sha256") != _sha256_file(view.root / "manifest.json"):
            raise ValueError(f"{name}: checkpoint view identity differs")
        candidate_metadata[name] = {
            "arm": payload.get("arm"),
            "step": int(payload.get("step", -1)),
        }
        candidates[name] = {
            "path": str(path.resolve()),
            "sha256": _sha256_file(path),
            "arm": payload.get("arm"),
            "step": int(payload.get("step", -1)),
            "validation_aggregate": payload.get("validation", {}).get("aggregate"),
            "test_used": payload.get("test_used"),
        }
    result = {
        "schema": "opennr-residual-postselection-evaluation-v1",
        "view": str(view.root),
        "view_manifest_sha256": _sha256_file(view.root / "manifest.json"),
        "runtime_checkpoint": str(args.runtime_checkpoint.resolve()),
        "candidates": candidates,
        "test": {},
        "selection": {
            "frozen_before_test": True,
            "test_used_for_tuning": False,
            "primary_validation_metric": "aggregate MAE",
        },
        "created_epoch": time.time(),
    }
    for name, path in [(name, Path(item["path"])) for name, item in candidates.items()]:
        print(f"loading candidate {name}: {path}", flush=True)
        model, payload = _load_candidate(name, path, args.runtime_checkpoint.resolve())
        arm = str(payload["arm"])
        per_source = {}
        for source in view.sources:
            print(f"test {name}/{source.label}", flush=True)
            per_source[source.label] = evaluate_source(
                model, source.test, view.residual, view.tail_threshold, arm
            )
        result["test"][name] = {
            "arm": arm,
            "step": int(payload["step"]),
            "sources": per_source,
            "aggregate": _aggregate(per_source),
            "test_used_for_tuning": False,
            "post_selection_only": True,
        }
        del model
        torch.cuda.empty_cache()
    names = list(result["test"])
    if len(names) == 2:
        left, right = names
        result["comparison"] = {
            "candidate_order": names,
            "delta_second_minus_first": {
                field: result["test"][right]["aggregate"].get(field)
                - result["test"][left]["aggregate"].get(field)
                for field in (
                    "mae",
                    "psnr",
                    "temporal_delta_mae",
                    "temporal_warp_mae",
                    "stereo_disagreement_mae",
                )
            },
        }
    if args.gallery:
        frames = [1, 16, 32, 48, 64]
        gallery_predictions = {}
        for name, path in [(name, Path(item["path"])) for name, item in candidates.items()]:
            print(f"gallery candidate {name}", flush=True)
            model, payload = _load_candidate(name, path, args.runtime_checkpoint.resolve())
            gallery_predictions[name] = {}
            for source in view.sources:
                gallery_predictions[name][source.label] = _collect_gallery_predictions(
                    model, source, view.residual, frames, str(payload["arm"])
                )
            del model
            torch.cuda.empty_cache()
        _render_galleries(output, view, candidate_metadata, gallery_predictions, frames)
        result["gallery"] = {
            "manifest": str((output / "fixed_gallery_manifest.json").resolve()),
            "split": "validation",
            "fixed_frame_ids": frames,
            "test_used": False,
        }
    _write_json(output / "test_evaluation.json", result)
    _write_json(
        output / "status.json",
        {
            "state": "complete",
            "test_used_for_tuning": False,
            "post_selection_test_evaluation": True,
            "gallery_written": bool(args.gallery),
        },
    )
    print(json.dumps({"state": "complete", "candidates": names, "test_used_for_tuning": False}), flush=True)


if __name__ == "__main__":
    main()
