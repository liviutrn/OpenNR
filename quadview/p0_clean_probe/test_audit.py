#!/usr/bin/env python3
"""Synthetic log tests for conservative QuadP0 auditing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_log import audit

def line(draw, family, target, obj, state, original, effective, seq):
    return (
        f"[QuadP0] view seq={seq} draw={draw} engine_frame=100 object={obj:x} "
        f"family={family:x} target={target:x} viewstate={state:x} "
        f"original_pass={original} effective_pass={effective} family_views=2 thread=8"
    )

def main():
    lines = [
        "[QuadP0] draw=begin serial=1 engine_frame=100 thread=8 nested=false",
        line(1, 10, 20, 100, 1, 1, 1, 1),
        line(1, 10, 20, 101, 2, 2, 1, 2),
        "[QuadP0] draw=end serial=1 engine_frame=100 thread=8",
        "[QuadP0] draw=begin serial=2 engine_frame=100 thread=8 nested=false",
        line(2, 11, 21, 102, 3, 1, 1, 3),
        line(2, 11, 21, 103, 4, 2, 1, 4),
        "[QuadP0] draw=end serial=2 engine_frame=100 thread=8",
    ]
    report = audit("\n".join(lines))
    assert report["two_view_same_family_candidates"] == [1, 2]
    assert report["adjacent_same_frame_four_state_candidates"] == [[1, 2]]
    assert report["not_proven"]
    duplicate = lines.copy()
    duplicate[5] = line(2, 11, 21, 102, 1, 1, 1, 3)
    rejected = audit("\n".join(duplicate))
    assert not rejected["adjacent_same_frame_four_state_candidates"]
    incomplete = audit("\n".join(lines[:-1]))
    assert not incomplete["adjacent_same_frame_four_state_candidates"]
    print("QuadP0 audit positive, alias, and incomplete-frame fixtures passed")

if __name__ == "__main__":
    main()
