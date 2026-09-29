"""Prepare and assemble a small, reproducible PixRestore-S Skyrim A/B test.

The source screenshots are side-by-side stereo captures.  This utility never
modifies them: it crops each eye into 512x512 inputs, creates a controlled
50%-downsampled/blurred variant, writes four ordered JSONL manifests, and can
assemble PixRestore outputs into labelled comparison sheets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


EYE_WIDTH = 2496
EYE_HEIGHT = 2688
CROP_SIZE = 512

# Coordinates are normalized to an individual eye.  These are deliberately
# fixed, hand-selected crops from three representative screenshots in the
# supplied collection, so clean/degraded and left/right runs are comparable.
# Close objects have substantial stereo disparity, so each eye has its own
# center rather than reusing one screen-space coordinate for both halves.
SAMPLES: list[dict] = [
    {
        "source": "OS_2026-09-02_18-39-03_322.png",
        "crops": {
            "face": {"left": (0.70, 0.47), "right": (0.50, 0.47)},
            "hair": {"left": (0.70, 0.37), "right": (0.50, 0.37)},
            "stone": {"left": (0.32, 0.35), "right": (0.32, 0.35)},
            "flora": {"left": (0.15, 0.52), "right": (0.24, 0.52)},
            "clothing": {"left": (0.64, 0.74), "right": (0.52, 0.74)},
        },
    },
    {
        "source": "OS_2026-09-02_18-49-32_327.png",
        "crops": {
            "face": {"left": (0.75, 0.46), "right": (0.39, 0.46)},
            "hair": {"left": (0.65, 0.38), "right": (0.39, 0.38)},
            "wood_stone": {"left": (0.35, 0.23), "right": (0.35, 0.23)},
            "grass_cobble": {"left": (0.28, 0.78), "right": (0.35, 0.78)},
            "clothing": {"left": (0.64, 0.70), "right": (0.42, 0.70)},
        },
    },
    {
        "source": "OS_2026-09-02_18-52-28_396.png",
        "crops": {
            "face": {"left": (0.76, 0.43), "right": (0.40, 0.43)},
            "hair": {"left": (0.64, 0.35), "right": (0.40, 0.35)},
            "stone_building": {"left": (0.36, 0.23), "right": (0.36, 0.23)},
            "grass_cobble": {"left": (0.24, 0.76), "right": (0.35, 0.76)},
            "clothing": {"left": (0.61, 0.72), "right": (0.42, 0.72)},
        },
    },
]


def stable_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def crop_box(center: tuple[float, float]) -> tuple[int, int, int, int]:
    cx = round(center[0] * EYE_WIDTH)
    cy = round(center[1] * EYE_HEIGHT)
    left = max(0, min(EYE_WIDTH - CROP_SIZE, cx - CROP_SIZE // 2))
    top = max(0, min(EYE_HEIGHT - CROP_SIZE, cy - CROP_SIZE // 2))
    return left, top, left + CROP_SIZE, top + CROP_SIZE


def make_degraded(image: Image.Image) -> Image.Image:
    half = image.resize((CROP_SIZE // 2, CROP_SIZE // 2), Image.Resampling.BILINEAR)
    restored_size = half.resize((CROP_SIZE, CROP_SIZE), Image.Resampling.BILINEAR)
    return restored_size.filter(ImageFilter.GaussianBlur(radius=0.45))


def write_manifest(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True) + "\n")


def prepare(source_dir: Path, output_dir: Path) -> None:
    input_root = output_dir / "inputs"
    manifest_root = output_dir / "manifests"
    input_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)

    metadata: dict = {
        "source_dir": str(source_dir),
        "source_dimensions": [EYE_WIDTH * 2, EYE_HEIGHT],
        "eye_dimensions": [EYE_WIDTH, EYE_HEIGHT],
        "crop_size": CROP_SIZE,
        "degradation": "512 -> 256 bilinear -> 512 bilinear -> GaussianBlur(0.45), saved as PNG",
        "samples": [],
    }
    rows: dict[tuple[str, str], list[dict]] = {
        (condition, eye): []
        for condition in ("clean", "degraded")
        for eye in ("left", "right")
    }

    for sample_index, sample in enumerate(SAMPLES):
        source_path = source_dir / sample["source"]
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with Image.open(source_path) as source_image:
            source_image = source_image.convert("RGB")
            if source_image.size != (EYE_WIDTH * 2, EYE_HEIGHT):
                raise ValueError(f"Unexpected dimensions for {source_path}: {source_image.size}")
            sample_meta = {
                "source": str(source_path),
                "source_sha256": stable_digest(source_path),
                "crops": [],
            }
            for category, center_value in sample["crops"].items():
                centers = (
                    center_value
                    if isinstance(center_value, dict)
                    else {"left": center_value, "right": center_value}
                )
                crop_meta = {"category": category, "centers": centers, "boxes": {}}
                sample_meta["crops"].append(crop_meta)
                for eye_index, eye in enumerate(("left", "right")):
                    center = tuple(centers[eye])
                    box = crop_box(center)
                    crop_meta["boxes"][eye] = box
                    eye_image = source_image.crop(
                        (eye_index * EYE_WIDTH, 0, (eye_index + 1) * EYE_WIDTH, EYE_HEIGHT)
                    )
                    crop = eye_image.crop(box)
                    stem = f"{sample_index:02d}_{Path(sample['source']).stem}_{category}"
                    clean_path = input_root / "clean" / eye / f"{stem}.png"
                    degraded_path = input_root / "degraded" / eye / f"{stem}.png"
                    clean_path.parent.mkdir(parents=True, exist_ok=True)
                    degraded_path.parent.mkdir(parents=True, exist_ok=True)
                    crop.save(clean_path)
                    make_degraded(crop).save(degraded_path)
                    common = {
                        "source": str(source_path),
                        "source_sha256": sample_meta["source_sha256"],
                        "category": category,
                        "eye": eye,
                        "box": box,
                    }
                    rows[("clean", eye)].append({"type": "clean", "data": eye, "lq": str(clean_path), **common})
                    rows[("degraded", eye)].append(
                        {"type": "degraded", "data": eye, "lq": str(degraded_path), **common}
                    )
            metadata["samples"].append(sample_meta)

    for (condition, eye), manifest_rows in rows.items():
        write_manifest(manifest_root / f"{condition}_{eye}.jsonl", manifest_rows)
    (output_dir / "prepare_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {sum(len(value) for value in rows.values())} input files under {input_root}")
    print(
        "Each manifest contains "
        f"{len(rows[('clean', 'left')])} crops; run each eye/condition separately for matched seeds."
    )


def resize_short_edge_and_crop(image: Image.Image, size: int) -> Image.Image:
    scale = size / min(image.size)
    resized = image.resize(
        (round(image.width * scale), round(image.height * scale)),
        Image.Resampling.BICUBIC,
    )
    left = (resized.width - size) // 2
    top = (resized.height - size) // 2
    return resized.crop((left, top, left + size, top + size))


def prepare_collection(source_dir: Path, output_dir: Path) -> None:
    """Prepare one center crop per eye for every supplied screenshot."""
    source_paths = sorted(source_dir.glob("*.png"))
    if not source_paths:
        raise FileNotFoundError(f"No PNG screenshots found under {source_dir}")

    input_root = output_dir / "inputs"
    manifest_root = output_dir / "manifests"
    input_root.mkdir(parents=True, exist_ok=True)
    manifest_root.mkdir(parents=True, exist_ok=True)
    rows: dict[tuple[str, str], list[dict]] = {
        (condition, eye): []
        for condition in ("clean", "degraded")
        for eye in ("left", "right")
    }
    metadata: dict = {
        "source_dir": str(source_dir),
        "source_dimensions": [EYE_WIDTH * 2, EYE_HEIGHT],
        "eye_dimensions": [EYE_WIDTH, EYE_HEIGHT],
        "crop_size": CROP_SIZE,
        "crop_rule": "eye split, then PixRestore center_crop preprocessing (short edge to 512, center crop)",
        "degradation": "512 -> 256 bilinear -> 512 bilinear -> GaussianBlur(0.45), saved as PNG",
        "samples": [],
    }

    for sample_index, source_path in enumerate(source_paths):
        with Image.open(source_path) as source_image:
            source_image = source_image.convert("RGB")
            if source_image.size != (EYE_WIDTH * 2, EYE_HEIGHT):
                raise ValueError(f"Unexpected dimensions for {source_path}: {source_image.size}")
            sample_meta = {
                "source": str(source_path),
                "source_sha256": stable_digest(source_path),
                "crops": [{"category": "center", "centers": {"left": (0.5, 0.5), "right": (0.5, 0.5)}}],
            }
            metadata["samples"].append(sample_meta)
            for eye_index, eye in enumerate(("left", "right")):
                eye_image = source_image.crop(
                    (eye_index * EYE_WIDTH, 0, (eye_index + 1) * EYE_WIDTH, EYE_HEIGHT)
                )
                crop = resize_short_edge_and_crop(eye_image, CROP_SIZE)
                stem = f"{sample_index:02d}_{source_path.stem}_center"
                clean_path = input_root / "clean" / eye / f"{stem}.png"
                degraded_path = input_root / "degraded" / eye / f"{stem}.png"
                clean_path.parent.mkdir(parents=True, exist_ok=True)
                degraded_path.parent.mkdir(parents=True, exist_ok=True)
                crop.save(clean_path)
                make_degraded(crop).save(degraded_path)
                common = {
                    "source": str(source_path),
                    "source_sha256": sample_meta["source_sha256"],
                    "category": "center",
                    "eye": eye,
                }
                rows[("clean", eye)].append({"type": "clean", "data": eye, "lq": str(clean_path), **common})
                rows[("degraded", eye)].append(
                    {"type": "degraded", "data": eye, "lq": str(degraded_path), **common}
                )

    for (condition, eye), manifest_rows in rows.items():
        write_manifest(manifest_root / f"{condition}_{eye}.jsonl", manifest_rows)
    (output_dir / "prepare_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Prepared {sum(len(value) for value in rows.values())} collection input files under {input_root}")
    print(f"Each manifest contains {len(rows[('clean', 'left')])} center crops.")


def label_image(image: Image.Image, label: str) -> Image.Image:
    canvas = Image.new("RGB", (image.width + 2, image.height + 38), (20, 20, 20))
    canvas.paste(image.convert("RGB"), (1, 37))
    ImageDraw.Draw(canvas).text((10, 10), label, fill=(240, 240, 240))
    return canvas


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGB").copy()


def compare_outputs(output_dir: Path) -> None:
    metadata = json.loads((output_dir / "prepare_metadata.json").read_text(encoding="utf-8"))
    comparison_root = output_dir / "comparisons"
    stereo_root = output_dir / "stereo"
    comparison_root.mkdir(parents=True, exist_ok=True)
    stereo_root.mkdir(parents=True, exist_ok=True)
    metrics: list[dict] = []

    for sample_index, sample in enumerate(metadata["samples"]):
        source_stem = Path(sample["source"]).stem
        for crop in sample["crops"]:
            category = crop["category"]
            stem = f"{sample_index:02d}_{source_stem}_{category}"
            clean_restored: dict[str, Image.Image] = {}
            degraded_restored: dict[str, Image.Image] = {}
            for eye in ("left", "right"):
                clean_input_path = output_dir / "inputs" / "clean" / eye / f"{stem}.png"
                degraded_input_path = output_dir / "inputs" / "degraded" / eye / f"{stem}.png"
                clean_output_path = (
                    output_dir / "outputs" / "clean" / eye / "pixrestore_cfg1_step1" / f"{stem}.png"
                )
                degraded_output_path = (
                    output_dir / "outputs" / "degraded" / eye / "pixrestore_cfg1_step1" / f"{stem}.png"
                )
                required = (clean_input_path, degraded_input_path, clean_output_path, degraded_output_path)
                if not all(path.is_file() for path in required):
                    print(f"Skipping incomplete result: {stem} {eye}")
                    continue
                clean_input = load_image(clean_input_path)
                degraded_input = load_image(degraded_input_path)
                clean_output = load_image(clean_output_path)
                degraded_output = load_image(degraded_output_path)
                clean_restored[eye] = clean_output
                degraded_restored[eye] = degraded_output
                panels = [
                    label_image(clean_input, "clean input"),
                    label_image(clean_output, "PixRestore(clean)"),
                    label_image(degraded_input, "degraded input"),
                    label_image(degraded_output, "PixRestore(degraded)"),
                ]
                canvas = Image.new("RGB", (sum(panel.width for panel in panels), max(panel.height for panel in panels)))
                x = 0
                for panel in panels:
                    canvas.paste(panel, (x, 0))
                    x += panel.width
                canvas.save(comparison_root / f"{stem}__{eye}.jpg", quality=94, subsampling=0)

                clean_delta = ImageChops.difference(clean_input, clean_output).convert("L")
                degraded_delta = ImageChops.difference(degraded_input, degraded_output).convert("L")
                metrics.append(
                    {
                        "stem": stem,
                        "eye": eye,
                        "clean_mean_abs_change_8bit": sum(clean_delta.getdata()) / (clean_delta.width * clean_delta.height),
                        "degraded_mean_abs_change_8bit": sum(degraded_delta.getdata()) / (degraded_delta.width * degraded_delta.height),
                    }
                )
            if len(clean_restored) == 2:
                for condition, restored in (("clean", clean_restored), ("degraded", degraded_restored)):
                    left = label_image(restored["left"], "left eye")
                    right = label_image(restored["right"], "right eye")
                    stereo = Image.new("RGB", (left.width + right.width, max(left.height, right.height)))
                    stereo.paste(left, (0, 0))
                    stereo.paste(right, (left.width, 0))
                    stereo.save(stereo_root / f"{stem}__{condition}_restored.jpg", quality=94, subsampling=0)

    (output_dir / "output_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote comparisons under {comparison_root}")
    print(f"Wrote stereo sheets under {stereo_root}")
    print(f"Recorded metrics for {len(metrics)} eye/condition pairs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "prepare-collection", "assemble"))
    parser.add_argument("--source-dir", type=Path, default=Path(r"E:\MGO-RC3-fresh\overwrite\Root\Screenshots"))
    parser.add_argument("--output-dir", type=Path, default=Path(r"E:\PixRestore-Skyrim-Test-20260903"))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.source_dir, args.output_dir)
    elif args.mode == "prepare-collection":
        prepare_collection(args.source_dir, args.output_dir)
    else:
        compare_outputs(args.output_dir)


if __name__ == "__main__":
    main()
