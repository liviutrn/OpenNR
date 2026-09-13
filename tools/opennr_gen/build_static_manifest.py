"""Build a small, auditable OpenNR-GEN static target-generation tranche.

The source cache is read-only.  This utility selects one representative frame
per sequence from the original *training* split, then includes both eyes.  It
writes PNG copies of the raw/pre-NR input and the original DLSS5-NR teacher so
the later offline enhancer has a self-contained three-image sample directory.

The selection is deliberately a pilot, not a claim that metadata can identify
faces or materials.  ``coverage_tags`` are left as ``needs_visual_review`` and
must be completed from the generated contact sheet before targets are accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _to_pil(array: np.ndarray) -> Image.Image:
    if array.ndim != 3 or array.shape[0] != 3:
        raise ValueError(f"expected CHW RGB array, got {array.shape}")
    image = np.moveaxis(array, 0, -1)
    if image.dtype != np.uint8:
        image = np.clip(image, 0, 255).astype(np.uint8)
    return Image.fromarray(image, mode="RGB")


def _candidate_feature(image: np.ndarray) -> np.ndarray:
    """Create a compact deterministic diversity feature from teacher RGB."""

    pil = _to_pil(image)
    small = np.asarray(pil.resize((16, 16), Image.Resampling.BILINEAR), dtype=np.float32) / 255.0
    gray = small.mean(axis=2)
    dx = np.diff(gray, axis=1)
    dy = np.diff(gray, axis=0)
    stats = np.asarray(
        [
            float(small.mean()),
            float(small.std()),
            float(np.quantile(gray, 0.05)),
            float(np.quantile(gray, 0.95)),
            float(np.abs(dx).mean()),
            float(np.abs(dy).mean()),
            float((small.max(axis=2) - small.min(axis=2)).mean()),
        ],
        dtype=np.float32,
    )
    return np.concatenate([small.reshape(-1), gray.reshape(-1), stats])


def _distance(a: np.ndarray, b: np.ndarray) -> float:
    # The feature is already in bounded [0, 1] ranges.  L2 is sufficient for
    # a small deterministic pilot and is easy to reproduce independently.
    return float(np.sqrt(np.mean((a - b) ** 2)))


def _pick_diverse(
    candidates: list[dict[str, Any]],
    features: list[np.ndarray],
    count: int,
    required_sources: dict[str, int],
) -> list[int]:
    if count <= 0 or count > len(candidates):
        raise ValueError(f"invalid selection count {count} for {len(candidates)} candidates")

    selected: list[int] = []
    selected_set: set[int] = set()

    def choose_from(pool: list[int], n: int) -> None:
        for _ in range(n):
            available = [i for i in pool if i not in selected_set]
            if not available:
                return
            if not selected:
                chosen = min(available, key=lambda i: candidates[i]["sequence_id"])
            else:
                chosen = max(
                    available,
                    key=lambda i: (
                        min(_distance(features[i], features[j]) for j in selected),
                        candidates[i]["sequence_id"],
                    ),
                )
            selected.append(chosen)
            selected_set.add(chosen)

    for source, quota in sorted(required_sources.items()):
        pool = [i for i, row in enumerate(candidates) if row["cache_source"] == source]
        choose_from(pool, min(quota, len(pool)))

    choose_from(list(range(len(candidates))), count - len(selected))
    if len(selected) != count:
        raise RuntimeError(f"only selected {len(selected)} of {count} requested")
    return selected


def _label_font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 16)
    except OSError:
        return ImageFont.load_default()


def _write_selection_gallery(
    samples: list[dict[str, Any]], output: Path, tile_size: int = 192
) -> None:
    """Write a broad raw/teacher contact sheet for mandatory visual review."""

    font = _label_font()
    pair_count = len(samples) // 2
    pair_columns = 4
    pair_rows = math.ceil(pair_count / pair_columns)
    canvas = Image.new(
        "RGB",
        (pair_columns * 2 * tile_size, pair_rows * 2 * tile_size),
        (22, 22, 22),
    )
    draw = ImageDraw.Draw(canvas)
    for pair_index in range(pair_count):
        left = samples[2 * pair_index]
        right = samples[2 * pair_index + 1]
        for eye_index, sample in enumerate((left, right)):
            x = (pair_index % pair_columns) * 2 * tile_size
            y = (pair_index // pair_columns) * 2 * tile_size + eye_index * tile_size
            with Image.open(sample["raw_input_path"]) as raw:
                raw = raw.convert("RGB").resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                canvas.paste(raw, (x, y))
            draw.rectangle((x, y, x + tile_size - 1, y + 28), fill=(0, 0, 0))
            draw.text(
                (x + 4, y + 4),
                f"{sample['sample_id']} eye{sample['eye']} raw",
                fill=(255, 255, 255),
                font=font,
            )
            tx = x + tile_size
            ty = y
            with Image.open(sample["teacher_path"]) as teacher:
                teacher = teacher.convert("RGB").resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                canvas.paste(teacher, (tx, ty))
            draw.rectangle((tx, ty, tx + tile_size - 1, ty + 28), fill=(0, 0, 0))
            draw.text(
                (tx + 4, ty + 4),
                f"{sample['sample_id']} eye{sample['eye']} teacher",
                fill=(255, 255, 255),
                font=font,
            )
    canvas.save(output, format="PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scene-count", type=int, default=20)
    parser.add_argument(
        "--high-effect-quota",
        type=int,
        default=4,
        help="minimum varied_high_effect scenes when available",
    )
    args = parser.parse_args()

    source = args.source_cache.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for name in ("complete.json", "rows.json", "patches.json", "rgb.npy"):
        if not (source / name).exists():
            raise FileNotFoundError(source / name)

    complete_path = source / "complete.json"
    rows_path = source / "rows.json"
    patches_path = source / "patches.json"
    complete = json.loads(complete_path.read_text(encoding="utf-8"))
    if complete.get("test_used_for_tuning") is not False:
        raise ValueError("source cache does not explicitly protect its test split")
    rows = json.loads(rows_path.read_text(encoding="utf-8"))
    rgb = np.load(source / "rgb.npy", mmap_mode="r")
    if rgb.ndim != 5 or tuple(rgb.shape[1:3]) != (2, 3):
        raise ValueError(f"unexpected RGB shape {rgb.shape}")
    if len(rows) != rgb.shape[0]:
        raise ValueError(f"row/RGB mismatch: {len(rows)} != {rgb.shape[0]}")

    by_sequence: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.get("split") == "train" and int(row.get("eye", -1)) == 0:
            by_sequence[(str(row["cache_source"]), str(row["sequence_id"]))].append(index)

    candidates: list[dict[str, Any]] = []
    for (cache_source, sequence_id), indices in sorted(by_sequence.items()):
        indices.sort(key=lambda i: int(rows[i]["frame_id"]))
        chosen = indices[len(indices) // 2]
        row = rows[chosen]
        candidates.append(
            {
                "source_row_index": chosen,
                "cache_source": cache_source,
                "sequence_id": sequence_id,
                "frame_id": int(row["frame_id"]),
                "sample_index": int(row.get("sample_index", row["frame_id"])),
            }
        )
    if len(candidates) < args.scene_count:
        raise ValueError(f"only {len(candidates)} train sequences are available")

    features = [_candidate_feature(np.asarray(rgb[item["source_row_index"], 1])) for item in candidates]
    source_counts = Counter(item["cache_source"] for item in candidates)
    required_sources: dict[str, int] = {}
    if "prior_allcohort_291" in source_counts:
        required_sources["prior_allcohort_291"] = max(1, args.scene_count - args.high_effect_quota)
    if "varied_high_effect_28" in source_counts:
        required_sources["varied_high_effect_28"] = min(args.high_effect_quota, args.scene_count)
    selected_indices = _pick_diverse(candidates, features, args.scene_count, required_sources)

    selected = [candidates[i] for i in selected_indices]
    selected.sort(key=lambda item: (item["cache_source"], item["sequence_id"]))
    scene_splits: dict[tuple[str, str], str] = {}
    by_selected_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in selected:
        by_selected_source[item["cache_source"]].append(item)
    for source_name, source_items in sorted(by_selected_source.items()):
        train_scene_count = max(1, round(len(source_items) * 0.70))
        for position, item in enumerate(source_items):
            scene_splits[(item["cache_source"], item["sequence_id"])] = (
                "train" if position < train_scene_count else "validation"
            )

    sample_rows: list[dict[str, Any]] = []
    sample_dirs: list[Path] = []
    row_lookup = {
        (str(row["cache_source"]), str(row["sequence_id"]), int(row["frame_id"]), int(row["eye"])): index
        for index, row in enumerate(rows)
        if row.get("split") == "train"
    }
    for pair_index, item in enumerate(selected):
        key_base = (item["cache_source"], item["sequence_id"], item["frame_id"])
        pair_id = f"scene-{pair_index:03d}"
        for eye in (0, 1):
            key = (*key_base, eye)
            if key not in row_lookup:
                raise ValueError(f"missing stereo partner for {key}")
            source_index = row_lookup[key]
            sample_id = f"{pair_id}-eye{eye}"
            sample_dir = output / "samples" / sample_id
            sample_dir.mkdir(parents=True, exist_ok=True)
            raw_path = sample_dir / "raw_input.png"
            teacher_path = sample_dir / "dlss5_teacher.png"
            _to_pil(np.asarray(rgb[source_index, 0])).save(raw_path, format="PNG", optimize=True)
            _to_pil(np.asarray(rgb[source_index, 1])).save(teacher_path, format="PNG", optimize=True)
            source_row = rows[source_index]
            sample_rows.append(
                {
                    "sample_id": sample_id,
                    "pair_id": pair_id,
                    "eye": eye,
                    "student_split": scene_splits[(item["cache_source"], item["sequence_id"])],
                    "coverage_tags": ["needs_visual_review"],
                    "source_row_index": source_index,
                    "source_row_sha256": _canonical_sha256(source_row),
                    "source_split": source_row.get("split"),
                    "cache_source": item["cache_source"],
                    "sequence_id": item["sequence_id"],
                    "frame_id": item["frame_id"],
                    "sample_index": int(source_row.get("sample_index", item["sample_index"])),
                    "history_reset": bool(source_row.get("history_reset", False)),
                    "raw_input_path": str(raw_path),
                    "teacher_path": str(teacher_path),
                    "enhanced_target_path": str(sample_dir / "enhanced_target.png"),
                }
            )
            sample_dirs.append(sample_dir)

    body: dict[str, Any] = {
        "schema": "opennr-gen-static-manifest-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_cache": str(source),
        "source_complete_sha256": sha256_file(complete_path),
        "source_rows_sha256": sha256_file(rows_path),
        "source_patches_sha256": sha256_file(patches_path),
        "source_rgb_sha256": sha256_file(source / "rgb.npy"),
        "source_rgb_shape": list(rgb.shape),
        "source_rgb_dtype": str(rgb.dtype),
        "source_test_used_for_tuning": False,
        "scene_count": args.scene_count,
        "eye_image_count": len(sample_rows),
        "scene_split_counts": dict(Counter(scene_splits.values())),
        "source_counts": dict(
            sorted(Counter(item["cache_source"] for item in selected).items())
        ),
        "selection_policy": {
            "source_split": "train only; original validation/test rows are untouched",
            "one_frame_per_sequence": "middle frame of each sequence after frame-id sort",
            "diversity": "greedy farthest-point selection over teacher RGB/color/edge features",
            "stereo": "both eye rows are required for every selected frame",
            "target_gate": "manual visual review required before student training",
        },
        "samples": sample_rows,
    }
    body["manifest_sha256"] = _canonical_sha256(body)
    manifest_path = output / "manifest.json"
    manifest_path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (output / "manifest.sha256").write_text(body["manifest_sha256"] + "  manifest.json\n", encoding="utf-8")
    _write_selection_gallery(sample_rows, output / "selection_gallery.png")
    review_template = {
        "schema": "opennr-gen-static-review-v1",
        "manifest": str(manifest_path),
        "instructions": [
            "Review selection_gallery.png and each sample pair.",
            "Replace needs_visual_review with one or more required material/scene tags.",
            "Reject a target later if identity, geometry, material, lighting direction, or stereo pairing changes.",
        ],
        "allowed_tags": [
            "face",
            "hair",
            "skin",
            "armor",
            "cloth",
            "stone",
            "wood",
            "foliage",
            "interior",
            "exterior",
            "deep_shadows",
            "highlights",
            "distant_scene",
            "other",
        ],
        "samples": [
            {"sample_id": row["sample_id"], "coverage_tags": row["coverage_tags"]}
            for row in sample_rows
        ],
    }
    (output / "review_template.json").write_text(json.dumps(review_template, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "manifest": str(manifest_path),
                "manifest_sha256": body["manifest_sha256"],
                "scene_count": args.scene_count,
                "eye_image_count": len(sample_rows),
                "scene_split_counts": body["scene_split_counts"],
                "source_counts": body["source_counts"],
                "review_gallery": str(output / "selection_gallery.png"),
                "test_used_for_tuning": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
