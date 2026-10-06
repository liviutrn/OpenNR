"""Apply the inside-NR protection and expanded controls to the exact r5 runtime."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path(__file__).resolve().parents[2]
contract = json.loads((root/'scripts/v06/nr-black-contract.json').read_text())
for name,expected in contract.items():
    path = root/name
    if expected is None:
        if path.exists(): raise SystemExit(f'Unexpected existing NR-protection file: {name}')
    elif not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit(f'Published r5 source mismatch: {name}')
patch = 'scripts/v06/nr-black.patch'
subprocess.run(['git','apply','--check',patch],cwd=root,check=True)
subprocess.run(['git','apply',patch],cwd=root,check=True)
subprocess.run(['git','diff','--check'],cwd=root,check=True)
print('v06-r6 inside-protection patch and exact r5 source contract passed')
