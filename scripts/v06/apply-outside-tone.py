"""Apply the isolated outside-only effect to the exact published r2 runtime."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
contract = json.loads((root / 'scripts/v06/outside-tone-contract.json').read_text())
for name, expected in contract.items():
    path = root / name
    if expected is None:
        if path.exists():
            raise SystemExit(f'Unexpected existing outside-tone file: {name}')
    elif not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Published r2 source mismatch: {name}')
patch = 'scripts/v06/outside-tone.patch'
subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
subprocess.run(['git', 'apply', patch], cwd=root, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=root, check=True)
print('v06-r3 outside-tone patch and exact r2 source contract passed')
