"""Apply r10 to exact reconstructed r7 source; reject partial or mismatched inputs."""
import hashlib,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
contract=json.loads((root/'scripts/v10/source-contract.json').read_text())
def digest(name):
    return hashlib.sha256((root/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
before=all(digest(name)==value['before'] for name,value in contract.items())
after=all(digest(name)==value['after'] for name,value in contract.items())
if before:
    subprocess.run(['git','apply','--check','--ignore-space-change','scripts/v10/r10.patch'],cwd=root,check=True)
    subprocess.run(['git','apply','--ignore-space-change','scripts/v10/r10.patch'],cwd=root,check=True)
elif not after:
    raise SystemExit('r10 exact source preimage mismatch: '+str({name:{'actual':digest(name),'expected':value['before']} for name,value in contract.items() if digest(name)!=value['before']}))
assert all(digest(name)==value['after'] for name,value in contract.items()),'r10 source postimage mismatch'
print('r10 exact reviewed source applied')
