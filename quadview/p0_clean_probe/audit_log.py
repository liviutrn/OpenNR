#!/usr/bin/env python3
"""Audit generic [QuadP0] records from ordinary UEVR log text.

The report describes observed pointer/pass patterns only. It does not prove
ownership, physical-eye pose, stable history, simulation timing, or rendering.
"""
import argparse
import json
import re
from pathlib import Path

DRAW = re.compile(r"\[QuadP0\] draw=(begin|end) serial=(\d+) engine_frame=(\d+) thread=(\d+)(?: nested=(true|false))?")
VIEW = re.compile(
    r"\[QuadP0\] view seq=(\d+) draw=(\d+) engine_frame=(\d+) "
    r"object=([0-9a-fA-F]+) family=([0-9a-fA-F]+) target=([0-9a-fA-F]+) "
    r"viewstate=([0-9a-fA-F]+) original_pass=(\d+) effective_pass=(\d+) "
    r"family_views=(-?\d+) thread=(\d+)"
)

def audit(text: str) -> dict:
    draws = {}
    warnings = []
    view_count = 0
    for line in text.splitlines():
        match = DRAW.search(line)
        if match:
            kind, serial, frame, thread, nested = match.groups()
            serial, frame, thread = int(serial), int(frame), int(thread)
            slot = draws.setdefault(serial, {"views": []})
            key = kind + "_frame"
            if key in slot:
                warnings.append(f"repeated {kind} record for draw {serial}")
            slot[key] = frame
            slot[kind + "_thread"] = thread
            if nested == "true":
                warnings.append(f"nested viewport Draw {serial}")
            continue
        match = VIEW.search(line)
        if match:
            seq, draw, frame, obj, family, target, state, original, effective, count, thread = match.groups()
            draw = int(draw)
            slot = draws.setdefault(draw, {"views": []})
            slot["views"].append({
                "sequence": int(seq), "frame": int(frame), "object": int(obj, 16),
                "family": int(family, 16), "target": int(target, 16),
                "state": int(state, 16), "original_pass": int(original),
                "effective_pass": int(effective), "family_views": int(count),
                "thread": int(thread)
            })
            view_count += 1

    complete_draws = []
    native_pair_candidates = []
    for serial in sorted(draws):
        slot = draws[serial]
        views = slot["views"]
        if "begin_frame" not in slot or "end_frame" not in slot:
            warnings.append(f"incomplete Draw {serial}")
            continue
        if slot["begin_frame"] != slot["end_frame"]:
            warnings.append(f"engine frame changed during Draw {serial}")
            continue
        if slot.get("begin_thread") != slot.get("end_thread"):
            warnings.append(f"thread changed during Draw {serial}")
        if any(v["frame"] != slot["begin_frame"] for v in views):
            warnings.append(f"constructor frame differs from Draw {serial}")
            continue
        complete_draws.append(serial)
        if len(views) == 2:
            same_family = len({v["family"] for v in views}) == 1
            distinct_objects = len({v["object"] for v in views}) == 2 and all(v["object"] for v in views)
            distinct_states = len({v["state"] for v in views}) == 2 and all(v["state"] for v in views)
            passes = {v["original_pass"] for v in views}
            if same_family and distinct_objects and distinct_states and passes == {1, 2}:
                native_pair_candidates.append(serial)

    four_source_candidates = []
    ordered = sorted(native_pair_candidates)
    for first, second in zip(ordered, ordered[1:]):
        if second != first + 1:
            continue
        left, right = draws[first], draws[second]
        if left["begin_frame"] != right["begin_frame"]:
            continue
        views = left["views"] + right["views"]
        if (len({v["family"] for v in views}) == 2 and
            len({v["object"] for v in views}) == 4 and
            len({v["target"] for v in views}) >= 1 and
            len({v["state"] for v in views}) == 4 and
            all(v["family"] and v["state"] for v in views)):
            four_source_candidates.append([first, second])

    return {
        "protocol": "QuadP0 generic read-only Draw/FSceneView observations",
        "draw_count": len(draws),
        "constructor_count": view_count,
        "complete_draws_same_engine_frame": len(complete_draws),
        "two_view_same_family_candidates": native_pair_candidates,
        "adjacent_same_frame_four_state_candidates": four_source_candidates,
        "draws": {
            str(serial): {
                "begin_frame": draws[serial].get("begin_frame"),
                "end_frame": draws[serial].get("end_frame"),
                "views": draws[serial]["views"]
            } for serial in sorted(draws)
        },
        "warnings": warnings,
        "not_proven": [
            "four persistent engine-owned state owners",
            "which physical eye each view represents",
            "same-eye camera pose or asymmetric projection",
            "one gameplay/world tick across adjacent Draw calls",
            "Native Stereo Fix shader and history parity",
            "separate GPU capture targets and fence retirement",
            "final left/right XR composition or submission"
        ]
    }

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", help="UEVR log containing [QuadP0] lines")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args()
    report = json.dumps(audit(Path(args.log).read_text(encoding="utf-8", errors="replace")), indent=2)
    if args.output:
        Path(args.output).write_text(report + "\n", encoding="utf-8")
    print(report)

if __name__ == "__main__":
    main()
