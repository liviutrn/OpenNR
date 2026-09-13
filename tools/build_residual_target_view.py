"""Build an immutable target-residual view over existing OpenNR RGB caches.

This is a research-data preparation tool.  It never edits a source cache and
never changes the protected model.  For every source row it preserves the
original row metadata and adds the explicit target definition::

    B = rgb[:, 0] / 255          # pre-DLSS5/base RGB
    T = rgb[:, 1] / 255          # teacher RGB
    R = T - B = (rgb[:, 1]-rgb[:, 0]) / 255

The residual is stored as an exact int16 byte difference rather than a
float16 approximation.  The statistics pass runs before that derived file is
materialized and writes signed and absolute histograms, including p99 and
p99.9 values, so a later training run cannot silently change the target tail.

The output is a new directory.  Existing directories are refused rather than
overwritten.  The source cache roots are intentionally supplied explicitly;
this prevents an old aligned overlay with a missing RGB source from being
mistaken for a complete corpus.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time
from typing import Any

import numpy as np


SPLITS = ("train", "validation", "test")
RGB_NAME = "rgb.npy"
GUIDES_NAME = "guides.npy"
CONTEXT_NAME = "context.npy"


def _json_default(value: Any):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256_file(path: Path, chunk_bytes: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _stable_json_sha(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=_json_default
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_source(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must be LABEL=PATH")
    label, raw_path = value.split("=", 1)
    label = label.strip()
    if not label or not raw_path.strip():
        raise argparse.ArgumentTypeError("source must be LABEL=PATH")
    if any(character in label for character in "\\/:*?\"<>|"):
        raise argparse.ArgumentTypeError(f"invalid source label: {label!r}")
    return label, Path(raw_path).expanduser().resolve()


def _first_present(row: dict[str, Any], names: tuple[str, ...]):
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return None


def _validate_streams(rows: list[dict[str, Any]], root: Path, label: str) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[tuple[int, int]]] = defaultdict(list)
    sequence_splits: dict[str, set[str]] = defaultdict(set)
    for index, row in enumerate(rows):
        split = row.get("split")
        if split not in SPLITS:
            raise ValueError(f"{label}: row {index} has unsupported split {split!r}")
        sequence = str(row.get("sequence_id"))
        eye = int(row.get("eye"))
        frame = int(row.get("frame_id"))
        grouped[(sequence, eye)].append((frame, index))
        sequence_splits[sequence].add(str(split))
    mixed = {key: sorted(value) for key, value in sequence_splits.items() if len(value) != 1}
    if mixed:
        raise ValueError(f"{label}: sequences span multiple splits: {mixed}")

    stream_summary = {split: 0 for split in SPLITS}
    sequence_summary = {split: set() for split in SPLITS}
    for (sequence, eye), values in grouped.items():
        values.sort(key=lambda item: item[0])
        frames = [frame for frame, _ in values]
        expected = list(range(1, len(frames) + 1))
        if frames != expected:
            raise ValueError(
                f"{label}: non-contiguous stream {(sequence, eye)}; "
                f"got {frames[:4]}...{frames[-4:]}"
            )
        if len(frames) != 64:
            raise ValueError(
                f"{label}: expected 64 frames in {(sequence, eye)}, found {len(frames)}"
            )
        first = rows[values[0][1]]
        if first.get("history_reset") is not True:
            raise ValueError(f"{label}: {(sequence, eye)} does not start with history_reset=true")
        pair = first.get("history_reset_pair")
        if pair is not None and list(pair) != [True, True]:
            raise ValueError(f"{label}: {(sequence, eye)} has invalid history_reset_pair={pair!r}")
        split = str(first["split"])
        stream_summary[split] += 1
        sequence_summary[split].add(sequence)

    return {
        "streams": {split: int(value) for split, value in stream_summary.items()},
        "sequences": {split: sorted(value) for split, value in sequence_summary.items()},
        "sequence_counts": {split: len(value) for split, value in sequence_summary.items()},
    }


class Source:
    def __init__(self, label: str, root: Path, hash_arrays: bool):
        self.label = label
        self.root = root
        if not root.is_dir():
            raise FileNotFoundError(f"{label}: source root does not exist: {root}")
        required = [root / "complete.json", root / "rows.json", root / RGB_NAME,
                    root / GUIDES_NAME, root / CONTEXT_NAME]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                f"{label}: source is incomplete; missing {missing}. "
                "An aligned overlay without its RGB source is not usable here."
            )
        self.complete_path = root / "complete.json"
        self.rows_path = root / "rows.json"
        self.complete = json.loads(self.complete_path.read_text(encoding="utf-8"))
        self.rows = json.loads(self.rows_path.read_text(encoding="utf-8"))
        self.rgb = np.load(root / RGB_NAME, mmap_mode="r")
        self.guides = np.load(root / GUIDES_NAME, mmap_mode="r")
        self.context = np.load(root / CONTEXT_NAME, mmap_mode="r")
        if self.rgb.ndim != 5 or self.rgb.shape[1:3] != (2, 3):
            raise ValueError(f"{label}: expected RGB shape [N,2,3,H,W], got {self.rgb.shape}")
        if self.rgb.dtype != np.uint8:
            raise ValueError(f"{label}: expected uint8 RGB, got {self.rgb.dtype}")
        if self.rgb.shape[0] != len(self.rows):
            raise ValueError(f"{label}: RGB rows do not match rows.json")
        if self.guides.shape[0] != len(self.rows) or self.context.shape[0] != len(self.rows):
            raise ValueError(f"{label}: guide/context rows do not match rows.json")
        if self.rgb.shape[-2:] != (512, 512):
            raise ValueError(f"{label}: expected 512x512 RGB rows, got {self.rgb.shape[-2:]}")
        if self.guides.ndim != 4 or self.guides.shape[1] != 5:
            raise ValueError(f"{label}: expected [N,5,H,W] guides, got {self.guides.shape}")
        if self.context.ndim != 4 or self.context.shape[1] != 8:
            raise ValueError(f"{label}: expected [N,8,H,W] context, got {self.context.shape}")
        if self.complete.get("test_used_for_tuning") is True:
            raise ValueError(f"{label}: source is marked test_used_for_tuning")
        self.streams = _validate_streams(self.rows, root, label)
        self.complete_sha256 = _sha256_file(self.complete_path)
        self.rows_sha256 = _sha256_file(self.rows_path)
        self.hash_arrays = hash_arrays
        self.array_hashes = {
            "rgb": hashlib.sha256() if hash_arrays else None,
            "guides": hashlib.sha256() if hash_arrays else None,
            "context": hashlib.sha256() if hash_arrays else None,
        }
        self.group_keys: dict[str, str] = {}
        for row in self.rows:
            face = _first_present(row, ("face_label", "face", "has_face", "face_present"))
            high = _first_present(row, ("high_effect_label", "high_effect", "is_high_effect"))
            self.group_keys.setdefault(
                "face_available" if face is not None else "face_unavailable", ""
            )
            self.group_keys.setdefault(
                "high_effect_available" if high is not None else "high_effect_unavailable", ""
            )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def update_hashes(self, rgb: np.ndarray, guides: np.ndarray, context: np.ndarray) -> None:
        if not self.hash_arrays:
            return
        self.array_hashes["rgb"].update(np.ascontiguousarray(rgb).tobytes())
        self.array_hashes["guides"].update(np.ascontiguousarray(guides).tobytes())
        self.array_hashes["context"].update(np.ascontiguousarray(context).tobytes())

    def finish_hashes(self) -> dict[str, str] | None:
        if not self.hash_arrays:
            return None
        return {key: value.hexdigest() for key, value in self.array_hashes.items()}


def _new_histogram_map():
    return defaultdict(lambda: np.zeros((3, 511), dtype=np.int64))


def _update_histograms(
    histograms: defaultdict[str, np.ndarray],
    key: str,
    difference: np.ndarray,
) -> None:
    destination = histograms[key]
    for channel in range(3):
        values = difference[:, channel].reshape(-1).astype(np.int16, copy=False) + 255
        destination[channel] += np.bincount(values, minlength=511)


def _percentile(counts: np.ndarray, values: np.ndarray, probability: float) -> float | None:
    total = int(counts.sum())
    if total == 0:
        return None
    rank = probability * (total - 1)
    position = int(np.searchsorted(np.cumsum(counts), rank + 1, side="left"))
    position = min(max(position, 0), len(values) - 1)
    return float(values[position])


def _histogram_summary(histograms: dict[str, np.ndarray], key: str) -> dict[str, Any]:
    channels = histograms[key]
    signed_values = np.arange(-255, 256, dtype=np.float64) / 255.0
    absolute_values = np.arange(256, dtype=np.float64) / 255.0
    channel_summaries = []
    for channel in range(3):
        signed = channels[channel]
        absolute = np.bincount(
            np.abs(np.arange(-255, 256, dtype=np.int16)), weights=signed, minlength=256
        ).astype(np.int64)
        total = int(signed.sum())
        mean = float(np.dot(signed, signed_values) / total) if total else None
        second = float(np.dot(signed, signed_values * signed_values) / total) if total else None
        std = float(max(0.0, second - mean * mean) ** 0.5) if total and mean is not None else None
        channel_summaries.append(
            {
                "channel": channel,
                "count": total,
                "min": _percentile(signed, signed_values, 0.0),
                "max": _percentile(signed, signed_values, 1.0),
                "mean": mean,
                "std": std,
                "rms": float(max(0.0, second) ** 0.5) if second is not None else None,
                "positive_fraction": float(signed[256:].sum() / total) if total else None,
                "negative_fraction": float(signed[:255].sum() / total) if total else None,
                "zero_fraction": float(signed[255] / total) if total else None,
                "signed_percentiles": {
                    "p50": _percentile(signed, signed_values, 0.50),
                    "p99": _percentile(signed, signed_values, 0.99),
                    "p99_9": _percentile(signed, signed_values, 0.999),
                },
                "absolute_percentiles": {
                    "p50": _percentile(absolute, absolute_values, 0.50),
                    "p99": _percentile(absolute, absolute_values, 0.99),
                    "p99_9": _percentile(absolute, absolute_values, 0.999),
                },
                "signed_histogram_counts": signed.tolist(),
                "absolute_histogram_counts": absolute.tolist(),
            }
        )

    aggregate = channels.sum(axis=0)
    absolute_aggregate = np.bincount(
        np.abs(np.arange(-255, 256, dtype=np.int16)), weights=aggregate, minlength=256
    ).astype(np.int64)
    total = int(aggregate.sum())
    mean = float(np.dot(aggregate, signed_values) / total) if total else None
    second = float(np.dot(aggregate, signed_values * signed_values) / total) if total else None
    return {
        "group": key,
        "count": total,
        "channels": channel_summaries,
        "aggregate": {
            "mean": mean,
            "std": float(max(0.0, second - mean * mean) ** 0.5)
            if total and mean is not None and second is not None
            else None,
            "rms": float(max(0.0, second) ** 0.5) if second is not None else None,
            "signed_percentiles": {
                "p50": _percentile(aggregate, signed_values, 0.50),
                "p99": _percentile(aggregate, signed_values, 0.99),
                "p99_9": _percentile(aggregate, signed_values, 0.999),
            },
            "absolute_percentiles": {
                "p50": _percentile(absolute_aggregate, absolute_values, 0.50),
                "p99": _percentile(absolute_aggregate, absolute_values, 0.99),
                "p99_9": _percentile(absolute_aggregate, absolute_values, 0.999),
            },
            "signed_histogram_counts": aggregate.tolist(),
            "absolute_histogram_counts": absolute_aggregate.tolist(),
        },
        "histogram_definition": {
            "signed_values": signed_values.tolist(),
            "absolute_values": absolute_values.tolist(),
            "percentile_method": "exact discrete uint8 difference order statistic",
        },
    }


def _build_rows(sources: list[Source]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    offsets: dict[str, int] = {}
    offset = 0
    for source in sources:
        offsets[source.label] = offset
        for source_index, original in enumerate(source.rows):
            row = dict(original)
            face = _first_present(original, ("face_label", "face", "has_face", "face_present"))
            high = _first_present(original, ("high_effect_label", "high_effect", "is_high_effect"))
            row.update(
                {
                    "view_index": offset + source_index,
                    "source_label": source.label,
                    "source_root": str(source.root),
                    "source_row_index": source_index,
                    "cohort_label": source.label,
                    "face_label": face,
                    "high_effect_label": high,
                    "residual_target": {
                        "base": "rgb[:,0]/255",
                        "teacher": "rgb[:,1]/255",
                        "residual": "(rgb[:,1]-rgb[:,0])/255",
                    },
                }
            )
            rows.append(row)
        offset += source.row_count
    return rows, offsets


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        action="append",
        type=_parse_source,
        required=True,
        help="immutable source cache as LABEL=PATH; repeat for multiple cohorts",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chunk-rows", type=int, default=16)
    parser.add_argument(
        "--hash-arrays",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="hash source arrays while doing the statistics pass (default: enabled)",
    )
    args = parser.parse_args()
    if args.chunk_rows < 1:
        raise ValueError("chunk-rows must be positive")
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Refusing to overwrite non-empty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    labels = [label for label, _ in args.source]
    if len(set(labels)) != len(labels):
        raise ValueError("source labels must be unique")

    started = time.time()
    sources = [Source(label, root, args.hash_arrays) for label, root in args.source]
    rows, offsets = _build_rows(sources)
    height, width = sources[0].rgb.shape[-2:]
    for source in sources[1:]:
        if source.rgb.shape[-2:] != (height, width):
            raise ValueError("all source RGB arrays must have the same spatial shape")

    histograms = _new_histogram_map()
    source_info: list[dict[str, Any]] = []
    label_availability: dict[str, dict[str, int]] = {}
    total_rows = 0
    print(f"preflight: {len(sources)} source caches, {len(rows)} eye rows", flush=True)
    for source_index, source in enumerate(sources):
        availability = {"face_label_present": 0, "high_effect_label_present": 0}
        for row in source.rows:
            if _first_present(row, ("face_label", "face", "has_face", "face_present")) is not None:
                availability["face_label_present"] += 1
            if _first_present(row, ("high_effect_label", "high_effect", "is_high_effect")) is not None:
                availability["high_effect_label_present"] += 1
        label_availability[source.label] = {
            **availability,
            "rows": source.row_count,
        }
        for start in range(0, source.row_count, args.chunk_rows):
            end = min(source.row_count, start + args.chunk_rows)
            rgb = np.asarray(source.rgb[start:end], dtype=np.uint8)
            guides = np.asarray(source.guides[start:end])
            context = np.asarray(source.context[start:end])
            source.update_hashes(rgb, guides, context)
            difference = rgb[:, 1].astype(np.int16) - rgb[:, 0].astype(np.int16)
            _update_histograms(histograms, "global", difference)
            for split in SPLITS:
                selected = np.asarray(
                    [row.get("split") == split for row in source.rows[start:end]], dtype=bool
                )
                if selected.any():
                    _update_histograms(
                        histograms, f"split:{split}", difference[selected]
                    )
            _update_histograms(histograms, f"cohort:{source.label}", difference)
            total_rows += end - start
            if end == source.row_count or end % max(args.chunk_rows * 64, 256) == 0:
                print(
                    f"stats {source_index + 1}/{len(sources)} {source.label} "
                    f"{end}/{source.row_count} rows",
                    flush=True,
                )
        source_info.append(
            {
                "label": source.label,
                "root": str(source.root),
                "complete_sha256": source.complete_sha256,
                "rows_sha256": source.rows_sha256,
                "rows": source.row_count,
                "rgb_shape": list(source.rgb.shape),
                "guides_shape": list(source.guides.shape),
                "context_shape": list(source.context.shape),
                "rgb_dtype": str(source.rgb.dtype),
                "guides_dtype": str(source.guides.dtype),
                "context_dtype": str(source.context.dtype),
                "array_sha256": source.finish_hashes(),
                "strict_streams": source.streams,
                "complete_schema": source.complete.get("schema"),
            }
        )

    stats = {
        "schema": "opennr-residual-target-stats-v1",
        "created_utc_epoch": time.time(),
        "target": {
            "base": "B = uint8 rgb[:,0] / 255",
            "teacher": "T = uint8 rgb[:,1] / 255",
            "residual": "R = T - B = (uint8 rgb[:,1] - uint8 rgb[:,0]) / 255",
            "stored_difference": "exact int16 uint8 difference; divide by 255 at training/evaluation",
            "clipping": "none during target construction",
        },
        "rows": total_rows,
        "groups": {
            key: _histogram_summary(histograms, key) for key in sorted(histograms)
        },
        "source_label_availability": label_availability,
        "note": (
            "Face and high-effect fields are preserved when present. A missing field is recorded as null; "
            "no detector or target-dependent label was invented by this tool."
        ),
    }
    # This file is intentionally written before residual_i16.npy.
    _write_json(output / "residual_stats.json", stats)
    global_tail = stats["groups"]["global"]["aggregate"]
    print(
        "RESIDUAL_STATS_PRE_MATERIALIZATION "
        + json.dumps(
            {
                "rows": total_rows,
                "absolute_p99": global_tail["absolute_percentiles"]["p99"],
                "absolute_p99_9": global_tail["absolute_percentiles"]["p99_9"],
                "signed_p99": global_tail["signed_percentiles"]["p99"],
                "signed_p99_9": global_tail["signed_percentiles"]["p99_9"],
            },
            sort_keys=True,
        ),
        flush=True,
    )

    differences_path = output / "residual_i16.npy"
    differences = np.lib.format.open_memmap(
        differences_path,
        mode="w+",
        dtype="<i2",
        shape=(len(rows), 3, height, width),
    )
    offset = 0
    for source_index, source in enumerate(sources):
        for start in range(0, source.row_count, args.chunk_rows):
            end = min(source.row_count, start + args.chunk_rows)
            rgb = np.asarray(source.rgb[start:end], dtype=np.uint8)
            differences[offset + start : offset + end] = (
                rgb[:, 1].astype(np.int16) - rgb[:, 0].astype(np.int16)
            )
        offset += source.row_count
        print(
            f"materialized {source_index + 1}/{len(sources)} {source.label} "
            f"({source.row_count} rows)",
            flush=True,
        )
    differences.flush()
    del differences

    rows_sha = _stable_json_sha(rows)
    _write_json(output / "rows.json", rows)
    manifest = {
        "schema": "opennr-residual-target-view-v1",
        "created_utc_epoch": time.time(),
        "output": str(output),
        "target_definition": {
            "B": "source rgb.npy[:,0].astype(float32)/255",
            "T": "source rgb.npy[:,1].astype(float32)/255",
            "R": "T-B",
            "storage": "residual_i16.npy contains exact uint8 T-B in [-255,255]; normalize by 255",
            "teacher_target_is_not_recomputed": True,
            "hdr_or_tone_transform": "none",
        },
        "rows": len(rows),
        "spatial_shape": [height, width],
        "source_count": len(sources),
        "sources": source_info,
        "source_offsets": offsets,
        "split_counts": {
            split: sum(row.get("split") == split for row in rows) for split in SPLITS
        },
        "split_sequence_counts": {
            split: len({(row["source_label"], row["sequence_id"]) for row in rows if row.get("split") == split})
            for split in SPLITS
        },
        "rows_sha256": rows_sha,
        "residual_file": {
            "path": str(differences_path),
            "dtype": "int16 little-endian",
            "shape": [len(rows), 3, height, width],
            "sha256": _sha256_file(differences_path),
        },
        "stats_file": {
            "path": str((output / "residual_stats.json").resolve()),
            "sha256": _sha256_file(output / "residual_stats.json"),
            "computed_before_residual_materialization": True,
        },
        "label_contract": {
            "cohort_label": "explicit source label supplied on the command line",
            "face_label": "preserved from row when present, otherwise null/unavailable",
            "high_effect_label": "preserved from row when present, otherwise null/unavailable",
            "target_dependent_filtering": False,
        },
        "legacy_provenance_boundary": {
            "included_sources_are_not_called_the_original_six_cohort_set": True,
            "missing_legacy_labels_must_remain_unavailable": True,
        },
        "test_used_for_tuning": False,
        "build_seconds": time.time() - started,
    }
    _write_json(output / "manifest.json", manifest)
    _write_json(
        output / "complete.json",
        {
            "schema": "opennr-residual-target-view-v1",
            "manifest_sha256": _sha256_file(output / "manifest.json"),
            "rows_sha256": rows_sha,
            "residual_sha256": manifest["residual_file"]["sha256"],
            "stats_sha256": manifest["stats_file"]["sha256"],
            "test_used_for_tuning": False,
            "materialized": True,
        },
    )
    print(
        "completed "
        f"rows={len(rows)} residual={differences_path} "
        f"seconds={time.time() - started:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
