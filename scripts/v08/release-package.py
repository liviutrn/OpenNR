"""Publish an audited experimental r8 package as a prerelease."""
from pathlib import Path
import hashlib,json,os,re,shutil,struct,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
TAG='opennr-2.20.1-v06-r8'

def run(argv,**kwargs): return subprocess.run(argv,check=True,**kwargs)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def inventory(root):return {p.relative_to(root).as_posix()+('/' if p.is_dir() else ''):{'size':0 if p.is_dir() else p.stat().st_size,'sha256':hashlib.sha256(b'').hexdigest() if p.is_dir() else sha(p)} for p in sorted(root.rglob('*'))}
def verify(root,manifest):
    assert inventory(root)==manifest,'Payload manifest mismatch'
    assert not any(n.lower().endswith('nvngx_dlssnr.dll') for n in manifest)
    blob=(root/'SKSE/Plugins/CommunityShaders.dll').read_bytes();offset=struct.unpack_from('<I',blob,60)[0]
    assert blob[:2]==b'MZ' and blob[offset:offset+4]==b'PE\0\0' and struct.unpack_from('<H',blob,offset+4)[0]==0x8664
    for marker in ('configureNeuralFeather','neuralFeatherStatus','configureAdaptivePerformance','configureNeuralBlackProtection'):assert marker.encode() in blob,marker

def main():
    evidence=json.loads((ROOT/'scripts/v08/build-evidence.json').read_text())
    audit=ROOT/'release-input/audit';runtime=ROOT/'release-input/runtime';output=ROOT/'release';output.mkdir(exist_ok=True)
    for name in ('r8-manifest.json','r8-package-audit.json'):
        assert sha(audit/name)==evidence[name],name
    built=json.loads((audit/'r8-package-audit.json').read_text());manifest=json.loads((audit/'r8-manifest.json').read_text())
    assert built['build_commit']==evidence['build_commit'] and built['build_run']==str(evidence['build_run'])
    assert built['nr_carrier_excluded'] and built['archive_crc_verified'] and built['all_other_r7_payloads_identical']
    archives=list(runtime.glob('*.7z'));assert len(archives)==1 and sha(archives[0])==evidence['archive_sha256']
    repo=os.environ['GITHUB_REPOSITORY'];commit=os.environ['GITHUB_SHA']
    build=json.loads(run(['gh','api',f'repos/{repo}/actions/runs/{evidence["build_run"]}'],capture_output=True,text=True).stdout)
    assert build['head_sha']==evidence['build_commit'] and build['conclusion']=='success'
    run(['git','fetch','--no-tags','--depth=1','origin',evidence['build_commit']],cwd=ROOT)
    changes=run(['git','diff','--name-only',evidence['build_commit'],commit,'--','runtime/open-shaders','VERSION','scripts'],cwd=ROOT,capture_output=True,text=True).stdout.splitlines()
    assert set(changes)<={'scripts/v08/release-package.py','scripts/v08/build-evidence.json'},('Build input drift',changes)
    assert (ROOT/'VERSION').read_text().strip()=='2.20.1'
    seven=shutil.which('7z') or r'C:\Program Files\7-Zip\7z.exe';archive=(output/'OpenNR-2.20.1-v06-r8.7z').resolve()
    with tempfile.TemporaryDirectory(prefix='opennr-r8-') as work:
        payload=Path(work)/'payload';roundtrip=Path(work)/'roundtrip'
        run([seven,'t',str(archives[0].resolve()),'-bd']);run([seven,'x',str(archives[0].resolve()),'-o'+str(payload),'-y','-bd']);verify(payload,manifest)
        (payload/'README.md').write_text((ROOT/'README.md').read_text(encoding='utf-8-sig'),encoding='utf-8',newline='\n')
        assert not re.search(r'\bliviu\b|RTX 5070|Recommended PSVR2',(payload/'README.md').read_text(),re.I)
        docs=ROOT/'docs/versions/2.20.1-v06/r8'
        for source,destination in [('CURRENT_FEATURES.md','OPENNR-2.20.1-CHANGELOG.md'),('EYE_TRACKING.md','OpenNR-EyeTracking.md')]:
            (payload/destination).write_text((docs/source).read_text(encoding='utf-8-sig'),encoding='utf-8',newline='\n')
            assert not re.search(r'\bliviu\b|RTX 5070|Recommended PSVR2',(payload/destination).read_text(),re.I)
        revised=inventory(payload);assert sorted(set(revised)-set(manifest))==['README.md']
        assert set(manifest)<=set(revised) and all(revised[n]==v for n,v in manifest.items() if n not in {'OPENNR-2.20.1-CHANGELOG.md','OpenNR-EyeTracking.md'})
        run([seven,'a','-t7z',str(archive),'*','-mx=5','-mmt=on','-mtm=off','-mta=off','-mtc=off','-bd'],cwd=payload)
        run([seven,'t',str(archive),'-bd']);run([seven,'x',str(archive),'-o'+str(roundtrip),'-y','-bd']);verify(roundtrip,revised)
        report={'version':'2.20.1-v06-r8','experimental':True,'release_commit':commit,'runtime_build_commit':evidence['build_commit'],'runtime_build_run':evidence['build_run'],'archive':{'name':archive.name,'size':archive.stat().st_size,'sha256':sha(archive)},'all_built_runtime_payloads_identical':True,'documentation_added':['README.md'],'documentation_replaced':['OPENNR-2.20.1-CHANGELOG.md','OpenNR-EyeTracking.md'],'release_roundtrip_manifest_verified':True,'nr_carrier_excluded':True,'hardware_gpu_timing_and_headset_acceptance':False}
        (output/'release-package-audit.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
        (output/'release-manifest.json').write_text(json.dumps(revised,indent=2)+'\n',encoding='utf-8',newline='\n');shutil.copyfile(payload/'README.md',output/'README.md')
    (output/'SHA256SUMS.txt').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in sorted(output.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'),encoding='ascii',newline='\n')
    assets=sorted(p for p in output.iterdir() if p.is_file())
    releases=json.loads(run(['gh','api',f'repos/{repo}/releases?per_page=100'],capture_output=True,text=True).stdout)
    matches=[r for r in releases if r['tag_name']==TAG];assert len(matches)<=1
    if not matches:
        run(['gh','release','create',TAG,'--repo',repo,'--target',evidence['build_commit'],'--draft','--prerelease','--title','OpenNR 2.20.1-v06-r8 — Experimental Neural Feather','--notes-file',str(ROOT/'docs/versions/2.20.1-v06/r8/RELEASE_NOTES.md')])
    else:
        assert matches[0]['target_commitish']==evidence['build_commit'] and matches[0]['prerelease']
        if not matches[0]['draft']:
            remote={a['name']:a for a in matches[0]['assets']};assert set(remote)=={p.name for p in assets}
            for p in assets:assert remote[p.name]['digest']=='sha256:'+sha(p)
            print('Existing prerelease verified; no assets changed');return
    run(['gh','release','upload',TAG,'--repo',repo,'--clobber',*map(str,assets)])
    release=json.loads(run(['gh','api',f'repos/{repo}/releases/tags/{TAG}'],capture_output=True,text=True).stdout)
    assert release['draft'] and release['prerelease'] and release['target_commitish']==evidence['build_commit']
    remote={a['name']:a for a in release['assets']};assert set(remote)=={p.name for p in assets}
    for p in assets:assert remote[p.name]['state']=='uploaded' and remote[p.name]['size']==p.stat().st_size and remote[p.name]['digest']=='sha256:'+sha(p)
    run(['gh','release','edit',TAG,'--repo',repo,'--draft=false','--prerelease','--latest=false'])
    tag=json.loads(run(['gh','api',f'repos/{repo}/git/ref/tags/{TAG}'],capture_output=True,text=True).stdout);assert tag['object']['sha']==evidence['build_commit'] and tag['object']['type']=='commit'
    print('RELEASE_PACKAGE_AUDIT='+json.dumps(report));print(f'RELEASE_URL=https://github.com/{repo}/releases/tag/{TAG}')
if __name__=='__main__':main()
