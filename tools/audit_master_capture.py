"""Exhaustively read master captures without modifying the source recording.

Writes per-artifact hashes/statistics, per-frame decisions, orphan inventory,
and representative stereo contact sheets. Raw tensors are tightly packed;
the recorded D3D row pitch is diagnostic, not the on-disk stride.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image, ImageDraw

STAGES = ('input', 'teacher', 'depth', 'motion_vectors')

def digest(data):
    return hashlib.sha256(data).hexdigest()

def audit_sequence(seq: Path, output: Path):
    meta = json.loads((seq / 'sequence.json').read_text())
    result = dict(sequence_id=seq.name, metadata=meta, frames=[], errors=[], orphan_files=[])
    referenced = set()
    previous = None
    artifact_log = (output / 'artifacts' / (seq.name + '.jsonl')).open('w')
    raw_manifest = (seq / 'frames.jsonl').read_bytes() if (seq / 'frames.jsonl').exists() else b''
    result['manifest_sha256'] = digest(raw_manifest)
    result['sequence_sha256'] = digest((seq / 'sequence.json').read_bytes())
    result['manifest_ends_newline'] = raw_manifest.endswith(b'\n')
    preview_rows = []
    lines = raw_manifest.splitlines()
    preview_indices = {0, len(lines)//2, len(lines)-1}
    for li, line in enumerate(lines):
        try:
            frame = json.loads(line)
        except Exception as exc:
            result['errors'].append(f'line {li+1}: {exc}')
            continue
        row = {k:v for k,v in frame.items() if k != 'artifacts'}
        row.update(errors=[], warnings=[], guide_stats=[], pair_metrics=[])
        fid = frame.get('frame_id')
        identity = (fid, frame.get('sample_index'), frame.get('host_frame'))
        if previous is not None:
            row['host_frame_gap'] = identity[2] - previous[2]
            if any(a <= b for a,b in zip(identity, previous)):
                row['errors'].append('non-increasing frame/sample/host identity')
        previous = identity
        if frame.get('sequence_id') != seq.name or frame.get('schema_version') != 2:
            row['errors'].append('sequence identity or schema mismatch')
        if frame.get('status') != 'complete':
            row['errors'].append('frame not committed complete')
        if frame.get('route') != 'feature18_stereo' or frame.get('model_resolution_percent') != 100 or frame.get('pass_count') != 1:
            row['errors'].append('unexpected teacher route/resolution/pass count')
        arts = frame.get('artifacts', [])
        keys = [(a['stage'], a['eye'], bool(a.get('full_frame')), a['crop_index']) for a in arts]
        if len(keys) != len(set(keys)):
            row['errors'].append('duplicate artifact key')
        for stage in STAGES:
            for eye in (0,1):
                for full,crop in [(True,0)] + [(False,i) for i in range(meta['crop_count'])]:
                    if (stage,eye,full,crop) not in keys:
                        row['errors'].append(f'missing {stage}/{eye}/{full}/{crop}')
        full_arrays = {}
        hashes = {}
        for a in arts:
            ar = dict(sequence_id=seq.name, frame_id=fid, stage=a['stage'], eye=a['eye'], full_frame=a.get('full_frame',False), crop_index=a['crop_index'], width=a['width'], height=a['height'], format=a['format'], errors=[])
            data_by_kind = {}
            for kind in ('raw','png'):
                if not a.get(kind+'_required', True):
                    continue
                rel = a.get(kind+'_path', '')
                p = (seq / rel).resolve()
                if not rel or not p.is_relative_to(seq.resolve()):
                    ar['errors'].append(f'unsafe {kind} path')
                    continue
                referenced.add(p)
                try:
                    before = p.stat()
                    data = p.read_bytes()
                    after = p.stat()
                    if (before.st_size,before.st_mtime_ns) != (after.st_size,after.st_mtime_ns):
                        raise ValueError('file changed during audit')
                    ar[kind] = dict(path=rel, bytes=len(data), sha256=digest(data), mtime_ns=after.st_mtime_ns)
                    data_by_kind[kind] = data
                    if not a.get(kind+'_written',False):
                        ar['errors'].append(f'{kind} write flag false')
                except Exception as exc:
                    ar['errors'].append(f'{kind}: {exc}')
            try:
                w,h = a['width'],a['height']
                formats = {28:('u1',4), 41:('<f4',1), 34:('<f2',2)}
                dtype,channels = formats[a['format']]
                raw = data_by_kind['raw']
                expected = w*h*channels*np.dtype(dtype).itemsize
                if len(raw) != expected:
                    raise ValueError(f'raw size {len(raw)} != {expected}')
                arr = np.frombuffer(raw, dtype=dtype).reshape(h,w,channels)
                if 'png' in data_by_kind:
                    with Image.open(io.BytesIO(data_by_kind['png'])) as im:
                        im.verify()
                    with Image.open(io.BytesIO(data_by_kind['png'])) as im:
                        if im.size != (w,h) or im.mode != 'RGB':
                            raise ValueError('PNG dimensions/mode mismatch')
                        rgb = np.asarray(im)
                        if not np.array_equal(rgb,arr[:,:,:3]):
                            raise ValueError('PNG differs from raw RGB')
                    ar['rgb_std'] = float(rgb.std())
                    ar['rgb_mean'] = float(rgb.mean())
                    ar['black_fraction'] = float(np.mean(np.all(rgb == 0,axis=2)))
                    if not rgb.any():
                        row['warnings'].append(f'all-black {a["stage"]} eye{a["eye"]} full={a.get("full_frame")}')
                else:
                    vals = arr.astype(np.float32)
                    finite = np.isfinite(vals)
                    good = vals[finite]
                    ar['tensor'] = dict(count=vals.size, nonfinite=int((~finite).sum()), zeros=int((vals==0).sum()), min=float(good.min()) if good.size else None, max=float(good.max()) if good.size else None, mean=float(good.mean()) if good.size else None, std=float(good.std()) if good.size else None, outlier_components=int((np.abs(good) > .25).sum()) if a['stage']=='motion_vectors' else None)
                    if a.get('full_frame'):
                        row['guide_stats'].append(dict(stage=a['stage'],eye=a['eye'],**ar['tensor']))
                if a.get('full_frame'):
                    full_arrays[(a['stage'],a['eye'])] = arr
                    hashes[(a['stage'],a['eye'])] = ar['raw']['sha256']
                cr,sr = a['crop_rect'],a['source_rect']
                if cr['width'] != w or cr['height'] != h or cr['x'] < sr['x'] or cr['y'] < sr['y'] or cr['x']+w > sr['x']+sr['width'] or cr['y']+h > sr['y']+sr['height']:
                    raise ValueError('crop/source bounds mismatch')
                if a.get('full_frame') and cr != sr:
                    raise ValueError('full frame is not complete source rectangle')
            except Exception as exc:
                ar['errors'].append(str(exc))
            row['errors'].extend(f'{a["stage"]}/eye{a["eye"]}/full={a.get("full_frame")}/crop{a["crop_index"]}: {e}' for e in ar['errors'])
            artifact_log.write(json.dumps(ar)+'\n')
        # Compare every native crop to its corresponding master, byte for byte.
        for a in arts:
            if a.get('full_frame') or (a['stage'],a['eye']) not in full_arrays:
                continue
            master = full_arrays[(a['stage'],a['eye'])]
            cr,sr = a['crop_rect'],a['source_rect']
            x,y = cr['x']-sr['x'],cr['y']-sr['y']
            p=(seq/a['raw_path']).resolve()
            if p.is_relative_to(seq.resolve()) and p.is_file():
                if digest(master[y:y+a['height'],x:x+a['width']].tobytes()) != digest(p.read_bytes()):
                    row['errors'].append(f'crop differs from master: {a["raw_path"]}')
        for eye in (0,1):
            if ('input',eye) in full_arrays and ('teacher',eye) in full_arrays:
                inp=full_arrays['input',eye][:,:,:3]
                target=full_arrays['teacher',eye][:,:,:3]
                delta=(target.astype(np.float32)-inp.astype(np.float32))/255
                row['pair_metrics'].append(dict(eye=eye,mae=float(np.abs(delta).mean()),mse=float(np.square(delta).mean()),identical=hashes['input',eye]==hashes['teacher',eye]))
        row['full_hashes'] = {f'{s}_eye{e}':v for (s,e),v in hashes.items()}
        row['spatial_structurally_valid'] = not row['errors']
        if li in preview_indices and all((s,e) in full_arrays for s in ('input','teacher') for e in (0,1)):
            tile=Image.new('RGB',(960,300),(22,22,22)); draw=ImageDraw.Draw(tile)
            for column,(stage,eye) in enumerate((('input',0),('teacher',0),('input',1),('teacher',1))):
                im=Image.fromarray(full_arrays[stage,eye][:,:,:3]); im.thumbnail((236,260))
                tile.paste(im,(column*240,35)); draw.text((column*240+3,6),f'{stage} eye{eye} frame {fid}',fill='white')
            preview_rows.append(tile)
        result['frames'].append(row)
    artifact_log.close()
    for p in (seq/'frames').rglob('*'):
        if p.is_file() and p.resolve() not in referenced:
            result['orphan_files'].append(dict(path=str(p.relative_to(seq)),bytes=p.stat().st_size,sha256=digest(p.read_bytes())))
    if preview_rows:
        sheet=Image.new('RGB',(960,300*len(preview_rows)))
        for i,tile in enumerate(preview_rows): sheet.paste(tile,(0,i*300))
        sheet.save(output/'previews'/(seq.name+'.jpg'),quality=90)
    (output/'sequences'/(seq.name+'.json')).write_text(json.dumps(result,indent=2))
    print(f'{seq.name}: {len(result["frames"])} frames, {sum(bool(f["errors"]) for f in result["frames"])} invalid, {len(result["orphan_files"])} orphans',flush=True)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('root',type=Path); p.add_argument('output',type=Path); p.add_argument('--workers',type=int,default=3); args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    for sub in ('artifacts','sequences','previews'): (args.output/sub).mkdir(exist_ok=True)
    start=time.time(); seqs=sorted(x.parent for x in args.root.glob('*/sequence.json'))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        reports=list(pool.map(lambda s:audit_sequence(s,args.output),seqs))
    summary=dict(root=str(args.root.resolve()),sequences=len(reports),frames=sum(len(r['frames']) for r in reports),invalid_frames=sum(bool(f['errors']) for r in reports for f in r['frames']),orphan_files=sum(len(r['orphan_files']) for r in reports),elapsed_seconds=time.time()-start,sequence_errors={r['sequence_id']:r['errors'] for r in reports if r['errors']})
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2)); print(json.dumps(summary),flush=True)

if __name__=='__main__': main()
