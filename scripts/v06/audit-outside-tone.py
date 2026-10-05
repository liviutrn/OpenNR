"""Independent numerical image oracle; not a substitute for FXC or a VR GPU run."""
import json
from pathlib import Path
import numpy as np

rng = np.random.default_rng(53)
height, eye_width = 257, 321
source = rng.uniform(0.02, 0.9, (height, eye_width * 2, 4)).astype(np.float32)
yy, xx = np.mgrid[:height, :eye_width * 2]
checked = 0
for oval in (False, True):
    for scale in (1, 0.8, 0.6):
        for origin in ((0, 0), (59, 43), (141, 117)):
            crop_w, crop_h = 180, 140
            result = source.copy()
            masks = []
            for eye in range(2):
                x, y = origin[0] + eye * eye_width, origin[1]
                local_x, local_y = xx - x, yy - y
                if oval:
                    dx, dy = local_x + 0.5 - crop_w / 2, local_y + 0.5 - crop_h / 2
                    radius = np.sqrt((dx / (crop_w / 2 * scale))**2 + (dy / (crop_h / 2 * scale))**2)
                    inside = radius <= 1
                    distance = np.hypot(dx, dy) * (1 - 1 / np.maximum(radius, 1e-8))
                else:
                    ix, iy = crop_w * (1-scale)/2, crop_h * (1-scale)/2
                    inside = (local_x >= ix) & (local_x <= crop_w-1-ix) & (local_y >= iy) & (local_y <= crop_h-1-iy)
                    distance = np.hypot(np.maximum(np.maximum(ix-local_x, local_x-(crop_w-1-ix)), 0),
                                        np.maximum(np.maximum(iy-local_y, local_y-(crop_h-1-iy)), 0))
                # Strong, known NR tint for the independent outside-write oracle.
                result[inside, :3] *= np.array([1.2, 1.1, 0.95], dtype=np.float32)
                masks.append((eye, inside, distance))
            before = result.copy()
            for eye, inside, distance in masks:
                t = np.clip(distance / 128, 0, 1)
                weight = (1 - t*t*(3-2*t))
                t = np.clip(distance / 8, 0, 1)
                weight *= t*t*(3-2*t)
                active = (~inside) & (distance > 0) & (distance < 128) & (xx >= eye*eye_width) & (xx < (eye+1)*eye_width)
                correction = np.exp2(weight[...,None] * np.array([0.14,0.08,-0.03]))
                result[active,:3] *= correction[active].astype(np.float32)
            for _, inside, _ in masks:
                assert np.array_equal(result[inside], before[inside])
            assert np.array_equal(result[...,3], before[...,3])
            assert np.isfinite(result).all()
            assert np.any(result != before)
            checked += 1

# Coarse paired map identity, known uniform gain, black protection and gain caps.
def tone(base, nr, limit=0.5):
    base = np.where(np.isfinite(base).all(axis=-1, keepdims=True), np.maximum(base,0), 0)
    nr = np.where(np.isfinite(nr).all(axis=-1, keepdims=True), np.maximum(nr,0), base)
    base, nr = base.mean(axis=(0,1)), nr.mean(axis=(0,1))
    luma = np.array([0.2126,0.7152,0.0722])
    brightness = np.clip(np.log2((nr@luma + 0.01)/(base@luma + 0.01)), -limit, limit)
    rgb = np.clip(np.log2((nr+0.01)/(base+0.01)), -limit, limit)
    t = np.clip((base@luma-0.002)/0.028, 0, 1)
    return np.r_[rgb,brightness] * t*t*(3-2*t)

base = rng.uniform(0.1,0.5,(8,8,3))
assert np.array_equal(tone(base,base), np.zeros(4))
assert np.all(tone(base,base*1.2) > 0)
assert np.all(tone(base,base*0.8) < 0)
assert np.array_equal(tone(base*0,base*0+1), np.zeros(4))
assert np.isfinite(tone(base*np.nan,base*np.nan)).all()
assert np.max(np.abs(tone(base,base*100))) <= 0.5
assert np.array_equal(source * np.exp2(np.zeros_like(source)), source) # identity transfer
print(json.dumps({'image_cases': checked, 'crop_and_inner_feather_bit_exact': True,
                  'alpha_bit_exact': True, 'paired_tone_identity': True,
                  'black_and_nonfinite_protection': True, 'gain_limit': True,
                  'runtime_gpu_verification': False}, indent=2))
