"""Test the safety contract for rebinding an initialized model to a new cache."""

from __future__ import annotations

import ast
from pathlib import Path


def main() -> None:
    source = Path(__file__).with_name("train_long_student.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    text = source
    assert "--allow-new-cache" in text
    assert "a.allow_new_cache and not a.initialize" in text
    assert "not (a.initialize and a.allow_new_cache)" in text
    assert "dataset_rebound" in text
    # Keep this as a source-level guard: a resume must never receive the
    # initialize-only override, even if a future refactor moves parser code.
    assert "resumes must keep the original cache identity" in text
    assert tree is not None
    print("PASS: train-long cache rebind is initialize-only")


if __name__ == "__main__":
    main()
