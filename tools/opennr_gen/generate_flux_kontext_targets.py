"""Generate offline FLUX.1 Kontext image-edit targets for a bounded GEN tranche."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

try:
    from generate_sdxl_targets import canonical_sha256, sha256_file, verify_manifest
except ImportError:  # pragma: no cover - supports package-style imports
    from .generate_sdxl_targets import canonical_sha256, sha256_file, verify_manifest


MODEL_ID = "black-forest-labs/FLUX.1-Kontext-dev"
CONVERSION_ID = "AlekseyCalvin/Flux_Kontext_Dev_fp8_scaled_diffusers"
CONVERSION_REVISION = "652a3172b715103503a27193c3fed5d9cb5bc29c"
ORIGINAL_MODEL_REVISION_OBSERVED = "24e9dedc4ef646698dc8eb4e18ae2cec3c9fea0d"

DEFAULT_PROMPT = (
    "Improve this Skyrim screenshot with subtle photorealistic surface detail. "
    "Preserve the exact camera, crop, composition, geometry, objects, pose, "
    "face, hair, armor, cloth, stone, wood, foliage, colors, lighting, "
    "shadows, and highlights. Add only natural microtexture and local "
    "contrast. Leave all else unchanged."
)

DEFAULT_NEGATIVE_PROMPT = (
    "Do not change the camera, crop, composition, geometry, objects, pose, "
    "face, identity, hair, armor, cloth, stone, wood, foliage, colors, "
    "lighting, shadows, or highlights. Do not add or remove anything."
)


def _load_pipeline(model_dir: Path, device: str):
    import torch
    import diffusers
    from diffusers import FluxKontextPipeline

    load_kwargs: dict[str, Any] = {
        "use_safetensors": True,
        "local_files_only": True,
        "low_cpu_mem_usage": True,
    }
    # The public conversion was authored against Diffusers main.  The pinned
    # 0.35.2 environment uses torch_dtype, while newer main snapshots expose
    # dtype.  Keep both paths explicit so the recorded route identifies the
    # actual loader contract used for a probe.
    if diffusers.__version__.startswith("0.35."):
        load_kwargs["torch_dtype"] = torch.bfloat16
    else:
        load_kwargs["dtype"] = torch.bfloat16
    pipe = FluxKontextPipeline.from_pretrained(model_dir, **load_kwargs)
    if device == "cuda":
        pipe.enable_model_cpu_offload()
        if hasattr(pipe, "enable_vae_slicing"):
            pipe.enable_vae_slicing()
        elif hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()
        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
    return pipe, diffusers.__version__


def _selected_samples(manifest: dict[str, Any], only: set[str] | None) -> list[dict[str, Any]]:
    samples = manifest["samples"]
    if only:
        samples = [sample for sample in samples if sample["sample_id"] in only]
        missing = sorted(only - {sample["sample_id"] for sample in samples})
        if missing:
            raise ValueError(f"unknown sample IDs: {missing}")
    return samples


def _write_records(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--coverage-review", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--guidance-scale", type=float, default=2.5)
    parser.add_argument("--true-cfg-scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=92110)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    parser.add_argument("--only", help="comma-separated sample IDs for a bounded probe")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.steps < 1 or args.steps > 40:
        raise ValueError("steps must stay in [1, 40] for this bounded probe")
    if args.guidance_scale < 0.0 or args.guidance_scale > 10.0:
        raise ValueError("guidance scale must stay in [0, 10]")
    if args.true_cfg_scale < 1.0 or args.true_cfg_scale > 3.0:
        raise ValueError("true CFG scale must stay in [1, 3]")

    manifest_path = args.manifest.resolve()
    coverage_path = args.coverage_review.resolve()
    model_dir = args.model_dir.resolve()
    output = args.output.resolve()
    manifest, _ = verify_manifest(manifest_path, coverage_path)
    if not model_dir.is_dir():
        raise FileNotFoundError(model_dir)
    if not (model_dir / "model_index.json").is_file():
        raise FileNotFoundError(model_dir / "model_index.json")
    if args.device == "cuda":
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")

    only = set(filter(None, (args.only or "").split(",")))
    samples = _selected_samples(manifest, only or None)
    output.mkdir(parents=True, exist_ok=True)
    records_path = output / "target_records.json"
    coverage_review_sha256 = sha256_file(coverage_path)
    records: dict[str, Any] = {
        "schema": "opennr-gen-static-target-records-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "status": "dry_run" if args.dry_run else "running",
        "manifest": str(manifest_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "coverage_review": str(coverage_path),
        "coverage_review_sha256": coverage_review_sha256,
        "source_cache": manifest["source_cache"],
        "enhancer": {
            "family": "FLUX.1 Kontext image-to-image",
            "model_id": MODEL_ID,
            "conversion_id": CONVERSION_ID,
            "conversion_revision": CONVERSION_REVISION,
            "original_model_revision_observed": ORIGINAL_MODEL_REVISION_OBSERVED,
            "provenance_confidence": "public FP8 conversion; source repo declares FLUX.1-Kontext-dev lineage",
            "license": "flux-1-dev-non-commercial-license",
            "model_dir": str(model_dir),
        },
        "inference": {
            "device": args.device,
            "steps": args.steps,
            "guidance_scale": args.guidance_scale,
            "true_cfg_scale": args.true_cfg_scale,
            "seed_base": args.seed,
            "height": 512,
            "width": 512,
            "auto_resize": False,
            "prompt": args.prompt,
            "negative_prompt": args.negative_prompt,
            "image_role": "dlss5_teacher",
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
        "completed_count": 0,
        "generated_count": 0,
        "skipped_count": 0,
    }
    if only and records_path.exists():
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
        records["created_utc"] = existing.get("created_utc", records["created_utc"])
        records["review_gate"] = existing.get("review_gate", records["review_gate"])
        records["enhancer"].update(existing.get("enhancer", {}))
        records["samples"] = existing.get("samples", {})
        records["completed_count"] = len(records["samples"])
        records["generated_count"] = sum(
            item.get("status") == "generated" for item in records["samples"].values()
        )
        records["skipped_count"] = sum(
            item.get("status") == "skipped_existing" for item in records["samples"].values()
        )
    if args.dry_run:
        for sample in samples:
            records["samples"][sample["sample_id"]] = {
                "sample_id": sample["sample_id"],
                "status": "dry_run",
                "raw_input_sha256": sha256_file(Path(sample["raw_input_path"])),
                "teacher_sha256": sha256_file(Path(sample["teacher_path"])),
                "target_path": sample["enhanced_target_path"],
            }
        records["completed_count"] = len(records["samples"])
        _write_records(records_path, records)
        print(json.dumps({"status": "dry_run", "records": str(records_path), "samples": len(samples)}, indent=2))
        return

    pipe, diffusers_version = _load_pipeline(model_dir, args.device)
    records["enhancer"]["diffusers_version"] = diffusers_version
    _write_records(records_path, records)
    import torch

    generator_device = args.device
    manifest_positions = {
        sample["sample_id"]: index for index, sample in enumerate(manifest["samples"])
    }
    for sample in samples:
        sample_id = sample["sample_id"]
        target_path = Path(sample["enhanced_target_path"])
        prior = records["samples"].get(sample_id)
        if target_path.exists() and not args.overwrite:
            records["samples"][sample_id] = {
                "sample_id": sample_id,
                "status": "skipped_existing",
                "target_path": str(target_path),
                "target_sha256": sha256_file(target_path),
                "raw_input_sha256": sha256_file(Path(sample["raw_input_path"])),
                "teacher_sha256": sha256_file(Path(sample["teacher_path"])),
            }
            records["completed_count"] = len(records["samples"])
            records["generated_count"] = sum(
                item.get("status") == "generated" for item in records["samples"].values()
            )
            records["skipped_count"] = sum(
                item.get("status") == "skipped_existing" for item in records["samples"].values()
            )
            _write_records(records_path, records)
            print(json.dumps({"sample_id": sample_id, "status": "skipped_existing"}))
            continue

        target_path.parent.mkdir(parents=True, exist_ok=True)
        seed = args.seed + manifest_positions[sample_id]
        with Image.open(sample["teacher_path"]) as teacher:
            image = teacher.convert("RGB")
        kwargs: dict[str, Any] = {
            "image": image,
            "prompt": args.prompt,
            "height": 512,
            "width": 512,
            "max_area": 512 * 512,
            "_auto_resize": False,
            "num_inference_steps": args.steps,
            "guidance_scale": args.guidance_scale,
            "generator": torch.Generator(device=generator_device).manual_seed(seed),
            "output_type": "pil",
        }
        if args.true_cfg_scale > 1.0:
            kwargs["true_cfg_scale"] = args.true_cfg_scale
            kwargs["negative_prompt"] = args.negative_prompt
        result = pipe(**kwargs).images[0].convert("RGB")
        result.save(target_path, format="PNG", optimize=True)
        records["samples"][sample_id] = {
            "sample_id": sample_id,
            "pair_id": sample["pair_id"],
            "eye": sample["eye"],
            "status": "generated",
            "seed": seed,
            "steps": args.steps,
            "guidance_scale": args.guidance_scale,
            "true_cfg_scale": args.true_cfg_scale,
            "target_path": str(target_path),
            "target_sha256": sha256_file(target_path),
            "raw_input_sha256": sha256_file(Path(sample["raw_input_path"])),
            "teacher_sha256": sha256_file(Path(sample["teacher_path"])),
        }
        records["completed_count"] = len(records["samples"])
        records["generated_count"] = sum(
            item.get("status") == "generated" for item in records["samples"].values()
        )
        records["skipped_count"] = sum(
            item.get("status") == "skipped_existing" for item in records["samples"].values()
        )
        _write_records(records_path, records)
        print(json.dumps({"sample_id": sample_id, "status": "generated", "target": str(target_path)}))

    records["status"] = "complete"
    records["completed_utc"] = datetime.now(timezone.utc).isoformat()
    _write_records(records_path, records)
    print(
        json.dumps(
            {"status": "complete", "records": str(records_path), "samples": len(records["samples"])},
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FLUX target generation failed: {exc}", file=sys.stderr)
        raise
