"""Build an isolated, aligned renderer-feature cache from audited 64-frame clips.

Never modifies captures or legacy caches. Completion is committed only after
structural/temporal gates, source-hash checks, and finite tensor checks pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image
import torch

from audit_conditioning_content import STAGES, align, decode, normals
from build_raw_crop_cache import _make_row, _guide_arrays, _split_sequence_ids


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)


def shrink(x, size):
    return np.stack([np.asarray(Image.fromarray(c.astype('float32')).resize(
        (size, size), Image.Resampling.BOX)) for c in x.transpose(2, 0, 1)])


def features(x, stage):
    if stage == 'gbuffer_normal_roughness':
        return np.concatenate((normals(x), 1-x[..., 2:3]), -1)
    if stage in ('gbuffer_masks', 'gbuffer_specular', 'gbuffer_reflectance'):
        if np.any(x < 0):
            raise ValueError('Unsigned renderer feature is negative')
        return x / (1+x)  # fixed monotonic HDR compression; no held-out fitting
    return x[..., :3] if stage == 'gbuffer_albedo' else x


def aligned_guides(row, arts):
    depth, dv, motion, mv = _guide_arrays(row)
    parts = []
    invalid = [int((~dv).sum()), int((~mv).sum())]
    for x, mask, stage in ((depth, dv, 'depth'), (motion, mv, 'motion_vectors')):
        weighted, mapping = align(x * mask[..., None], arts[stage], arts['teacher'])
        weight, _ = align(mask[..., None].astype(float), arts[stage], arts['teacher'])
        if not mapping['covered']:
            raise ValueError('Native guide crop does not cover teacher crop')
        # Invalid native samples do not bleed zero-valued guides into valid pixels.
        value = weighted / np.maximum(weight, 1e-8)
        parts.append((value * (weight > 1e-6), weight))
    return np.concatenate((parts[0][0], parts[1][0], parts[0][1], parts[1][1]), -1), invalid


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--audit', type=Path, required=True)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--expected-pass-count', type=int, choices=(1,2), default=1)
    a = p.parse_args()
    torch.set_num_threads(1)
    if a.output.exists():
        raise FileExistsError(a.output)
    if a.output.resolve().is_relative_to(a.root.resolve()):
        raise ValueError('Cache must be outside capture root')
    a.output.mkdir(parents=True)
    audit = json.loads(a.audit.read_text())
    if audit.get('expected_pass_count',1)!=a.expected_pass_count:
        raise ValueError('Audit teacher mode mismatch')
    accepted, excluded, gates = [], list(audit.get('excluded', [])), []
    for s in audit['sequences']:
        seq = a.root / s['sequence']
        errors = []
        for file, digest in s['metadata_hashes'].items():
            if sha(seq/file) != digest:
                errors.append('metadata changed: '+file)
        for tool, args in [('validate_capture.py', ['--json']),
                           ('validate_temporal_capture.py', ['--mode', 'crop','--expected-pass-count',str(a.expected_pass_count)])]:
            result = subprocess.run([sys.executable, str(Path(__file__).parent/tool), *args, str(seq)],
                                    capture_output=True, text=True)
            if result.returncode:
                errors.append(tool+' failed')
            report = json.loads(result.stdout)
            gates.append({'sequence': seq.name, 'tool': tool, 'report': report})
            if report.get('errors') or (tool.startswith('validate_temporal') and not report['temporal_ready']):
                errors.append(tool+' not ready')
        cond = [r for r in s['records'] if r['stage'] in STAGES]
        if s['frames'] != 64 or len(cond) != 64*2*6:
            errors.append('not complete 64-frame six-stage coverage')
        if any(r['nonfinite'] or not r['alignment']['covered'] for r in cond):
            errors.append('nonfinite or uncovered conditioning')
        if any(v <= 1 for v in s['unique_hashes'].values()):
            errors.append('unchanging entire stream requires manual review')
        if errors:
            excluded.append({'sequence': seq.name, 'reasons': errors})
        else:
            accepted.append({'sequence_id': seq.name, 'created_utc':
                json.loads((seq/'sequence.json').read_text())['created_utc']})
        print(json.dumps({'sequence': seq.name, 'errors': errors}), flush=True)
    save(a.output/'gates.json', {'checks': gates, 'excluded': excluded})
    if len(accepted) < 5:
        raise ValueError('Too few accepted sequences for bounded pilot')
    split = _split_sequence_ids(accepted)
    membership = {s: name for name in ('train','validation','test') for s in split[name]}
    rows, source_hashes, manifests = [], {}, {}
    audit_records = {(s['sequence'], r['frame'], r['eye'], r['stage']): r['sha256']
                     for s in audit['sequences'] for r in s['records']}
    for s in accepted:
        seq = a.root/s['sequence_id']
        frames = [json.loads(line) for line in (seq/'frames.jsonl').read_text().splitlines()]
        manifests[seq.name] = frames
        source_hashes[seq.name] = {f:sha(seq/f) for f in ('sequence.json','frames.jsonl')}
        for f in frames:
            for eye in (0,1):
                rows.append(_make_row(seq, seq.name, f, eye, membership[seq.name]))
    # Exact duplicate color/teacher pairs must not cross holdouts.
    seen = {}
    for row in rows:
        key = tuple(audit_records[row['sequence_id'],row['frame_id'],row['eye'],stage]
                    for stage in ('input','teacher'))
        if key in seen and seen[key] != row['split']:
            raise ValueError('Exact input/teacher pair crosses holdouts')
        seen[key] = row['split']
    save(a.output/'rows.json', rows)
    save(a.output/'split.json', split)
    n = len(rows)
    arrays = {name:np.lib.format.open_memmap(a.output/(name+'.npy'), mode='w+', dtype=dtype,
                                           shape=(n,*shape)) for name,dtype,shape in [
        ('rgb','u1',(2,3,512,512)), ('guides','<f2',(5,128,128)),
        ('context','<f2',(8,96,96)), ('conditioning','<f2',(17,128,128))]}
    invalid = np.zeros(2, dtype=np.int64)
    payload_hashes = []
    for i,row in enumerate(rows):
        seq = a.root/row['sequence_id']
        f = manifests[seq.name][row['frame_id']-1]
        arts = {v['stage']:v for v in f['artifacts'] if v['eye']==row['eye']
                and v['crop_index']==0 and not v['full_frame']}
        condition = []
        for stage in ['input','teacher']+STAGES:
            x,h = decode(seq/arts[stage]['raw_path'], arts[stage])
            if h != audit_records[seq.name,row['frame_id'],row['eye'],stage]:
                raise ValueError('Payload changed after audit')
            payload_hashes.append(h)
            if not np.isfinite(x).all():
                raise ValueError('Nonfinite source')
            if stage in STAGES:
                x = features(x,stage)
                x,mapping = align(x,arts[stage],arts['teacher'])
                if not mapping['covered']:
                    raise ValueError('Conditioning crop uncovered')
                condition.append(shrink(x,128))
            else:
                arrays['rgb'][i,0 if stage=='input' else 1] = np.rint(x.transpose(2,0,1)*255).astype('uint8')
        g,bad = aligned_guides(row,arts)
        invalid += bad
        arrays['guides'][i] = shrink(g,128)
        rgb = arrays['rgb'][i,0].transpose(1,2,0).astype('float32')/255
        arrays['context'][i] = np.concatenate((shrink(rgb,96),shrink(g,96)))
        arrays['conditioning'][i] = np.concatenate(condition)
        for key in ('guides','context','conditioning'):
            if not np.isfinite(arrays[key][i]).all():
                raise ValueError('Nonfinite cache tensor '+key)
        if (i+1)%128==0:
            for value in arrays.values(): value.flush()
            print(f'prepared {i+1}/{n} eye rows',flush=True)
    for s,hashes in source_hashes.items():
        for file,digest in hashes.items():
            if sha(a.root/s/file) != digest: raise ValueError('Capture changed during preparation')
    complete = {'schema':'opennr-aligned-renderer-pilot-v1','rows':n,'split':split,'teacher_pass_count':a.expected_pass_count,
        'source_root':str(a.root.resolve()),'source_hashes':source_hashes,
        'audit_sha256':sha(a.audit),'payload_hashes_sha256':hashlib.sha256(''.join(payload_hashes).encode()).hexdigest(),
        'rows_sha256':sha(a.output/'rows.json'),'excluded':excluded,'invalid_native_guide_pixels':invalid.tolist(),
        'channel_order':['albedo_rgb','normal_xyz_roughness','masks_rgb','masks2_r','specular_rgb','reflectance_rgb'],
        'conditioning_channels':17,'normalization':'UNORM unchanged, signed decoded normals; float x/(1+x)',
        'alignment':'all native guides and conditionings mapped to teacher crop before fixed BOX downsampling',
        'test_used_for_tuning':False,'scope':'new session pilot; no old cache modification; chronological holdouts are not independent scene/session proof'}
    for v in arrays.values(): v.flush()
    complete['array_sha256'] = {key:sha(a.output/(key+'.npy')) for key in arrays}
    save(a.output/'complete.json',complete)
    print(json.dumps(complete),flush=True)


if __name__ == '__main__': main()
