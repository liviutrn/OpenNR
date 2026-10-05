"""Apply the boundary gain/offset estimator to the exact published r3 runtime."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
contract = json.loads((root / 'scripts/v06/boundary-tone-contract.json').read_text())
for name, expected in contract.items():
    path = root / name
    if expected is None:
        if path.exists():
            raise SystemExit(f'Unexpected existing boundary-tone file: {name}')
    elif not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Published r3 source mismatch: {name}')
patch = 'scripts/v06/boundary-tone.patch'
subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
subprocess.run(['git', 'apply', patch], cwd=root, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=root, check=True)
print('v06-r4 boundary-tone patch and exact r3 source contract passed')
