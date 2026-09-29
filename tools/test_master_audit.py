"""Crash-tail and corruption regression fixtures for the exhaustive auditor."""
import json
from pathlib import Path
import tempfile
import numpy as np
from PIL import Image
from audit_master_capture import audit_sequence

def main():
    with tempfile.TemporaryDirectory(prefix='opennr-audit-test-') as tmp:
        root=Path(tmp); seq=root/'seq-test'; seq.mkdir(); (seq/'frames').mkdir()
        out=root/'out'; out.mkdir()
        for sub in ('artifacts','sequences','previews'): (out/sub).mkdir()
        (seq/'sequence.json').write_text(json.dumps(dict(crop_count=1)))
        artifacts=[]
        for eye in (0,1):
            for stage,fmt,dtype,ch in (('input',28,'u1',4),('teacher',28,'u1',4),('depth',41,'<f4',1),('motion_vectors',34,'<f2',2)):
                master=np.full((4,4,ch),.1 if fmt!=28 else 60+eye+(stage=='teacher')*10,dtype=dtype)
                for full in (False,True):
                    size=4 if full else 2; arr=master[:size,:size]
                    stem=f'frames/{stage}_{eye}_{full}'; (seq/(stem+'.bin')).write_bytes(arr.tobytes())
                    png=fmt==28
                    if png: Image.fromarray(arr[:,:,:3]).save(seq/(stem+'.png'))
                    artifacts.append(dict(stage=stage,eye=eye,full_frame=full,crop_index=0,width=size,height=size,format=fmt,raw_path=stem+'.bin',png_path=stem+'.png' if png else '',raw_required=True,raw_written=True,png_required=png,png_written=png,crop_rect=dict(x=0,y=0,width=size,height=size),source_rect=dict(x=0,y=0,width=4,height=4)))
        f=dict(sequence_id=seq.name,schema_version=2,status='complete',frame_id=1,sample_index=1,host_frame=10,route='feature18_stereo',model_resolution_percent=100,pass_count=1,artifacts=artifacts)
        manifest=seq/'frames.jsonl'; manifest.write_text(json.dumps(f)+'\n')
        r=audit_sequence(seq,out); assert not r['frames'][0]['errors'],r
        # A truncated PNG, incomplete raw write, orphan file and torn JSONL tail
        # must all be reported without losing the earlier frame record.
        (seq/'frames/input_0_True.png').write_bytes(b'\x89PNG\r\n\x1a\n')
        (seq/'frames/depth_1_True.bin').write_bytes(b'bad')
        (seq/'frames/uncommitted.bin').write_bytes(b'uncommitted')
        with manifest.open('a') as stream: stream.write('{"frame_id":2')
        r=audit_sequence(seq,out)
        assert r['errors'] and r['frames'][0]['errors'] and len(r['orphan_files'])==1
        assert len(r['frames'])==1 and not r['manifest_ends_newline']
        print('PASS: complete fixture, PNG corruption, raw truncation, orphan, torn tail recovery')

if __name__=='__main__': main()
