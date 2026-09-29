"""Resolve external OpenNR storage without writing large payloads to D:."""
from __future__ import annotations

import json
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {
    "data": "C:/OpenNR/TrainingInputs",
    "cache": "C:/OpenNR/TrainingCache",
    "training": "C:/OpenNR/Training",
    "output": "C:/OpenNR/Outputs",
    "build": "E:/OpenNR_Builds/2.15.0",
    "dependencies": "C:/OpenNR/Dependencies/runtime-2.15.0",
}


def external_path(kind: str, explicit: str | Path | None = None) -> Path:
    """Apply CLI, environment, machine configuration, and default precedence."""
    if kind not in DEFAULTS:
        raise ValueError(f"Unknown OpenNR storage kind: {kind}")
    config_path = PROJECT_ROOT / "config" / "paths.local.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    value = explicit or os.environ.get(f"OPENNR_{kind.upper()}_ROOT") or config.get(kind) or DEFAULTS[kind]
    return require_external_output(Path(value).expanduser())


def require_external_output(path: Path | str) -> Path:
    """Resolve junctions, including an existing ancestor of a new output path."""
    resolved = Path(path).expanduser().resolve()
    if resolved.drive.casefold() == "d:":
        raise ValueError(f"OpenNR generated data must be outside D:; resolved destination: {resolved}")
    return resolved


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=DEFAULTS)
    parser.add_argument("--path")
    args = parser.parse_args()
    print(external_path(args.kind, args.path))
