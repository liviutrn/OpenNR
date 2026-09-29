"""Prepare immutable-source training references from a completed master audit."""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('audit',type=Path); args=p.parse_args()
    summary=json.loads((args.audit/'summary.json').read_text()); root=Path(summary['root'])
    reports=[json.loads(p.read_text()) for p in sorted((args.audit/'sequences').glob('*.json'))]
    if len(reports)!=summary['sequences']: raise ValueError('incomplete audit')
    # The second game process is held out. The final four sequences of process 1
    # form validation; the preceding two sequences are a guard band.
    sessions=[]; last=None
    for r in reports:
        created=r['metadata']['created_utc']
        if last is None or created-last>600000: sessions.append([])
        sessions[-1].append(r['sequence_id']); last=created
    if len(sessions)!=2: raise ValueError('Review session split for this dataset; expected two sessions')
    split={s:'train' for s in sessions[0]}
    split.update({s:'validation' for s in sessions[0][-4:]})
    split.update({s:'guard' for s in sessions[0][-6:-4]})
    split.update({s:'test' for s in sessions[1]})
    rows=[]; excluded=[]; duplicates=[]; seen={}; manifest_parts=[]; counts=Counter(); artifact_counts=Counter(); bytes_total=0
    guide=defaultdict(Counter); errors=[]; thumbnails=[]
    for r in reports:
        sid=r['sequence_id']; seq=root/sid
        if hashlib.sha256((seq/'sequence.json').read_bytes()).hexdigest()!=r['sequence_sha256'] or hashlib.sha256((seq/'frames.jsonl').read_bytes()).hexdigest()!=r['manifest_sha256']:
            raise ValueError(f'source metadata changed after audit: {sid}')
        manifest_parts.extend([r['sequence_sha256'],r['manifest_sha256']])
        frames={}
        for line in (seq/'frames.jsonl').read_text().splitlines():
            try:
                f=json.loads(line); frames[f['frame_id']]=f
            except json.JSONDecodeError: pass
        for line in (args.audit/'artifacts'/(sid+'.jsonl')).read_text().splitlines():
            a=json.loads(line); artifact_counts['artifacts']+=1
            for kind in ('raw','png'):
                if kind in a:
                    artifact_counts[kind]+=1; bytes_total+=a[kind]['bytes']; manifest_parts.append(a[kind]['sha256'])
        for f in r['frames']:
            fid=f['frame_id']; reasons=list(f['errors'])
            full=f.get('full_hashes',{})
            for stage in ('input','teacher'):
                if full.get(stage+'_eye0') and full.get(stage+'_eye0')==full.get(stage+'_eye1'):
                    reasons.append(f'identical stereo {stage}')
            if any(m['identical'] for m in f['pair_metrics']): reasons.append('identity teacher')
            if any('all-black input' in w or 'all-black teacher' in w for w in f['warnings']): reasons.append('black color artifact; manual review required')
            frame_hash=tuple(full.get(s+'_eye'+str(e)) for s in ('input','teacher') for e in (0,1))
            if all(frame_hash):
                if frame_hash in seen:
                    duplicates.append(dict(sequence_id=sid,frame_id=fid,duplicate_of=seen[frame_hash])); reasons.append('exact duplicate stereo color sample')
                else: seen[frame_hash]=dict(sequence_id=sid,frame_id=fid,split=split[sid])
            for g in f['guide_stats']:
                for key in ('count','nonfinite','zeros','outlier_components'):
                    if g.get(key) is not None: guide[g['stage']][key]+=g[key]
            if reasons or split[sid]=='guard':
                excluded.append(dict(sequence_id=sid,frame_id=fid,reasons=reasons or ['split guard band']))
                continue
            frame=frames[fid]; counts[split[sid]+'_frames']+=1
            for eye in (0,1):
                arts={a['stage']:a for a in frame['artifacts'] if a.get('full_frame') and a['eye']==eye}
                paths={s:str((seq/a['png_path' if s in ('input','teacher') else 'raw_path']).resolve()) for s,a in arts.items() if s in ('input','teacher','depth','motion_vectors')}
                rows.append(dict(schema_version=1,sequence_id=sid,frame_id=fid,host_frame=frame['host_frame'],eye=eye,split=split[sid],color_size=[frame['color_width'],frame['color_height']],guide_size=[frame['guide_width'],frame['guide_height']],paths=paths,motion_scale=[frame['motion_vector_scale_x'][eye],frame['motion_vector_scale_y'][eye]],history_reset=frame['history_reset'][eye],teacher_settings=frame['teacher_settings'],temporal_training_eligible=False))
        preview=args.audit/'previews'/(sid+'.jpg')
        if preview.exists():
            with Image.open(preview) as im:
                # Middle sampled stereo row; preserve both eyes and both stages.
                y=300 if im.height>=900 else 0
                thumb=im.crop((0,y,960,y+300)); thumb.thumbnail((640,200))
            tile=Image.new('RGB',(640,224),(20,20,20)); tile.paste(thumb,(0,24)); ImageDraw.Draw(tile).text((5,5),f'{sid} | {split[sid]}',fill='white'); thumbnails.append(tile)
    (args.audit/'training_manifest.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (args.audit/'exclusions.json').write_text(json.dumps(excluded,indent=2))
    (args.audit/'duplicates.json').write_text(json.dumps(duplicates,indent=2))
    (args.audit/'split_manifest.json').write_text(json.dumps(dict(sessions=sessions,sequence_split=split,policy='process-2 test; process-1 last four sequences validation; preceding two guard; scene novelty unverified'),indent=2))
    gaps=[f['host_frame_gap'] for r in reports for f in r['frames'] if 'host_frame_gap' in f]
    stats=dict(**summary,prepared_stereo_frames=len(rows)//2,eye_pairs=len(rows),fixed_512_patches=len(rows)*4,counts=counts,sequence_split_counts=Counter(split.values()),exclusions=len(excluded),duplicates=len(duplicates),artifact_counts=artifact_counts,referenced_bytes=bytes_total,guide_stats=guide,host_gap_percentiles=dict(zip(('min','p50','p95','max'),map(float,np.percentile(gaps,[0,50,95,100])))),consecutive_record_pairs=sum(g==1 for g in gaps),dataset_sha256=hashlib.sha256(''.join(manifest_parts).encode()).hexdigest(),temporal_ready=False,scene_disjoint_split_verified=False)
    (args.audit/'prepared_summary.json').write_text(json.dumps(stats,indent=2))
    for page,start in enumerate(range(0,len(thumbnails),8),1):
        sheet=Image.new('RGB',(1280,224*4),(15,15,15))
        for i,tile in enumerate(thumbnails[start:start+8]): sheet.paste(tile,((i%2)*640,(i//2)*224))
        sheet.save(args.audit/'previews'/f'overview_{page:02}.jpg',quality=92)
    html=['<html><head><meta charset="utf-8"><title>OpenNR full-resolution audit</title></head><body style="background:#151515;color:#eee;font-family:Arial"><h1>OpenNR full-resolution audit</h1><p>Each sequence: first, middle and final committed record; input left, teacher left, input right, teacher right. Failed files are listed separately in exclusions.json. Sampled visual review, exhaustive binary audit.</p>']
    for r in reports:
        sid=r['sequence_id']; html.append(f'<h2>{sid} — {split[sid]}</h2><p>{len(r["frames"])} records; {len(r["orphan_files"])} orphan files</p><img loading="lazy" width="960" src="previews/{sid}.jpg">')
    (args.audit/'index.html').write_text('\n'.join(html)+'</body></html>',encoding='utf-8')
    print(json.dumps(stats,indent=2))

if __name__=='__main__': main()
