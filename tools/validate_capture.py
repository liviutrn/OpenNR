#!/usr/bin/env python3
"""Validate an OpenNR-VR capture sequence without third-party dependencies."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BYTES_PER_PIXEL = {
    9: 8,  # R16G16B16A16_TYPELESS
    28: 4,  # R8G8B8A8_UNORM
    29: 4,  # R8G8B8A8_UNORM_SRGB
    27: 4,  # R8G8B8A8_TYPELESS
    23: 4,  # R10G10B10A2_TYPELESS
    87: 4,  # B8G8R8A8_UNORM
    91: 4,  # B8G8R8A8_UNORM_SRGB
    90: 4,  # B8G8R8A8_TYPELESS
    88: 4,  # B8G8R8X8_UNORM
    92: 4,  # B8G8R8X8_TYPELESS
    24: 4,  # R10G10B10A2_UNORM
    10: 8,  # R16G16B16A16_FLOAT
    11: 8,  # R16G16B16A16_UNORM
    15: 8,  # R32G32_TYPELESS
    16: 8,  # R32G32_FLOAT
    33: 4,  # R16G16_TYPELESS
    34: 4,  # R16G16_FLOAT
    37: 4,  # R16G16_SNORM
    39: 4,  # R32_TYPELESS
    41: 4,  # R32_FLOAT
}


@dataclass
class ValidationReport:
    sequences: int = 0
    frames: int = 0
    complete_frames: int = 0
    partial_frames: int = 0
    failed_frames: int = 0
    artifacts: int = 0
    missing_files: int = 0
    duplicate_ids: int = 0
    duplicate_hashes: int = 0
    all_zero_images: int = 0
    all_zero_raw: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "sequences": self.sequences,
            "frames": self.frames,
            "complete_frames": self.complete_frames,
            "partial_frames": self.partial_frames,
            "failed_frames": self.failed_frames,
            "artifacts": self.artifacts,
            "missing_files": self.missing_files,
            "duplicate_ids": self.duplicate_ids,
            "duplicate_hashes": self.duplicate_hashes,
            "all_zero_images": self.all_zero_images,
            "all_zero_raw": self.all_zero_raw,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _read_png(path: Path) -> tuple[int, int, int, int, bytes] | None:
    """Return width, height, bit depth, color type, and decompressed scanlines."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 33 or data[:8] != PNG_SIGNATURE:
        return None
    offset = 8
    width = height = bit_depth = color_type = None
    interlace = 1
    idat = bytearray()
    while offset + 12 <= len(data):
        length = struct.unpack_from(">I", data, offset)[0]
        kind = data[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(data):
            return None
        payload = data[payload_start:payload_end]
        if kind == b"IHDR" and len(payload) >= 13:
            width, height, bit_depth, color_type = struct.unpack_from(">IIBB", payload, 0)
            interlace = payload[12]
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
        offset = payload_end + 4
    if None in (width, height, bit_depth, color_type) or interlace != 0:
        return None
    try:
        scanlines = zlib.decompress(bytes(idat))
    except zlib.error:
        return None
    return width, height, bit_depth, color_type, scanlines


def _png_has_signal(path: Path) -> bool | None:
    """Check RGB8 PNG pixels after undoing PNG row filters."""
    parsed = _read_png(path)
    if parsed is None:
        return None
    width, height, bit_depth, color_type, scanlines = parsed
    if bit_depth != 8 or color_type != 2:
        return None
    row_bytes = width * 3
    expected = height * (row_bytes + 1)
    if len(scanlines) < expected:
        return None
    previous = bytearray(row_bytes)
    offset = 0
    for _ in range(height):
        filter_type = scanlines[offset]
        encoded = scanlines[offset + 1 : offset + 1 + row_bytes]
        offset += row_bytes + 1
        row = bytearray(encoded)
        for index in range(row_bytes):
            left = row[index - 3] if index >= 3 else 0
            up = previous[index]
            upper_left = previous[index - 3] if index >= 3 else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 0xFF
            elif filter_type == 2:
                row[index] = (row[index] + up) & 0xFF
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                prediction = left + up - upper_left
                distances = (abs(prediction - left), abs(prediction - up), abs(prediction - upper_left))
                predictor = (left, up, upper_left)[distances.index(min(distances))]
                row[index] = (row[index] + predictor) & 0xFF
            elif filter_type != 0:
                return None
        if any(row):
            return True
        previous = row
    return False


def _safe_artifact_path(sequence_root: Path, relative: str) -> Path | None:
    candidate = (sequence_root / relative).resolve()
    root = sequence_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _iter_frame_files(root: Path) -> Iterable[Path]:
    if root.is_file() and root.name == "frames.jsonl":
        yield root
    elif root.is_dir():
        yield from sorted(root.rglob("frames.jsonl"))


def validate_capture(root: Path, expected_crop_size: int = 512) -> ValidationReport:
    report = ValidationReport()
    frame_files = list(_iter_frame_files(root))
    report.sequences = len(frame_files)
    if not frame_files:
        report.errors.append(f"no frames.jsonl found under {root}")
        return report

    seen_ids: set[tuple[str, int]] = set()
    seen_hashes: dict[str, Path] = {}
    last_order: dict[str, tuple[int, int]] = {}

    for frame_file in frame_files:
        sequence_root = frame_file.parent
        sequence: dict[str, Any] = {}
        sequence_path = sequence_root / "sequence.json"
        try:
            loaded_sequence = json.loads(sequence_path.read_text(encoding="utf-8"))
            if isinstance(loaded_sequence, dict):
                sequence = loaded_sequence
        except (OSError, json.JSONDecodeError) as exc:
            report.errors.append(f"cannot read {sequence_path}: {exc}")
        try:
            lines = frame_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            report.errors.append(f"cannot read {frame_file}: {exc}")
            continue
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError as exc:
                report.errors.append(f"{frame_file}:{line_number}: invalid JSON: {exc.msg}")
                continue
            report.frames += 1
            required = ("schema_version", "sequence_id", "frame_id", "sample_index", "artifacts")
            missing = [key for key in required if key not in frame]
            if missing:
                report.errors.append(f"{frame_file}:{line_number}: missing fields {missing}")
                continue
            sequence_id = str(frame["sequence_id"])
            try:
                frame_id = int(frame["frame_id"])
                sample_index = int(frame["sample_index"])
            except (TypeError, ValueError):
                report.errors.append(f"{frame_file}:{line_number}: frame/sample IDs are not integers")
                continue
            identity = (sequence_id, frame_id)
            if identity in seen_ids:
                report.duplicate_ids += 1
                report.errors.append(f"{frame_file}:{line_number}: duplicate frame ID {identity}")
            seen_ids.add(identity)
            order = (frame_id, sample_index)
            previous = last_order.get(sequence_id)
            if previous is not None and order <= previous:
                report.errors.append(f"{frame_file}:{line_number}: frame order regressed for {sequence_id}")
            last_order[sequence_id] = order

            status = frame.get("status", "unknown")
            if status == "complete":
                report.complete_frames += 1
            elif status == "partial":
                report.partial_frames += 1
            elif status == "failed":
                report.failed_frames += 1
            artifacts = frame.get("artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                report.errors.append(f"{frame_file}:{line_number}: artifacts is empty or not an array")
                continue
            artifact_keys: set[tuple[str, int, int]] = set()
            for artifact in artifacts:
                if not isinstance(artifact, dict) or artifact.get("full_frame", False):
                    continue
                try:
                    key = (str(artifact.get("stage", "")), int(artifact.get("eye")), int(artifact.get("crop_index")))
                except (TypeError, ValueError):
                    continue
                if key in artifact_keys:
                    report.errors.append(f"{frame_file}:{line_number}: duplicate artifact {key}")
                artifact_keys.add(key)

            required_stages = []
            for enabled_key, stage in (
                ("pre_nr", "input"),
                ("post_nr", "teacher"),
                ("depth", "depth"),
                ("motion_vectors", "motion_vectors"),
            ):
                if sequence.get(enabled_key, False):
                    required_stages.append(stage)
            required_eyes = [eye for eye, key in ((0, "left_eye"), (1, "right_eye")) if sequence.get(key, False)]
            crop_count = int(sequence.get("crop_count", 0))
            for stage in required_stages:
                for eye in required_eyes:
                    for crop_index in range(crop_count):
                        key = (stage, eye, crop_index)
                        if key not in artifact_keys:
                            report.errors.append(f"{frame_file}:{line_number}: missing paired artifact {key}")
            for artifact in artifacts:
                report.artifacts += 1
                if not isinstance(artifact, dict):
                    report.errors.append(f"{frame_file}:{line_number}: artifact is not an object")
                    continue
                width = artifact.get("width")
                height = artifact.get("height")
                full_frame = bool(artifact.get("full_frame", False))
                if not full_frame and (width != expected_crop_size or height != expected_crop_size):
                    report.errors.append(
                        f"{frame_file}:{line_number}: crop is {width}x{height}, expected {expected_crop_size}x{expected_crop_size}"
                    )
                png_required = bool(artifact.get("png_required", True))
                raw_required = bool(artifact.get("raw_required", True))
                png_path = _safe_artifact_path(sequence_root, str(artifact.get("png_path", ""))) if png_required else None
                raw_path = _safe_artifact_path(sequence_root, str(artifact.get("raw_path", "")))
                if png_required and (png_path is None or not png_path.is_file() or png_path.stat().st_size == 0):
                    report.missing_files += 1
                    report.errors.append(f"{frame_file}:{line_number}: missing PNG {artifact.get('png_path')}")
                elif png_required and png_path is not None:
                    parsed = _read_png(png_path)
                    if parsed is None:
                        report.errors.append(f"{png_path}: invalid or unsupported PNG")
                    else:
                        png_width, png_height, depth, color_type, _ = parsed
                        if (png_width, png_height) != (width, height):
                            report.errors.append(f"{png_path}: dimensions {png_width}x{png_height} != metadata {width}x{height}")
                        if depth != 8 or color_type != 2:
                            report.errors.append(f"{png_path}: expected 8-bit RGB PNG, got depth={depth} color_type={color_type}")
                    digest = hashlib.sha256(png_path.read_bytes()).hexdigest()
                    if digest in seen_hashes:
                        report.duplicate_hashes += 1
                        report.warnings.append(f"duplicate PNG hash: {png_path} == {seen_hashes[digest]}")
                    else:
                        seen_hashes[digest] = png_path
                    signal = _png_has_signal(png_path)
                    if signal is False:
                        report.all_zero_images += 1
                        report.warnings.append(f"all-zero RGB image: {png_path}")
                if raw_required and (raw_path is None or not raw_path.is_file() or raw_path.stat().st_size == 0):
                    report.missing_files += 1
                    report.errors.append(f"{frame_file}:{line_number}: missing raw readback {artifact.get('raw_path')}")
                elif raw_path is not None:
                    fmt = int(artifact.get("format", -1)) if str(artifact.get("format", "")).lstrip("-").isdigit() else -1
                    bpp = BYTES_PER_PIXEL.get(fmt)
                    if bpp and isinstance(width, int) and isinstance(height, int):
                        expected_bytes = width * height * bpp
                        if raw_path.stat().st_size != expected_bytes:
                            report.errors.append(f"{raw_path}: {raw_path.stat().st_size} bytes != expected {expected_bytes}")
                    if raw_path.stat().st_size > 0 and not any(raw_path.read_bytes()):
                        report.all_zero_raw += 1
                        report.warnings.append(f"all-zero raw tensor: {raw_path}")

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="capture root or a sequence directory")
    parser.add_argument("--expected-crop-size", type=int, default=512)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit the report as JSON")
    args = parser.parse_args(argv)
    report = validate_capture(args.root, args.expected_crop_size)
    if args.as_json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(json.dumps(report.as_dict(), indent=2))
        if report.warnings:
            print(f"warnings: {len(report.warnings)}", file=sys.stderr)
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
