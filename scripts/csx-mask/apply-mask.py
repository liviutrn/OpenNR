"""Apply the CSX-style shader detail mask to exact reconstructed r8."""
from pathlib import Path
import hashlib,json,subprocess
root=Path(__file__).resolve().parents[2]
contract=json.loads((root/'scripts/csx-mask/source-contract.json').read_text())
def sha(path):
    p=root/path
    return hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() if p.exists() else None
before=all(sha(p)==v['before'] for p,v in contract.items())
after=all(sha(p)==v['after'] for p,v in contract.items())
if before:
    subprocess.run(['git','apply','--check','--ignore-space-change','scripts/csx-mask/csx-mask.patch'],cwd=root,check=True)
    subprocess.run(['git','apply','--ignore-space-change','scripts/csx-mask/csx-mask.patch'],cwd=root,check=True)
elif not after:
    raise SystemExit('CSX mask source preimage mismatch: '+str([p for p,v in contract.items() if sha(p)!=v['before']]))
assert all(sha(p)==v['after'] for p,v in contract.items()),'CSX mask postimage mismatch'
print('CSX detail-mask exact source replay verified')
