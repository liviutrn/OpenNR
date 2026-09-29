#!/usr/bin/env python3
"""Audit contiguous OpenNR sequences before temporal training.

This is a metadata/path gate layered on top of validate_capture.py.  It does
not infer missing frames, repair motion vectors, or turn a sparse recording
into a clip.  The default ``master`` mode requires complete full-frame
resources.  The ``crop`` mode is an explicitly separate lower-I/O contract for
temporal training clips: every committed frame must contain the same complete
set of non-full crop resources for both eyes.  Neither mode changes the
renderer or invents missing frames.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


REQUIRED_STAGES = ("input", "teacher", "depth", "motion_vectors")
REQUIRED_ROLES = ("left_eye", "right_eye")
MAX_RECORDED_ERRORS = 200


@dataclass
class SequenceReport:
    sequence: str
    path: str
    frames: int = 0
    complete_frames: int = 0
    failed_frames: int = 0
    partial_frames: int = 0
    contiguous_pairs: int = 0
    host_frame_gaps: list[int] = field(default_factory=list)
    frame_id_gaps: list[int] = field(default_factory=list)
    sample_index_gaps: list[int] = field(default_factory=list)
    reset_indices: list[int] = field(default_factory=list)
    first_frame_resets: list[bool] | None = None
    resource_mode: str = "master"
    full_frame_complete: int = 0
    crop_frame_complete: int = 0
    backpressure_events: int = 0
    dropped_frames: int = 0
    errors: list[str] = field(default_factory=list)
    errors_total: int = 0
    warnings: list[str] = field(default_factory=list)
    temporal_ready: bool = False

    def error(self, message: str) -> None:
        self.errors_total += 1
        if len(self.errors) < MAX_RECORDED_ERRORS:
            self.errors.append(message)

    def warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["host_frame_gap_min"] = min(self.host_frame_gaps) if self.host_frame_gaps else None
        data["host_frame_gap_max"] = max(self.host_frame_gaps) if self.host_frame_gaps else None
        data["scope"] = "Committed full-frame metadata/path audit; use validate_capture.py for exhaustive bytes/PNG validation"
        return data


def _sequence_roots(paths: Iterable[Path]) -> list[Path]:
    roots: dict[str, Path] = {}
    for path in paths:
        path = path.resolve()
        if path.is_file() and path.name == "frames.jsonl":
            roots[str(path.parent)] = path.parent
        elif path.is_dir() and (path / "frames.jsonl").is_file():
            roots[str(path)] = path
        elif path.is_dir():
            for manifest in sorted(path.rglob("frames.jsonl")):
                roots[str(manifest.parent.resolve())] = manifest.parent.resolve()
    return [roots[key] for key in sorted(roots)]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _safe_path(root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate


def _full_keys(frame: dict[str, Any], root: Path, report: SequenceReport, line: int) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    artifacts = frame.get("artifacts")
    if not isinstance(artifacts, list):
        report.error(f"line {line}: artifacts is not an array")
        return keys
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not artifact.get("full_frame", False):
            continue
        try:
            stage = str(artifact["stage"])
            eye = int(artifact["eye"])
        except (KeyError, TypeError, ValueError):
            report.error(f"line {line}: malformed full-frame artifact identity")
            continue
        key = (stage, eye)
        if key in keys:
            report.error(f"line {line}: duplicate full-frame artifact {key}")
        keys.add(key)
        for path_key in ("raw_path", "png_path"):
            required = bool(artifact.get(f"{path_key.split('_')[0]}_required", True)) if path_key == "raw_path" else bool(artifact.get("png_required", False))
            if not required:
                continue
            resolved = _safe_path(root, artifact.get(path_key))
            if resolved is None or not resolved.is_file() or resolved.stat().st_size == 0:
                report.error(f"line {line}: missing full-frame {path_key} for {key}")
    return keys


def _crop_keys(frame: dict[str, Any], root: Path, report: SequenceReport, line: int) -> set[tuple[str, int, int]]:
    """Return and validate the non-full crop artifacts in one frame."""
    keys: set[tuple[str, int, int]] = set()
    artifacts = frame.get("artifacts")
    if not isinstance(artifacts, list):
        report.error(f"line {line}: artifacts is not an array")
        return keys
    for artifact in artifacts:
        if not isinstance(artifact, dict) or artifact.get("full_frame", False):
            continue
        try:
            stage = str(artifact["stage"])
            eye = int(artifact["eye"])
            crop_index = int(artifact["crop_index"])
        except (KeyError, TypeError, ValueError):
            report.error(f"line {line}: malformed crop artifact identity")
            continue
        key = (stage, eye, crop_index)
        if key in keys:
            report.error(f"line {line}: duplicate crop artifact {key}")
        keys.add(key)
        for path_key in ("raw_path", "png_path"):
            if path_key == "raw_path":
                required = bool(artifact.get("raw_required", True))
            else:
                required = bool(artifact.get("png_required", False))
            if not required:
                continue
            resolved = _safe_path(root, artifact.get(path_key))
            if resolved is None or not resolved.is_file() or resolved.stat().st_size == 0:
                report.error(f"line {line}: missing crop {path_key} for {key}")
    return keys


def audit_sequence(
    root: Path,
    require_initial_reset: bool = True,
    require_full_frames: bool = True,
    expected_pass_count: int = 1,
) -> SequenceReport:
    if expected_pass_count not in (1, 2):
        raise ValueError('Only explicitly selected one-pass or two-pass teacher modes are supported')
    sequence = _read_json(root / "sequence.json") or {}
    sequence_id = str(sequence.get("sequence_id") or root.name)
    report = SequenceReport(
        sequence=sequence_id,
        path=str(root),
        resource_mode="master" if require_full_frames else "crop",
    )
    manifest = root / "frames.jsonl"
    if not manifest.is_file():
        report.error("missing frames.jsonl")
        return report
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        report.error(f"cannot read frames.jsonl: {exc}")
        return report

    frames: list[tuple[int, dict[str, Any]]] = []
    for line_no, text in enumerate(lines, 1):
        if not text.strip():
            continue
        try:
            frame = json.loads(text)
        except json.JSONDecodeError as exc:
            report.error(f"line {line_no}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(frame, dict):
            report.error(f"line {line_no}: frame is not an object")
            continue
        report.frames += 1
        frames.append((line_no, frame))

    if not frames:
        report.error("no readable frame records")
        return report

    expected_signature: tuple[Any, ...] | None = None
    expected_crop_keys: set[tuple[str, int, int]] | None = None
    previous: dict[str, int] | None = None
    seen_frame_ids: set[int] = set()
    for index, (line_no, frame) in enumerate(frames):
        status = frame.get("status")
        if status == "complete":
            report.complete_frames += 1
        elif status == "failed":
            report.failed_frames += 1
            report.error(f"line {line_no}: failed frame record is not usable")
            continue
        elif status == "partial":
            report.partial_frames += 1
            report.error(f"line {line_no}: partial frame record is not usable")
            continue
        else:
            report.error(f"line {line_no}: status is not complete ({status!r})")
            continue

        try:
            frame_id = int(frame["frame_id"])
            sample_index = int(frame["sample_index"])
            host_frame = int(frame["host_frame"])
        except (KeyError, TypeError, ValueError):
            report.error(f"line {line_no}: frame_id, sample_index or host_frame is invalid")
            continue
        if frame_id in seen_frame_ids:
            report.error(f"line {line_no}: duplicate frame_id {frame_id}")
        seen_frame_ids.add(frame_id)
        if str(frame.get("sequence_id")) != sequence_id:
            report.error(f"line {line_no}: sequence_id does not match sequence.json")

        resets = frame.get("history_reset")
        if not isinstance(resets, list) or len(resets) != 2 or not all(isinstance(value, bool) for value in resets):
            report.error(f"line {line_no}: history_reset must be [bool, bool]")
        else:
            reset_pair = [bool(value) for value in resets]
            if any(reset_pair):
                report.reset_indices.append(index)
            if index == 0:
                report.first_frame_resets = reset_pair
            elif any(reset_pair):
                report.error(f"line {line_no}: mid-clip history reset; split clips at reset boundaries")

        dropped = int(frame.get("dropped_frames_before", 0) or 0)
        backpressure = int(frame.get("backpressure_events_before", 0) or 0)
        report.dropped_frames = max(report.dropped_frames, dropped)
        report.backpressure_events = max(report.backpressure_events, backpressure)
        if dropped:
            report.error(f"line {line_no}: dropped_frames_before={dropped}")
        if backpressure:
            report.warning(f"backpressure_events_before reached {backpressure}")

        signature = (
            frame.get("route"),
            frame.get("model_resolution_percent"),
            frame.get("pass_count"),
            frame.get("color_width"),
            frame.get("color_height"),
            frame.get("guide_width"),
            frame.get("guide_height"),
            json.dumps(frame.get("teacher_settings"), sort_keys=True),
        )
        if expected_signature is None:
            expected_signature = signature
        elif signature != expected_signature:
            report.error(f"line {line_no}: renderer/settings signature changed inside clip")
        if frame.get("route") != "feature18_stereo":
            report.error(f"line {line_no}: route is not feature18_stereo")
        if frame.get("model_resolution_percent") != 100 or frame.get("pass_count") != expected_pass_count:
            report.error(f"line {line_no}: expected 100% model resolution and {expected_pass_count} Feature 18 pass(es)")
        if frame.get("motion_vector_contract") != "exact_feature18_bound_resource":
            report.error(f"line {line_no}: motion-vector contract is not exact_feature18_bound_resource")

        if require_full_frames:
            full_keys = _full_keys(frame, root, report, line_no)
            if all((stage, eye) in full_keys for stage in REQUIRED_STAGES for eye in (0, 1)):
                report.full_frame_complete += 1
            else:
                report.error(f"line {line_no}: missing one or more full-frame stage/eye resources")
        else:
            crop_keys = _crop_keys(frame, root, report, line_no)
            expected_crop_keys = crop_keys if expected_crop_keys is None else expected_crop_keys
            if expected_crop_keys != crop_keys:
                report.error(f"line {line_no}: crop stage/eye/crop set changed inside clip")
            required_crop_keys = {
                (stage, eye, crop_index)
                for stage in REQUIRED_STAGES
                for eye in (0, 1)
                for crop_index in sorted({key[2] for key in (expected_crop_keys or set())})
            }
            if required_crop_keys and required_crop_keys.issubset(crop_keys):
                report.crop_frame_complete += 1
            else:
                report.error(f"line {line_no}: missing one or more crop stage/eye resources")

        if previous is not None:
            frame_gap = frame_id - previous["frame_id"]
            sample_gap = sample_index - previous["sample_index"]
            host_gap = host_frame - previous["host_frame"]
            report.frame_id_gaps.append(frame_gap)
            report.sample_index_gaps.append(sample_gap)
            report.host_frame_gaps.append(host_gap)
            if frame_gap == 1 and sample_gap == 1 and host_gap == 1:
                report.contiguous_pairs += 1
            else:
                report.error(
                    f"line {line_no}: non-contiguous transition frame={frame_gap}, sample={sample_gap}, host={host_gap}"
                )
        previous = {"frame_id": frame_id, "sample_index": sample_index, "host_frame": host_frame}

    if require_initial_reset and report.first_frame_resets != [True, True]:
        report.error(f"first frame must reset both eyes, got {report.first_frame_resets}")
    if report.complete_frames < 2:
        report.error("at least two complete frames are required")
    if require_full_frames:
        if report.full_frame_complete != report.complete_frames:
            report.error("every complete frame must have all full-frame stages for both eyes")
        resource_complete = report.full_frame_complete
    else:
        if report.crop_frame_complete != report.complete_frames:
            report.error("every complete frame must have the same complete crop stages for both eyes")
        resource_complete = report.crop_frame_complete
    report.temporal_ready = (
        report.errors_total == 0
        and report.complete_frames >= 2
        and report.contiguous_pairs == report.complete_frames - 1
        and resource_complete == report.complete_frames
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="sequence directory, frames.jsonl, or capture root")
    parser.add_argument("--output", type=Path, help="write a JSON report")
    parser.add_argument('--expected-pass-count', type=int, choices=(1,2), default=1)
    parser.add_argument("--allow-missing-initial-reset", action="store_true", help="report reset absence as a warning instead of a temporal gate failure")
    parser.add_argument(
        "--mode",
        choices=("master", "crop"),
        default="master",
        help="resource contract: master requires full-frame resources; crop accepts complete non-full crop resources",
    )
    args = parser.parse_args()
    roots = _sequence_roots(args.paths)
    if not roots:
        print("No sequence manifests found", file=sys.stderr)
        return 2
    reports = [
        audit_sequence(
            root,
            require_initial_reset=not args.allow_missing_initial_reset,
            require_full_frames=args.mode == "master",
            expected_pass_count=args.expected_pass_count,
        )
        for root in roots
    ]
    result = {
        "schema": "opennr-temporal-capture-audit-v1",
        "expected_pass_count": args.expected_pass_count,
        "sequences": len(reports),
        "temporal_ready_sequences": sum(report.temporal_ready for report in reports),
        "temporal_ready": bool(reports) and all(report.temporal_ready for report in reports),
        "reports": [report.as_dict() for report in reports],
        "scope": (
            "Metadata/path gate for contiguous Feature 18 master clips. It does not repair data or prove temporal image quality."
            if args.mode == "master"
            else "Metadata/path gate for contiguous Feature 18 crop clips. It does not repair data or prove temporal image quality or full-frame coverage."
        ),
    }
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded)
    return 0 if result["temporal_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
