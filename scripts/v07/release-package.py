"""Publish the verified r7 runtime with current documentation and no NR carrier."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile

BUILD_SHA = '3a005b981acb178e624c782c571c422f6daeeddd'
BUILD_RUN = '37738693746'
ARCHIVE_SHA = '274ae5e34f13d3772625e28507ee17853ae30abeaff2aa7ba26845ea08c8f472'
MANIFEST_SHA = '3ae8b0222d7dd6bd0b7e1d02a8af4bcacfb3e0ff07e5fa390b99ee4a462aa658'
AUDIT_SHA = 'f0f84fcc6af58f12c262da56c1e9bca0ac8149ffbbdbcf1b49c937452365f816'
TAG = 'opennr-2.20.1-v06-r7'
DOCS = {'README.md', 'OpenNR-EyeTracking.md', 'OPENNR-2.20.1-CHANGELOG.md'}
ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def inventory(root):
    return {p.relative_to(root).as_posix() + ('/' if p.is_dir() else ''):
            {'size': 0 if p.is_dir() else p.stat().st_size,
             'sha256': hashlib.sha256(b'').hexdigest() if p.is_dir() else sha(p)}
            for p in sorted(root.rglob('*'))}


def verify_payload(payload, expected):
    actual = inventory(payload)
    assert actual == expected, 'Extracted payload does not match its manifest'
    assert not any(n.lower().endswith('nvngx_dlssnr.dll') for n in actual)
    blob = (payload/'SKSE/Plugins/CommunityShaders.dll').read_bytes()
    offset = struct.unpack_from('<I', blob, 60)[0]
    assert blob[:2] == b'MZ' and blob[offset:offset+4] == b'PE\0\0'
    assert struct.unpack_from('<H', blob, offset+4)[0] == 0x8664
    for marker in ('Adaptive Performance', 'Controller mode', 'Force stage 6 (NR off)',
                   'Crop reduction per step', 'Disable NR above (stage 5 only)',
                   'Re-enable NR below (stage 6 only)', 'configureAdaptivePerformance',
                   'configureNeuralBlackProtection', 'NR near-black protection'):
        assert marker.encode() in blob, marker
    for marker in ('configureOutsideTone', 'Start settings benchmark',
                   'startSettingsBenchmark', 'Force one-pass atlas'):
        assert marker.encode() not in blob, marker
    return actual


def write_document(source, destination):
    destination.write_text(source.read_text(encoding='utf-8-sig'), encoding='utf-8', newline='\n')


def verify_provenance(commit):
    run(['git', 'fetch', '--no-tags', '--depth=1', 'origin', BUILD_SHA], cwd=ROOT)
    changed = run(['git', 'diff', '--name-only', BUILD_SHA, commit, '--',
                   'runtime/open-shaders', 'VERSION', 'scripts'], cwd=ROOT,
                  capture_output=True, text=True).stdout.splitlines()
    assert set(changed) <= {'scripts/v07/release-package.py'}, ('Runtime/build inputs changed', changed)
    assert (ROOT/'VERSION').read_text().strip() == '2.20.1'


def publish(output, commit):
    repo = os.environ['GITHUB_REPOSITORY']
    assets = sorted(p for p in output.iterdir() if p.is_file())
    releases = json.loads(run(['gh', 'api', f'repos/{repo}/releases?per_page=100'],
                              capture_output=True, text=True).stdout)
    matches = [r for r in releases if r['tag_name'] == TAG]
    assert len(matches) <= 1, 'Duplicate release records'
    if matches:
        existing = matches[0]
        if not existing['draft']:
            assert existing['target_commitish'] == commit, 'Release tag belongs to another commit'
            tag = json.loads(run(['gh', 'api', f'repos/{repo}/git/ref/tags/{TAG}'],
                                 capture_output=True, text=True).stdout)
            assert tag['object']['sha'] == commit and tag['object']['type'] == 'commit'
            remote = {a['name']: a for a in existing['assets']}
            assert set(remote) == {p.name for p in assets}, 'Published asset list differs'
            for p in assets:
                assert remote[p.name]['state'] == 'uploaded'
                assert remote[p.name]['size'] == p.stat().st_size
                assert remote[p.name]['digest'] == 'sha256:' + sha(p), p.name
            print('Published release already matches; no assets changed')
            return
        assert existing['author']['login'] == 'github-actions[bot]'
        assert existing['target_commitish'] in (commit, '61f78c213679e070064dfe65636cefc520870491')
        tag = subprocess.run(['gh', 'api', f'repos/{repo}/git/ref/tags/{TAG}'], capture_output=True, text=True)
        if tag.returncode == 0:
            assert json.loads(tag.stdout)['object']['sha'] == commit, 'Existing tag cannot be retargeted'
        else:
            assert '404' in tag.stderr or 'Not Found' in tag.stdout, tag.stderr
        run(['gh', 'release', 'edit', TAG, '--repo', repo, '--target', commit,
             '--notes-file', str(ROOT/'docs/versions/2.20.1-v06/r7/RELEASE_NOTES.md')])
    else:
        run(['gh', 'release', 'create', TAG, '--repo', repo, '--target', commit,
             '--draft', '--title', 'OpenNR 2.20.1-v06-r7 — Stereo Atlas and Adaptive Performance',
             '--notes-file', str(ROOT/'docs/versions/2.20.1-v06/r7/RELEASE_NOTES.md')])
    run(['gh', 'release', 'upload', TAG, '--repo', repo, '--clobber', *map(str, assets)])
    releases = json.loads(run(['gh', 'api', f'repos/{repo}/releases?per_page=100'],
                              capture_output=True, text=True).stdout)
    matches = [r for r in releases if r['tag_name'] == TAG]
    assert len(matches) == 1
    current = json.loads(run(['gh', 'api', f'repos/{repo}/releases/{matches[0]["id"]}'],
                            capture_output=True, text=True).stdout)
    assert current['draft'] and current['target_commitish'] == commit
    remote = {a['name']: a for a in current['assets']}
    assert set(remote) == {p.name for p in assets}
    for p in assets:
        assert remote[p.name]['state'] == 'uploaded'
        assert remote[p.name]['size'] == p.stat().st_size
        assert remote[p.name]['digest'] == 'sha256:' + sha(p), p.name
    run(['gh', 'release', 'edit', TAG, '--repo', repo, '--draft=false', '--latest'])
    print(f'RELEASE_URL=https://github.com/{repo}/releases/tag/{TAG}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT/'release')
    parser.add_argument('--verify-only', type=Path, metavar='EXTRACTED_PAYLOAD')
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    manifest_path = args.audit/'r7-manifest.json'
    audit_path = args.audit/'r7-package-audit.json'
    assert sha(manifest_path) == MANIFEST_SHA and sha(audit_path) == AUDIT_SHA
    built = json.loads(audit_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    assert built['build_commit'] == BUILD_SHA and built['build_run'] == BUILD_RUN
    assert built['archive_crc_verified'] and built['nr_carrier_excluded']
    assert built['shader_matches_reviewed_source'] and built['x64_dll_and_controls_verified']
    archives = list(args.artifact.glob('*.7z'))
    assert len(archives) == 1 and sha(archives[0]) == ARCHIVE_SHA
    if args.verify_only:
        verify_payload(args.verify_only, manifest)
        print('Independent release verification passed: every compiled payload, x64 controls and NR exclusion')
        return
    commit = os.environ['GITHUB_SHA']
    verify_provenance(commit)
    seven = shutil.which('7z') or shutil.which('7zz') or r'C:\Program Files\7-Zip\7z.exe'
    assert Path(seven).is_file()
    args.output.mkdir(parents=True, exist_ok=True)
    archive = (args.output/'OpenNR-2.20.1-v06-r7.7z').resolve()
    with tempfile.TemporaryDirectory(prefix='r7-release-') as work:
        payload = Path(work)/'payload'
        roundtrip = Path(work)/'roundtrip'
        run([seven, 't', str(archives[0].resolve()), '-bd'])
        run([seven, 'x', str(archives[0].resolve()), '-o'+str(payload), '-y', '-bd'])
        verify_payload(payload, manifest)
        docs = ROOT/'docs/versions/2.20.1-v06/r7'
        write_document(ROOT/'README.md', payload/'README.md')
        write_document(docs/'EYE_TRACKING.md', payload/'OpenNR-EyeTracking.md')
        write_document(docs/'CURRENT_FEATURES.md', payload/'OPENNR-2.20.1-CHANGELOG.md')
        revised = inventory(payload)
        added = sorted(set(revised)-set(manifest))
        removed = sorted(set(manifest)-set(revised))
        changed = sorted(n for n in set(manifest)&set(revised) if manifest[n] != revised[n])
        assert added == ['README.md'] and not removed
        assert changed == ['OPENNR-2.20.1-CHANGELOG.md', 'OpenNR-EyeTracking.md']
        assert all(revised[n] == v for n,v in manifest.items() if n not in DOCS)
        feature_inis = sorted(n for n in revised if n.startswith('Shaders/Features/') and n.endswith('.ini'))
        normalize = lambda s: re.sub('[^a-z0-9]', '', s.lower())
        guide = normalize((payload/'README.md').read_text(encoding='utf-8'))
        assert len(feature_inis) == 52
        assert all(normalize(Path(n).stem) in guide for n in feature_inis), 'Feature inventory incomplete'
        run([seven, 'a', '-t7z', str(archive), '*', '-mx=5', '-mmt=on',
             '-mtm=off', '-mta=off', '-mtc=off', '-bd'], cwd=payload)
        run([seven, 't', str(archive), '-bd'])
        run([seven, 'x', str(archive), '-o'+str(roundtrip), '-y', '-bd'])
        verify_payload(roundtrip, revised)
        report = {'version': '2.20.1-v06-r7', 'release_commit': commit,
                  'runtime_build_commit': BUILD_SHA, 'runtime_build_run': BUILD_RUN,
                  'verified_source_archive_sha256': ARCHIVE_SHA,
                  'release_archive': {'name': archive.name, 'size': archive.stat().st_size, 'sha256': sha(archive)},
                  'archive_entries': len(revised), 'documentation_added': added,
                  'documentation_replaced': changed, 'removed_payloads': removed,
                  'all_built_runtime_payloads_identical': True, 'all_bundled_dependencies_identical': True,
                  'x64_plugin_and_controls_verified': True, 'original_and_release_crc_verified': True,
                  'release_roundtrip_manifest_verified': True, 'nr_carrier_excluded': True,
                  'nr_carrier_install_path': 'Data/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll',
                  'included_feature_inis': feature_inis,
                  'hardware_gpu_timing_and_headset_acceptance': False}
        (args.output/'release-package-audit.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8', newline='\n')
        (args.output/'release-manifest.json').write_text(json.dumps(revised, indent=2)+'\n', encoding='utf-8', newline='\n')
        shutil.copyfile(payload/'README.md', args.output/'README.md')
    sums = '\n'.join(sha(p)+'  '+p.name for p in sorted(args.output.iterdir()) if p.is_file() and p.name != 'SHA256SUMS.txt')+'\n'
    (args.output/'SHA256SUMS.txt').write_text(sums, encoding='ascii', newline='\n')
    print('RELEASE_PACKAGE_AUDIT='+json.dumps(report, separators=(',', ':')))
    if args.publish:
        publish(args.output.resolve(), commit)


if __name__ == '__main__':
    main()
