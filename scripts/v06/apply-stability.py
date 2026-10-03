"""Apply v6 only to the exact normalized v5 generated-source contract."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
inputs = json.loads((root / "scripts/v06/source-contract.json").read_text())
normalized = {}
for name, expected in inputs.items():
    path = root / name
    if expected is None:
        if path.exists():
            raise SystemExit(f"Unexpected pre-existing v6 input: {name}")
        continue
    text = path.read_text(encoding="utf-8-sig")
    if hashlib.sha256(text.encode()).hexdigest() != expected:
        raise SystemExit(f"v5 source contract mismatch: {name}")
    normalized[path] = text
for path, text in normalized.items():
    with path.open("w", encoding="utf-8", newline="\n") as output:
        output.write(text)
patch = "scripts/v06/stability.patch"
subprocess.run(["git", "apply", "--check", patch], cwd=root, check=True)
subprocess.run(["git", "apply", patch], cwd=root, check=True)
subprocess.run(["git", "diff", "--check"], cwd=root, check=True)
print("v6 source contract and patch application passed")
