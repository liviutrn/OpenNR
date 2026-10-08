"""Apply r7 only to the reviewed, fully reconstructed r6 source."""
import hashlib, json, subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[2]
contract=json.loads((root/'scripts/v07/source-contract.json').read_text())
def digest(path):
    p=root/path
    return hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() if p.exists() else None
before=all(digest(p)==v['before'] for p,v in contract.items())
after=all(digest(p)==v['after'] for p,v in contract.items())
if before:
    subprocess.run(['git','apply','--check','--ignore-space-change','scripts/v07/r7.patch'],cwd=root,check=True)
    subprocess.run(['git','apply','--ignore-space-change','scripts/v07/r7.patch'],cwd=root,check=True)
elif not after:
    raise SystemExit('r7 preimage mismatch: '+str([p for p,v in contract.items() if digest(p)!=v['before']]))
assert all(digest(p)==v['after'] for p,v in contract.items()), 'r7 postimage mismatch'
# Historical reconstruction checks stay before r7. Update final UI contracts
# to describe the permanent native-gaze provider and the single controller.
p=root/'runtime/open-shaders/cmake/ValidateOpenNRSourceContracts.cmake'
if p.exists():
    s=p.read_text(encoding='utf-8-sig')
    for old,new in [('Native OpenVR gaze provider','Native OpenVR gaze'),('Temporal Stability','Adaptive Performance'),
                    ('    "neuralRenderingTemporalReuseCadence"\n','    "neuralRenderingForcedStage"\n'),
                    ('    "neuralRenderingTemporalReuseResetAfterSkip"\n','    "neuralRenderingCropDrop"\n'),
                    ('The temporal-reuse controls or dedicated page would regress.',
                     'The adaptive controller controls or dedicated page would regress.'),
                    ('The experimental provider must stay opt-in and fail closed through the existing foveated/NR path.',
                     'The native provider must fail closed through the existing foveated/NR path.')]:
        assert old in s or new in s, ('Missing inherited source contract',old)
        s=s.replace(old,new)
    p.write_text(s,encoding='utf-8')
# The benchmark payload was removed deliberately. Retain every other inherited
# manifest requirement; the compiled-package audit also enforces its absence.
p=root/'runtime/open-shaders/cmake/ValidateOpenNRPackage.cmake'
if p.exists():
    s=p.read_text(encoding='utf-8-sig')
    retired='    "SKSE/Plugins/CommunityShaders/OpenNR-SettingsBenchmark.json"\n'
    assert s.count(retired) <= 1, 'Ambiguous inherited benchmark manifest entry'
    s=s.replace(retired,'')
    p.write_text(s,encoding='utf-8')
print('r7 exact source preimages/postimages passed; cleanup applied')
