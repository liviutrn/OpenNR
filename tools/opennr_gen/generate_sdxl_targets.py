"""Generate structure-preserving offline GEN targets with SDXL + Canny ControlNet.

This is intentionally an offline target builder.  It never belongs in the
Skyrim runtime path.  The input to the enhancer is the already-rendered
DLSS5-NR teacher image; the raw/pre-NR image is retained only as provenance and
for later three-way review.

The default denoising strength is deliberately conservative.  A target is
not accepted because diffusion completed: every output remains ``review_pending``
until geometry, identity, materials, lighting direction, and stereo pairing
are visually audited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter


SDXL_REVISION = "462165984030d82259a11f4367a4eed129e94a7b"
CONTROLNET_REVISION = "eb115a19a10d14909256db740ed109532ab1483c"
DEFAULT_BASE_MODEL_ID = "stabilityai/stable-diffusion-xl-base-1.0"
DEFAULT_BASE_LICENSE = "CreativeML Open RAIL++-M / openrail++"
DEFAULT_PROMPT = (
    "photorealistic fantasy RPG game screenshot, exact same scene and camera; "
    "preserve composition, objects, geometry, pose, facial identity, hair silhouette, "
    "armor and cloth shapes, material colors, lighting direction and shadows; add only "
    "subtle physically plausible skin, hair, cloth, metal, stone and foliage detail, "
    "with natural local contrast and faithful lighting"
)
DEFAULT_NEGATIVE_PROMPT = (
    "new or missing objects, changed face or person, altered pose, extra limbs, "
    "warped geometry, changed camera or crop, text, logo, cartoon, plastic skin, "
    "waxy face, oversharpening, halos, color cast, fog, dramatic relighting, "
    "blown highlights, crushed shadows, duplicate objects"
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verify_manifest(manifest_path: Path, review_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "opennr-gen-static-manifest-v1":
        raise ValueError("unsupported GEN static manifest schema")
    recorded_hash = manifest.get("manifest_sha256")
    body = dict(manifest)
    body.pop("manifest_sha256", None)
    if canonical_sha256(body) != recorded_hash:
        raise ValueError("static manifest hash does not match its contents")
    if manifest.get("source_test_used_for_tuning") is not False:
        raise ValueError("source test split is not explicitly protected")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("schema") != "opennr-gen-static-coverage-review-v1":
        raise ValueError("unsupported coverage review schema")
    if review.get("selection_gate", {}).get("all_required_tags_present") is not True:
        raise ValueError("coverage review has not established required material coverage")
    pair_reviews = review.get("pair_reviews", {})
    if len(pair_reviews) != manifest.get("scene_count"):
        raise ValueError("coverage review does not cover every selected scene")
    required = set(review.get("required_coverage", []))
    observed = {
        tag
        for pair in pair_reviews.values()
        for tag in pair.get("coverage_tags", [])
    }
    missing = sorted(required - observed)
    if missing:
        raise ValueError(f"coverage review is missing required tags: {missing}")
    if any("needs_visual_review" in pair.get("coverage_tags", []) for pair in pair_reviews.values()):
        raise ValueError("coverage review still contains needs_visual_review")
    return manifest, review


def edge_control(image: Image.Image) -> Image.Image:
    """Make a conservative 3-channel edge map without a runtime OpenCV dependency."""

    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    gray = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    padded = np.pad(gray, 1, mode="edge")
    gx = (
        padded[:-2, 2:]
        + 2.0 * padded[1:-1, 2:]
        + padded[2:, 2:]
        - padded[:-2, :-2]
        - 2.0 * padded[1:-1, :-2]
        - padded[2:, :-2]
    )
    gy = (
        padded[2:, :-2]
        + 2.0 * padded[2:, 1:-1]
        + padded[2:, 2:]
        - padded[:-2, :-2]
        - 2.0 * padded[:-2, 1:-1]
        - padded[:-2, 2:]
    )
    magnitude = np.sqrt(gx * gx + gy * gy)
    threshold = max(float(np.quantile(magnitude, 0.78)), 0.025)
    edges = (magnitude >= threshold).astype(np.uint8) * 255
    edge_image = Image.fromarray(edges, mode="L").filter(ImageFilter.MaxFilter(3))
    return Image.merge("RGB", (edge_image, edge_image, edge_image))


def _selected_samples(manifest: dict[str, Any], only: set[str] | None) -> list[dict[str, Any]]:
    samples = manifest["samples"]
    if only:
        samples = [sample for sample in samples if sample["sample_id"] in only]
        missing = sorted(only - {sample["sample_id"] for sample in samples})
        if missing:
            raise ValueError(f"unknown sample IDs: {missing}")
    return samples


def _load_pipeline(model_dir: Path, controlnet_dir: Path, device: str):
    try:
        import torch
        from diffusers import ControlNetModel, StableDiffusionXLControlNetImg2ImgPipeline
    except ImportError as exc:
        raise RuntimeError(
            "GEN diffusion dependencies are missing; use the isolated runtime "
            "documented in docs/OPENNR_GEN_POC.md"
        ) from exc

    dtype = torch.float16 if device.startswith("cuda") else torch.float32
    controlnet = ControlNetModel.from_pretrained(
        controlnet_dir,
        torch_dtype=dtype,
        variant="fp16" if dtype == torch.float16 else None,
        use_safetensors=True,
        local_files_only=True,
    )
    pipe = StableDiffusionXLControlNetImg2ImgPipeline.from_pretrained(
        model_dir,
        controlnet=controlnet,
        torch_dtype=dtype,
        variant="fp16" if dtype == torch.float16 else None,
        use_safetensors=True,
        local_files_only=True,
    )
    pipe.set_progress_bar_config(disable=False)
    if device.startswith("cuda"):
        # CPU offload is important for a 16-GiB card with SDXL + ControlNet.
        pipe.enable_model_cpu_offload(gpu_id=0)
        pipe.enable_vae_tiling()
        pipe.enable_vae_slicing()
        pipe.enable_attention_slicing("max")
    else:
        pipe.to(device)
    return pipe, torch


def _write_records(path: Path, records: dict[str, Any]) -> None:
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--coverage-review", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--controlnet-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--strength", type=float, default=0.16)
    parser.add_argument("--control-scale", type=float, default=1.0)
    parser.add_argument("--guidance-scale", type=float, default=3.5)
    parser.add_argument("--seed", type=int, default=91110)
    parser.add_argument("--base-model-id", default=DEFAULT_BASE_MODEL_ID)
    parser.add_argument("--base-revision", default=SDXL_REVISION)
    parser.add_argument("--base-license", default=DEFAULT_BASE_LICENSE)
    parser.add_argument(
        "--input-role",
        choices=["raw_input", "dlss5_teacher"],
        default="dlss5_teacher",
        help="image and Canny source for SDXL; default preserves the teacher-conditioned route",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    parser.add_argument("--only", help="comma-separated sample IDs for a bounded smoke run")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not 0.05 <= args.strength <= 0.60:
        raise ValueError("strength must stay in [0.05, 0.60] for this conservative pilot")
    if args.steps < 1 or args.steps > 60:
        raise ValueError("steps must stay in [1, 60]")
    if args.control_scale <= 0.0:
        raise ValueError("control scale must be positive")

    manifest_path = args.manifest.resolve()
    review_path = args.coverage_review.resolve()
    model_dir = args.model_dir.resolve()
    controlnet_dir = args.controlnet_dir.resolve()
    output = args.output.resolve()
    manifest, review = verify_manifest(manifest_path, review_path)
    samples = _selected_samples(manifest, set(filter(None, (args.only or "").split(","))))
    for path in (model_dir, controlnet_dir):
        if not path.exists():
            raise FileNotFoundError(path)
    output.mkdir(parents=True, exist_ok=True)

    records_path = output / "target_records.json"
    coverage_review_sha256 = sha256_file(review_path)
    records: dict[str, Any] = {
        "schema": "opennr-gen-static-target-records-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "dry_run" if args.dry_run else "running",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "coverage_review": str(review_path),
        "coverage_review_sha256": coverage_review_sha256,
        "source_cache": manifest["source_cache"],
        "enhancer": {
            "family": "Stable Diffusion XL img2img + Canny ControlNet",
            "base_model": args.base_model_id,
            "base_revision": args.base_revision,
            "controlnet_model": "diffusers/controlnet-canny-sdxl-1.0",
            "controlnet_revision": CONTROLNET_REVISION,
            "license": args.base_license,
            "model_dir": str(model_dir),
            "controlnet_dir": str(controlnet_dir),
        },
        "inference": {
            "device": args.device,
            "steps": args.steps,
            "strength": args.strength,
            "control_scale": args.control_scale,
            "guidance_scale": args.guidance_scale,
            "seed_base": args.seed,
            "prompt": args.prompt,
            "negative_prompt": args.negative_prompt,
            "input_role": args.input_role,
            "raw_input_retained": True,
        },
        "review_gate": {
            "status": "pending",
            "accepted_count": 0,
            "rejected_count": 0,
            "required_checks": [
                "teacher_preference",
                "identity_and_face",
                "geometry_and_objects",
                "material_fidelity",
                "lighting_direction",
                "stereo_pair_consistency",
            ],
        },
        "samples": {},
    }
    if args.only and records_path.exists():
        existing = json.loads(records_path.read_text(encoding="utf-8"))
        if existing.get("schema") != records["schema"]:
            raise ValueError("existing target records use an unsupported schema")
        if existing.get("manifest_sha256") != records["manifest_sha256"]:
            raise ValueError("existing target records belong to a different manifest")
        if existing.get("coverage_review_sha256") != coverage_review_sha256:
            raise ValueError("existing target records belong to a different coverage review")
        if existing.get("inference") and existing["inference"] != records["inference"]:
            raise ValueError(
                "existing target records use different inference settings; use a new output directory"
            )
        existing_enhancer = existing.get("enhancer", {})
        for key in (
            "base_model",
            "base_revision",
            "controlnet_model",
            "controlnet_revision",
            "model_dir",
            "controlnet_dir",
        ):
            if existing_enhancer.get(key) not in {None, records["enhancer"].get(key)}:
                raise ValueError("existing target records use a different enhancer route")
        records["created_utc"] = existing.get("created_utc", records["created_utc"])
        records["review_gate"] = existing.get("review_gate", records["review_gate"])
        records["samples"] = existing.get("samples", {})
    _write_records(records_path, records)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "manifest_sha256": manifest["manifest_sha256"],
                    "sample_count": len(samples),
                    "model_dir": str(model_dir),
                    "controlnet_dir": str(controlnet_dir),
                    "steps": args.steps,
                    "strength": args.strength,
                },
                indent=2,
            )
        )
        return

    pipe, torch = _load_pipeline(model_dir, controlnet_dir, args.device)
    manifest_positions = {
        sample["sample_id"]: index for index, sample in enumerate(manifest["samples"])
    }
    for sample in samples:
        sample_id = sample["sample_id"]
        sample_dir = Path(sample["raw_input_path"]).resolve().parent
        target_path = Path(sample["enhanced_target_path"]).resolve()
        edge_path = sample_dir / "control_canny.png"
        input_path = (
            Path(sample["raw_input_path"])
            if args.input_role == "raw_input"
            else Path(sample["teacher_path"])
        ).resolve()
        record: dict[str, Any] = {
            "sample_id": sample_id,
            "pair_id": sample["pair_id"],
            "eye": sample["eye"],
            "status": "running",
            "seed": args.seed + manifest_positions[sample_id],
            "input_role": args.input_role,
            "input_path": str(input_path),
            "input_sha256": sha256_file(input_path),
            "raw_input_sha256": sha256_file(Path(sample["raw_input_path"])),
            "teacher_sha256": sha256_file(Path(sample["teacher_path"])),
            "target_review": "pending",
        }
        if target_path.exists() and not args.overwrite:
            record.update({"status": "skipped_existing", "target_sha256": sha256_file(target_path)})
            records["samples"][sample_id] = record
            _write_records(records_path, records)
            continue
        input_image = Image.open(input_path).convert("RGB")
        edge = edge_control(input_image)
        edge.save(edge_path, format="PNG", optimize=True)
        generator = torch.Generator(device=args.device).manual_seed(record["seed"])
        with torch.inference_mode():
            result = pipe(
                prompt=args.prompt,
                negative_prompt=args.negative_prompt,
                image=input_image,
                control_image=edge,
                strength=args.strength,
                num_inference_steps=args.steps,
                guidance_scale=args.guidance_scale,
                controlnet_conditioning_scale=args.control_scale,
                generator=generator,
                height=input_image.height,
                width=input_image.width,
            )
        target_path.parent.mkdir(parents=True, exist_ok=True)
        result.images[0].convert("RGB").save(target_path, format="PNG", optimize=True)
        record.update(
            {
                "status": "generated",
                "target_sha256": sha256_file(target_path),
                "control_canny_sha256": sha256_file(edge_path),
                "target_review": "pending",
            }
        )
        records["samples"][sample_id] = record
        records["completed_count"] = len(records["samples"])
        _write_records(records_path, records)
        print(json.dumps({"sample_id": sample_id, "status": record["status"], "target": str(target_path)}))

    records["status"] = "complete"
    records["completed_utc"] = datetime.now(timezone.utc).isoformat()
    records["generated_count"] = sum(item.get("status") == "generated" for item in records["samples"].values())
    records["skipped_count"] = sum(item.get("status") == "skipped_existing" for item in records["samples"].values())
    _write_records(records_path, records)
    print(
        json.dumps(
            {"status": records["status"], "records": str(records_path), "samples": len(records["samples"])},
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GEN target generation failed: {exc}", file=sys.stderr)
        raise
