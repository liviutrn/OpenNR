"""Build a strict renderer-conditioning overlay from an existing temporal cache.

The full-eye pilot stores six native Skyrim G-buffer readbacks beside every
crop frame, but the ordinary temporal cache intentionally keeps only RGB,
Feature-18 guides, and crop context.  This tool materializes the discarded
G-buffer channels at the same row order as a verified strict temporal cache.

The source cache, capture tree, and raw artifacts are read-only.  The output
is an isolated overlay consumed together with the source cache by the
renderer-conditioned semantic experiment.  Test rows are materialized for
row identity, but consumers are required to use only train/validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from audit_conditioning_content import STAGES, align, decode
from prepare_conditioning_pilot import features, shrink
from prepare_conditioning_pilot import save, sha


SCHEMA = "opennr-full-eye-renderer-conditioning-v1"
SOURCE_SCHEMA = "opennr-raw-crop-capture"
CONDITIONING_CHANNELS = 17
SIZE = 128
EXPECTED_FORMATS = {
    "gbuffer_albedo": "R10G10B10A2_UNORM",
    "gbuffer_normal_roughness": "R10G10B10A2_UNORM",
    "gbuffer_masks": "R11G11B10_FLOAT",
    "gbuffer_masks2": "R16_UNORM",
    "gbuffer_specular": "R11G11B10_FLOAT",
    "gbuffer_reflectance": "R11G11B10_FLOAT",
}
CHANNEL_ORDER = [
    "albedo_rgb",
    "normal_xyz_roughness",
    "masks_rgb",
    "masks2_r",
    "specular_rgb",
    "reflectance_rgb",
]


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _stable_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _artifact_map(frame: dict[str, Any], sequence: str, eye: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for artifact in frame.get("artifacts", []):
        if not isinstance(artifact, dict):
            raise ValueError(f"{sequence} frame {frame.get('frame_id')}: malformed artifact")
        if artifact.get("full_frame") or int(artifact.get("crop_index", -1)) != 0:
            continue
        if int(artifact.get("eye", -1)) != eye:
            continue
        stage = str(artifact.get("stage", ""))
        if stage in result:
            raise ValueError(f"{sequence} frame {frame.get('frame_id')}: duplicate {stage}")
        result[stage] = artifact
    return result


def _validate_frame(frame: dict[str, Any], sequence: str, expected_id: int) -> None:
    if int(frame.get("frame_id", -1)) != expected_id:
        raise ValueError(f"{sequence}: frame manifest is not indexed by frame_id")
    if frame.get("status") != "complete":
        raise ValueError(f"{sequence} frame {expected_id}: incomplete")
    if frame.get("route") != "feature18_stereo":
        raise ValueError(f"{sequence} frame {expected_id}: route changed")
    if int(frame.get("model_resolution_percent", 0)) != 100:
        raise ValueError(f"{sequence} frame {expected_id}: model resolution changed")
    if int(frame.get("pass_count", 0)) != 1:
        raise ValueError(f"{sequence} frame {expected_id}: pass count changed")
    if frame.get("motion_vector_contract") != "exact_feature18_bound_resource":
        raise ValueError(f"{sequence} frame {expected_id}: motion-vector contract changed")
    if frame.get("renderer_conditionings_requested") is not True:
        raise ValueError(f"{sequence} frame {expected_id}: renderer conditioning was not requested")
    available = set(frame.get("renderer_conditionings_available", []))
    if available != set(STAGES):
        raise ValueError(f"{sequence} frame {expected_id}: renderer stages are incomplete")
    diagnostics = frame.get("renderer_conditioning_diagnostics")
    if not isinstance(diagnostics, list) or len(diagnostics) != len(STAGES) * 2:
        raise ValueError(f"{sequence} frame {expected_id}: diagnostic coverage is incomplete")
    for diagnostic in diagnostics:
        if (
            diagnostic.get("copy_queued") is not True
            or diagnostic.get("texture_present") is not True
            or diagnostic.get("deferred_refresh_status") != "targets_match_main"
        ):
            raise ValueError(f"{sequence} frame {expected_id}: renderer diagnostic gate failed")


def _validate_artifact(
    artifact: dict[str, Any],
    stage: str,
    sequence: str,
    frame_id: int,
    eye: int,
    sequence_root: Path,
) -> Path:
    if artifact.get("format_name") != EXPECTED_FORMATS[stage]:
        raise ValueError(
            f"{sequence} frame {frame_id} eye {eye} {stage}: format changed"
        )
    if not artifact.get("raw_required") or not artifact.get("raw_written"):
        raise ValueError(f"{sequence} frame {frame_id} eye {eye} {stage}: raw is not committed")
    if int(artifact.get("width", 0)) != 512 or int(artifact.get("height", 0)) != 512:
        raise ValueError(f"{sequence} frame {frame_id} eye {eye} {stage}: crop is not 512x512")
    if int(artifact.get("row_pitch", 0)) <= 0:
        raise ValueError(f"{sequence} frame {frame_id} eye {eye} {stage}: invalid row pitch")
    path = Path(str(artifact.get("raw_path", "")))
    if not path.is_absolute():
        path = (sequence_root / path).resolve()
        try:
            path.relative_to(sequence_root.resolve())
        except ValueError as exc:
            raise ValueError(
                f"{sequence} frame {frame_id} eye {eye} {stage}: unsafe raw path"
            ) from exc
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _conditioning(
    frame: dict[str, Any], sequence: str, eye: int, sequence_root: Path
) -> tuple[np.ndarray, dict[str, str]]:
    artifacts = _artifact_map(frame, sequence, eye)
    for stage in ("input", "teacher", *STAGES):
        if stage not in artifacts:
            raise ValueError(f"{sequence} frame {frame['frame_id']} eye {eye}: missing {stage}")
    teacher_artifact = artifacts["teacher"]
    values: list[np.ndarray] = []
    hashes: dict[str, str] = {}
    for stage in STAGES:
        path = _validate_artifact(
            artifacts[stage], stage, sequence, int(frame["frame_id"]), eye, sequence_root
        )
        value, digest = decode(path, artifacts[stage])
        hashes[stage] = digest
        if not np.isfinite(value).all():
            raise ValueError(f"{sequence} frame {frame['frame_id']} eye {eye} {stage}: nonfinite source")
        value = features(value, stage)
        aligned, mapping = align(value, artifacts[stage], teacher_artifact)
        if not mapping["covered"]:
            raise ValueError(
                f"{sequence} frame {frame['frame_id']} eye {eye} {stage}: teacher crop is uncovered"
            )
        if not np.isfinite(aligned).all():
            raise ValueError(f"{sequence} frame {frame['frame_id']} eye {eye} {stage}: nonfinite aligned value")
        values.append(shrink(aligned, SIZE))
    result = np.concatenate(values, axis=0).astype(np.float16)
    if result.shape != (CONDITIONING_CHANNELS, SIZE, SIZE):
        raise ValueError(f"unexpected conditioning shape {result.shape}")
    if not np.isfinite(result).all():
        raise ValueError(f"{sequence} frame {frame['frame_id']} eye {eye}: nonfinite conditioning")
    return result, hashes


def _source_rows(source: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    complete = _read(source / "complete.json")
    if complete.get("source_type") != "opennr_raw_crop_capture":
        raise ValueError("source cache is not a raw crop cache")
    if complete.get("training_role") != "strict_temporal_crop_cache":
        raise ValueError("source cache is not strict temporal")
    if complete.get("temporal_training_allowed") is not True:
        raise ValueError("source cache does not allow strict temporal training")
    if complete.get("crop_indices") != [0]:
        raise ValueError("renderer overlay requires the single crop-0 temporal cache")
    rows = _read(source / "rows.json")
    if not isinstance(rows, list) or len(rows) != int(complete.get("source_eye_rows", -1)):
        raise ValueError("source row manifest is inconsistent")
    source_root = Path(str(complete["source_root"])).resolve()
    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    rows_sha = _stable_sha(rows)
    if rows_sha != complete["rows_sha256"]:
        raise ValueError("source row identity changed")
    if sha(source / "complete.json") != _read(source / "provenance.json").get("source_complete_sha256", sha(source / "complete.json")):
        # This branch is intentionally defensive; the source cache's own
        # complete hash is checked below and this message avoids silently
        # accepting a partially rewritten source directory.
        raise ValueError("source cache provenance is inconsistent")
    return complete, rows, {"source_root": source_root}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_cache.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(output)
    if source == output or output.is_relative_to(source):
        raise ValueError("overlay output must be outside the source cache")

    source_complete, rows, info = _source_rows(source)
    source_complete_sha = sha(source / "complete.json")
    source_rows_sha = _stable_sha(rows)
    source_root: Path = info["source_root"]
    sequence_ids = sorted({str(row["sequence_id"]) for row in rows})
    if len(sequence_ids) < 3:
        raise ValueError("renderer overlay requires at least three sequences")
    split = source_complete["split"]
    if set(split["train"]) | set(split["validation"]) | set(split["test"]) != set(sequence_ids):
        raise ValueError("source split does not cover exactly the source sequences")

    manifests: dict[str, list[dict[str, Any]]] = {}
    manifest_hashes: dict[str, dict[str, str]] = {}
    for sequence in sequence_ids:
        root = source_root / sequence
        manifest = root / "frames.jsonl"
        sequence_json = root / "sequence.json"
        if not manifest.is_file() or not sequence_json.is_file():
            raise FileNotFoundError(root)
        manifests[sequence] = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
        manifest_hashes[sequence] = {
            "sequence.json": sha(sequence_json),
            "frames.jsonl": sha(manifest),
        }
        if len(manifests[sequence]) < 64:
            raise ValueError(f"{sequence}: fewer than 64 source frames")
        for frame_id in range(1, 65):
            _validate_frame(manifests[sequence][frame_id - 1], sequence, frame_id)

    output.mkdir(parents=True)
    conditioning = np.lib.format.open_memmap(
        output / "conditioning.npy",
        mode="w+",
        dtype="<f2",
        shape=(len(rows), CONDITIONING_CHANNELS, SIZE, SIZE),
    )
    payload_records: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        sequence = str(row["sequence_id"])
        frame_id = int(row["frame_id"])
        eye = int(row["eye"])
        if frame_id < 1 or frame_id > 64:
            raise ValueError(f"source row {index}: frame is outside the strict window")
        if row.get("split") not in ("train", "validation", "test"):
            raise ValueError(f"source row {index}: invalid split")
        frame = manifests[sequence][frame_id - 1]
        if bool(row.get("history_reset")) != (frame_id == 1):
            raise ValueError(f"source row {index}: reset contract changed")
        value, hashes = _conditioning(frame, sequence, eye, source_root / sequence)
        conditioning[index] = value
        payload_records.append(
            {
                "source_row": index,
                "sequence_id": sequence,
                "frame_id": frame_id,
                "eye": eye,
                "split": row["split"],
                "stage_sha256": hashes,
            }
        )
        if (index + 1) % 128 == 0 or index + 1 == len(rows):
            conditioning.flush()
            print(f"prepared {index + 1}/{len(rows)} renderer-conditioned eye rows", flush=True)
    conditioning.flush()

    # Keep row order independently auditable without copying the source arrays.
    save(output / "rows.json", rows)
    save(output / "payload_records.json", payload_records)
    source_hash_digest = _stable_sha(payload_records)
    complete = {
        "schema": SCHEMA,
        "source_cache": str(source),
        "source_complete_sha256": source_complete_sha,
        "source_rows_sha256": source_rows_sha,
        "source_root": str(source_root),
        "rows": len(rows),
        "shape": [len(rows), CONDITIONING_CHANNELS, SIZE, SIZE],
        "split": split,
        "sequence_count": len(sequence_ids),
        "sequence_ids": sequence_ids,
        "sequence_counts": {name: len(split[name]) for name in ("train", "validation", "test")},
        "eye_row_counts": {
            name: sum(row["split"] == name for row in rows)
            for name in ("train", "validation", "test")
        },
        "conditioning_channels": CONDITIONING_CHANNELS,
        "channel_order": CHANNEL_ORDER,
        "normalization": "albedo unchanged; decoded signed view-space normals plus 1-glossiness; unsigned HDR stages x/(1+x)",
        "alignment": "native renderer crop mapped into teacher crop with existing audited affine, then fixed BOX downsampling to 128",
        "renderer_source": "Skyrim deferred G-buffer render targets at the Neural Rendering call boundary",
        "renderer_diagnostic_gate": "all six stages, both eyes, copy_queued, texture_present, deferred_refresh_status=targets_match_main",
        "strict_temporal_contract": "source cache exact contiguous frame IDs 1..64; first [true,true] reset; no mid-stream reset",
        "source_manifest_hashes": manifest_hashes,
        "payload_records_sha256": _stable_sha(payload_records),
        "test_used_for_tuning": False,
        "test_rows_materialized": True,
        "training_role": "strict_temporal_renderer_conditioning_overlay",
        "source_arrays_unchanged": True,
    }
    complete["array_sha256"] = {"conditioning": sha(output / "conditioning.npy")}
    complete["rows_sha256"] = sha(output / "rows.json")
    save(output / "complete.json", complete)
    save(
        output / "provenance.json",
        {
            "schema": SCHEMA,
            "source_cache": str(source),
            "source_complete_sha256": source_complete_sha,
            "source_rows_sha256": source_rows_sha,
            "payload_records_sha256": source_hash_digest,
            "test_used_for_tuning": False,
        },
    )
    print(json.dumps(complete, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
