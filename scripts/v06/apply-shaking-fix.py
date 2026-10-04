"""Apply crop-grid corrections only to the reviewed v06-r1 generated source."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
contract = json.loads((root / 'scripts/v06/shaking-contract.json').read_text())
for name, expected in contract.items():
    path = root / name
    if expected is None:
        if path.exists():
            raise SystemExit(f'Unexpected existing shader: {name}')
    elif not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Published v06-r1 source mismatch: {name}')
patch = 'scripts/v06/shaking.patch'
subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
subprocess.run(['git', 'apply', patch], cwd=root, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=root, check=True)
print('v06-r2 crop-grid patch and exact source contract passed')
