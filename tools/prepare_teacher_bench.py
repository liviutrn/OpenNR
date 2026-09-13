"""Prepare an isolated native Feature 18 replay from an audited validation pair."""
import argparse,json,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--iterations',type=int,default=50);p.add_argument('--validation-sequence-index',type=int,default=0);a=p.parse_args()
cache=Path('C:/OpenNR/TrainingCache/student_v1');rows=json.loads((cache/'rows.json').read_text())
sequences=list(dict.fromkeys(r['sequence_id'] for r in rows if r['split']=='validation'))
if not 0<=a.validation_sequence_index<len(sequences):raise ValueError('Validation sequence index out of range')
i=next(i for i,r in enumerate(rows) if r['split']=='validation' and r['sequence_id']==sequences[a.validation_sequence_index]);pair=rows[i:i+2]
assert pair[0]['sequence_id']==pair[1]['sequence_id'] and pair[0]['frame_id']==pair[1]['frame_id'] and [r['eye'] for r in pair]==[0,1]
dll=Path('E:/MGO-RC3-fresh/mods/Open Shaders DLSSNR VR 0.5.2 OpenNR/Shaders/Upscaling/Streamline/nvngx_dlssnr.dll');a.output.mkdir(parents=True,exist_ok=True)
cores=list(Path('C:/Windows/System32/DriverStore/FileRepository').glob('nv_dispi.inf_amd64_*/_nvngx.dll'))
if len(cores)!=1:raise ValueError('Resolve the active driver core explicitly before benchmarking')
core=cores[0]
w,h=pair[0]['color_size'];gw,gh=pair[0]['guide_size'];lines=[f'{w} {h} {gw} {gh} {a.iterations}',str(a.output.resolve()),str(dll),str(core)]
for row in pair:
    lines += [str(Path(row['paths']['input']).with_suffix('.raw.bin')),row['paths']['depth'],row['paths']['motion_vectors'],' '.join(map(str,row['motion_scale']))]
(a.output/'inputs.txt').write_text('\n'.join(lines)+'\n')
runtime=Path('D:/.CODEX_Projects/DLSS_5_SKYRIM/vendor/open-shaders-dlssnr-vr-091bfb4d/src/Features/Upscaling/NeuralRendering/Runtime.cpp')
(a.output/'provenance.json').write_text(json.dumps(dict(rows=pair,dll=str(dll),dll_sha256=hashlib.sha256(dll.read_bytes()).hexdigest(),driver_core=str(core),driver_core_sha256=hashlib.sha256(core.read_bytes()).hexdigest(),runtime_source=str(runtime),runtime_sha256=hashlib.sha256(runtime.read_bytes()).hexdigest(),warmup=20,iterations=a.iterations,scope='Repeated recorded stereo pair; authentic native guides. Replayed motion is not a contiguous temporal sequence. Output is a contract check, not expected bit-equivalence to captured history.'),indent=2))
print(a.output/'inputs.txt')
