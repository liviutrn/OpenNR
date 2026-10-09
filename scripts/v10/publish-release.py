"""Publish only the exact archive from a successful, matching audited r10 build."""
import argparse,hashlib,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run',required=True,type=int);p.add_argument('--commit',required=True)
args=p.parse_args();repository='liviutrn/OpenNR'
run=json.loads(subprocess.check_output(['gh','api',f'repos/{repository}/actions/runs/{args.run}'],text=True,encoding='utf-8'))
assert run['conclusion']=='success' and run['head_sha']==args.commit,'Build does not match reviewed release'
runtime=Path('release-input/runtime');auditRoot=Path('release-input/audit')
audit=json.loads((auditRoot/'r10-package-audit.json').read_text(encoding='utf-8-sig'))
assert audit['build_commit']==args.commit and int(audit['build_run'])==args.run
assert audit['archive_crc_verified'] and audit['nr_carrier_excluded']
assert audit['x64_dll_and_controls_verified'] and audit['all_other_r6_payloads_identical']
archives=list(runtime.glob('*.7z'));assert len(archives)==1
archive=archives[0];record=audit['archives']['r10']
assert archive.name==record['name'] and archive.stat().st_size==record['size']
digest=hashlib.sha256(archive.read_bytes()).hexdigest();assert digest==record['sha256']
tag='opennr-2.20.1-v06-r10-stable'
notes=Path('release-input/RELEASE_NOTES.md')
notes.write_text(Path('docs/versions/2.20.1-v06/r10/README.md').read_text(encoding='utf-8-sig').replace('(REVIEW.md)',
 '(https://github.com/liviutrn/OpenNR/blob/'+args.commit+'/docs/versions/2.20.1-v06/r10/REVIEW.md)'),encoding='utf-8')
report=Path('release-input/release-verification.json')
report.write_text(json.dumps({'build_run':args.run,'build_commit':args.commit,'archive':archive.name,
 'sha256':digest,'audited_archive_unchanged':True,'headset_and_hardware_gpu_validation':False},indent=2)+'\n',encoding='utf-8')
checksum=Path('release-input/SHA256SUMS.txt');checksum.write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
subprocess.run(['gh','release','create',tag,'--repo',repository,'--target',args.commit,
 '--title','OpenNR 2.20.1-v06-r10 stable','--notes-file',str(notes),str(archive),str(checksum),
 str(auditRoot/'r10-package-audit.json'),str(auditRoot/'r10-source-audit.json'),str(report),
 'docs/versions/2.20.1-v06/r10/REVIEW.md'],check=True)
print('Published verified r10 stable archive: '+digest)
