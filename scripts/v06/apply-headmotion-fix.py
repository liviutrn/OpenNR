"""Apply the reviewed head-motion correction to the exact compiled v6 source."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
contract = json.loads((root / 'scripts/v06/headmotion-contract.json').read_text())
for name, expected in contract.items():
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise SystemExit(f'Published v6 source mismatch: {name}')
patch = 'scripts/v06/headmotion.patch'
subprocess.run(['git', 'apply', '--check', patch], cwd=root, check=True)
subprocess.run(['git', 'apply', patch], cwd=root, check=True)
subprocess.run(['git', 'diff', '--check'], cwd=root, check=True)
print('v6 head-motion patch and exact source contract passed')
