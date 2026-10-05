"""CPU image/scene oracle for r2. Does not execute HLSL, NGX or a GPU."""
import ctypes as c
import json
import math
from pathlib import Path
import numpy as np

root = Path(__file__).resolve().parent
lib = c.CDLL(str(root / 'grid-export.so'))
lib.sampling.argtypes = [c.c_uint] * 4 + [c.c_bool, c.POINTER(c.c_float)]
lib.clip.argtypes = [c.c_uint] * 6 + [c.POINTER(c.c_float)]

def sampling(width, percent, origin, anchored=True):
    model = max(1, (width * percent + 50) // 100)
    values = (c.c_float * 4)()
    lib.sampling(width, model, percent, origin, anchored, values)
    return model, float(values[0]), float(values[2])

def downsample(scene, origin, width, percent, anchored=True):
    count, pitch, phase = sampling(width, percent, origin, anchored)
    # Emulate shader area weights and valid-region clamping, with a full-scene
    # oracle independent of the local crop's coordinate system.
    values = []
    for i in range(count):
        begin, end = i * pitch + phase, (i + 1) * pitch + phase
        value = 0.0
        for x in range(math.floor(begin), math.ceil(end)):
            weight = max(0.0, min(end, x + 1) - max(begin, x))
            value += scene[origin + min(max(x, 0), width - 1)] * weight
        values.append(value / pitch)
    return np.array(values), pitch, phase

def resolve(samples, pitch, phase, local):
    position = np.clip((local - phase) / pitch, .5, len(samples) - .5) - .5
    first = np.floor(position).astype(int)
    last = np.minimum(first + 1, len(samples) - 1)
    f = position - first
    return samples[first] * (1-f) + samples[last] * f

rng = np.random.default_rng(24)
scene = rng.uniform(0, 1, 8192)
max_new, max_old, constant_error, flat_error = 0.0, 0.0, 0.0, 0.0
image_cases = 0
for percent in (100,85,70):
    for width in (720,721,960,961,1202):
        for eye_offset in (0,2404):
            base = eye_offset + 238
            reference, pitch, phase = downsample(scene,base,width,percent)
            for delta in (2,4,6,8,10,12,14):
                origin = base + delta
                current,pitch_cur,phase_cur = downsample(scene,origin,width,percent)
                world = np.arange(origin+4,base+width-4)+.5
                error = np.max(np.abs(resolve(reference,pitch,phase,world-base)-resolve(current,pitch_cur,phase_cur,world-origin)))
                max_new = max(max_new,float(error)); image_cases += 1
                old0,p0,o0 = downsample(scene,base,width,percent,False)
                old1,p1,o1 = downsample(scene,origin,width,percent,False)
                max_old = max(max_old,float(np.max(np.abs(resolve(old0,p0,o0,world-base)-resolve(old1,p1,o1,world-origin)))))
                whites,_,_ = downsample(np.ones(8192),origin,width,percent)
                constant_error = max(constant_error,float(np.max(np.abs(whites-1))))
        # Flat/stationary source retains nominal ratio, area, and resolve.
        count,pitch,phase = sampling(width,percent,0,False)
        flat_error = max(flat_error,abs(count*pitch-width))
assert max_new < 4e-5, max_new
assert max_old > .1, max_old
assert constant_error < 1e-12, constant_error
assert flat_error < 1e-4, flat_error

# Test row-vector crop transforms with nontrivial perspective, camera rotation,
# translation, origin rebasing, and asymmetric frusta. Oracle projects the
# scene point directly in the previous frame and then crops pixel coordinates.
matrix_error = 0.0
for _ in range(2000):
    def vp():
        angle = rng.uniform(-.3,.3)
        rotation=np.eye(4); rotation[0,0]=rotation[2,2]=math.cos(angle)
        rotation[0,2]=-math.sin(angle); rotation[2,0]=math.sin(angle)
        translation=np.eye(4); translation[3,:3]=rng.uniform(-1,1,3)
        projection=np.zeros((4,4)); projection[0,0]=1.4; projection[1,1]=1.6
        projection[2,0:2]=rng.uniform(-.2,.2,2)
        projection[2,2]=1.001; projection[2,3]=1; projection[3,2]=-.1001
        return rotation@translation@projection
    def crop():
        x,y=map(int,rng.integers(0,500,2)); width,height=map(int,rng.integers(500,700,2))
        values=(c.c_float*4)();lib.clip(1202,1202,x,y,width,height,values)
        m=np.eye(4);m[0,0]=values[0];m[1,1]=values[1];m[3,0]=values[2];m[3,1]=values[3]
        return m,(x,y,width,height)
    a,b=vp(),vp(); ca,_=crop();cb,rect=crop()
    rebase=np.eye(4);rebase[3,:3]=rng.uniform(-.1,.1,3)
    point=np.array([*rng.uniform(-1,1,2),rng.uniform(4,8),1])
    current=point@a@ca
    via=current@np.linalg.inv(a@ca)@rebase@b@cb
    direct=point@rebase@b;ndc=direct[:2]/direct[3]
    pixel=np.array([(ndc[0]+1)*601,(1-ndc[1])*601])
    x,y,width,height=rect
    expected=np.array([2*(pixel[0]-x)/width-1,1-2*(pixel[1]-y)/height])
    matrix_error=max(matrix_error,float(np.max(np.abs(via[:2]/via[3]-expected))))
assert matrix_error < 3e-7,matrix_error

# World-space oracle for both atlas eyes through model/crop/guard transitions.
# A valid pixel must resolve into its own previous eye, including near borders.
atlas_cases=0;rejected=0;max_atlas_error=0.0
for cur_percent in (100,85,70):
    for prev_percent in (100,85,70):
        for cur_width in (720,960,1202):
            for prev_width in (720,960,1202):
                for eye_offset in (0,2404):
                    cur_origin=eye_offset+242;prev_origin=eye_offset+238
                    cur_count,cur_pitch,cur_phase=sampling(cur_width,cur_percent,cur_origin)
                    prev_count,prev_pitch,prev_phase=sampling(prev_width,prev_percent,prev_origin)
                    cur_guard=max(1,(64*cur_percent+50)//100);prev_guard=max(1,(64*prev_percent+50)//100)
                    cur_start=cur_count+cur_guard if eye_offset else 0
                    prev_start=prev_count+prev_guard if eye_offset else 0
                    for model in (.5,1.5,100.5,cur_count-.5):
                        for physical_motion in (-1500,-2.5,0,1.75,1500):
                            color=model*cur_pitch+cur_phase
                            prev_model=(color+cur_origin-prev_origin+physical_motion-prev_phase)/prev_pitch
                            valid=.5-.001<=prev_model<=prev_count-.5+.001
                            if valid:
                                packed_delta=prev_model-model+prev_start-cur_start
                                previous_packed=model+cur_start+packed_delta
                                expected_world=cur_origin+color+physical_motion
                                actual_world=prev_origin+(previous_packed-prev_start)*prev_pitch+prev_phase
                                max_atlas_error=max(max_atlas_error,abs(actual_world-expected_world))
                                assert prev_start+.5-.001<=previous_packed<=prev_start+prev_count-.5+.001
                            else:rejected+=1
                            atlas_cases+=1
assert max_atlas_error<1e-9,max_atlas_error

result=dict(cpu_only=True,image_cases=image_cases,max_overlap_error=max_new,
            unanchored_overlap_error=max_old,constant_field_error=constant_error,
            flat_extent_error=flat_error,matrix_cases=2000,max_matrix_ndc_error=matrix_error,
            atlas_cases=atlas_cases,atlas_rejections=rejected,max_atlas_world_error=max_atlas_error)
(root/'results.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
