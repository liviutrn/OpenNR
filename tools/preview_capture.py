#!/usr/bin/env python3
"""Create a dependency-free HTML contact sheet for an OpenNR capture dataset."""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
from typing import Any, Iterable


def _frame_files(root: Path) -> Iterable[Path]:
    if root.is_file() and root.name == "frames.jsonl":
        yield root
    elif root.is_dir():
        yield from sorted(root.rglob("frames.jsonl"))


def _safe_png(sequence_root: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = (sequence_root / relative).resolve()
    try:
        candidate.relative_to(sequence_root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _display_root(root: Path, frame_files: list[Path]) -> Path:
    if root.is_file():
        return root.parent
    if len(frame_files) == 1 and frame_files[0].parent == root:
        return root
    return root


def build_preview(root: Path, output: Path, limit: int) -> int:
    frame_files = list(_frame_files(root))
    records: list[tuple[Path, dict[str, Any]]] = []
    for frame_file in frame_files:
        sequence_root = frame_file.parent
        try:
            lines = frame_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                frame = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(frame, dict):
                records.append((sequence_root, frame))
    records = records[: max(0, limit)] if limit else records

    sections: list[str] = []
    image_count = 0
    for sequence_root, frame in records:
        sequence_id = html.escape(str(frame.get("sequence_id", "unknown")))
        frame_id = html.escape(str(frame.get("frame_id", "?")))
        status = html.escape(str(frame.get("status", "unknown")))
        cards: list[str] = []
        for artifact in frame.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            png = _safe_png(sequence_root, artifact.get("png_path"))
            if png is None:
                continue
            image_count += 1
            relative = os.path.relpath(png, output.parent).replace(os.sep, "/")
            stage = html.escape(str(artifact.get("stage", "?")))
            eye = html.escape(str(artifact.get("eye", "?")))
            crop = html.escape(str(artifact.get("crop_index", "?")))
            dimensions = f"{html.escape(str(artifact.get('width', '?')))}×{html.escape(str(artifact.get('height', '?')))}"
            cards.append(
                '<figure><img loading="lazy" src="{}" alt="{} eye {} crop {}">'
                '<figcaption>{} · eye {} · crop {} · {}</figcaption></figure>'.format(
                    html.escape(relative), stage, eye, crop, stage, eye, crop, dimensions
                )
            )
        sections.append(
            '<section><h2>{} · frame {} · {}</h2><div class="meta">sample {} · host frame {} · route {}</div>'
            '<div class="grid">{}</div></section>'.format(
                sequence_id,
                frame_id,
                status,
                html.escape(str(frame.get("sample_index", "?"))),
                html.escape(str(frame.get("host_frame", "?"))),
                html.escape(str(frame.get("route", "?"))),
                "".join(cards) or '<p class="missing">No readable PNG artifacts.</p>',
            )
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    title = html.escape(root.name or "OpenNR capture")
    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>OpenNR preview — {title}</title>
<style>
body{{font:14px system-ui,sans-serif;background:#15171b;color:#e8eaf0;margin:24px}}
h1{{font-size:22px}}h2{{font-size:16px;margin-bottom:4px}}section{{margin:24px 0;border-top:1px solid #3a3d45;padding-top:12px}}
.meta{{color:#aeb4c0;margin-bottom:10px}}.grid{{display:flex;flex-wrap:wrap;gap:12px}}
figure{{margin:0;background:#20232a;padding:8px;border-radius:6px}}img{{display:block;width:256px;height:256px;object-fit:contain;background:#000}}
figcaption{{max-width:256px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:6px;color:#c6cad4}}
.missing{{color:#ffb86c}}
</style></head><body><h1>OpenNR capture preview</h1>
<p>{frames} frame records · {images} PNG artifacts</p>{sections}</body></html>
""".format(frames=len(records), images=image_count, title=title, sections="".join(sections))
    output.write_text(document, encoding="utf-8")
    return len(records)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="capture root, sequence directory, or frames.jsonl")
    parser.add_argument("-o", "--output", type=Path, help="HTML output path (default: <root>/preview.html)")
    parser.add_argument("--limit", type=int, default=0, help="preview at most N frame records (0 means all)")
    args = parser.parse_args(argv)
    frame_files = list(_frame_files(args.root))
    if not frame_files:
        parser.error(f"no frames.jsonl found under {args.root}")
    root = _display_root(args.root, frame_files)
    output = args.output or (root / "preview.html")
    count = build_preview(args.root, output, args.limit)
    print(json.dumps({"output": str(output), "frames": count}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
