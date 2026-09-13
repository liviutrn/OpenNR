"""Regression fixtures for the contiguous temporal capture gate."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from validate_temporal_capture import audit_sequence


def _make_sequence(root: Path, *, contiguous: bool, reset: bool) -> Path:
    sequence = root / "seq-test"
    sequence.mkdir(parents=True)
    (sequence / "frames").mkdir()
    (sequence / "sequence.json").write_text(json.dumps({"sequence_id": sequence.name}), encoding="utf-8")
    records = []
    for index in range(3):
        frame = {
            "sequence_id": sequence.name,
            "status": "complete",
            "frame_id": index + 1,
            "sample_index": index + 1,
            "host_frame": 100 + index if contiguous else 100 + index * 3,
            "history_reset": [reset and index == 0, reset and index == 0],
            "dropped_frames_before": 0,
            "backpressure_events_before": 0,
            "route": "feature18_stereo",
            "model_resolution_percent": 100,
            "pass_count": 1,
            "color_width": 4,
            "color_height": 4,
            "guide_width": 2,
            "guide_height": 2,
            "motion_vector_contract": "exact_feature18_bound_resource",
            "teacher_settings": {"style": 0},
            "artifacts": [],
        }
        for eye in (0, 1):
            for stage in ("input", "teacher", "depth", "motion_vectors"):
                path = sequence / "frames" / f"f{index}_s{stage}_e{eye}.bin"
                path.write_bytes(b"valid")
                frame["artifacts"].append({
                    "stage": stage,
                    "eye": eye,
                    "full_frame": True,
                    "raw_required": True,
                    "raw_path": str(path.relative_to(sequence)),
                })
        records.append(frame)
    (sequence / "frames.jsonl").write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")
    return sequence


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="opennr-temporal-test-") as tmp:
        root = Path(tmp)
        good = audit_sequence(_make_sequence(root / "good", contiguous=True, reset=True))
        assert good.temporal_ready, good.as_dict()
        sparse = audit_sequence(_make_sequence(root / "sparse", contiguous=False, reset=True))
        assert not sparse.temporal_ready and sparse.errors_total
        no_reset = audit_sequence(_make_sequence(root / "no-reset", contiguous=True, reset=False))
        assert not no_reset.temporal_ready and no_reset.errors_total
        multi=_make_sequence(root/'two-pass',contiguous=True,reset=True)
        records=[json.loads(line) for line in (multi/'frames.jsonl').read_text().splitlines()]
        for record in records:record['pass_count']=2
        (multi/'frames.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
        assert not audit_sequence(multi).temporal_ready
        assert audit_sequence(multi,expected_pass_count=2).temporal_ready
        records[-1]['pass_count']=1
        (multi/'frames.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
        assert not audit_sequence(multi,expected_pass_count=2).temporal_ready
    print("PASS: temporal gate accepts reset-and-contiguous clips and rejects sparse/no-reset fixtures")


if __name__ == "__main__":
    main()
