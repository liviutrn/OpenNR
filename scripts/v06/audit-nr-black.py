"""Check inside-NR attenuation and consistent configuration range contracts."""
from pathlib import Path
import math, random, re
root=Path(__file__).resolve().parents[2]
src=root/'runtime/open-shaders/src/Features/Upscaling'
def smooth(a,b,v):
 t=max(0,min(1,(v-a)/(b-a)));return t*t*(3-2*t)
def protect(base,delta,strength,threshold,softness):
 luma=sum(a*b for a,b in zip(delta,(.2126,.7152,.0722)))
 weight=max(0,min(1,strength*(1-smooth(0,threshold,max(0,*base)))*smooth(0,softness,luma))) if luma>0 else 0
 return tuple(d*(1-weight) for d in delta)
rng=random.Random(619)
for _ in range(10000):
 base=tuple(rng.random()*.25 for _ in range(3));delta=tuple(rng.uniform(-.2,2) for _ in range(3))
 strength=rng.uniform(0,2);threshold=rng.uniform(.001,.25);softness=rng.uniform(.00001,.05)
 result=protect(base,delta,strength,threshold,softness)
 assert all(math.isfinite(v) and min(0,d)-1e-12<=v<=max(0,d)+1e-12 for v,d in zip(result,delta))
 if sum(a*b for a,b in zip(delta,(.2126,.7152,.0722)))<=0 or max(base)>=threshold:
  assert result==delta
 assert protect(base,delta,0,threshold,softness)==delta
base=(0,0,0);delta=(.04,.04,.04)
assert protect(base,delta,1,.035,.001)==(0,0,0)
assert protect(base,delta,2,.035,.001)==(0,0,0)
base=(.02,.02,.02)
assert protect(base,delta,2,.035,.001)[0] <= protect(base,delta,1,.035,.001)[0]
fov=(src/'FoveatedRender.cpp').read_text();policy=(src/'NeuralRendering/OutsideTonePolicy.h').read_text();ux=(src.parent/'Upscaling.cpp').read_text()
names=('Brightness','Color','Width','Curve','Dither','BoundaryRamp','LimitStops','OffsetLimit','SampleWidth','Smoothing','EdgeProtection','Contrast','Nonlinear','Plateau','SampleFocus','ContrastReach')
for name in names:
 field='outsideTone'+name;key=name[0].lower()+name[1:]
 def ranges(text,pattern):
  m=re.search(pattern,text);assert m,(name,pattern);return tuple(float(x.rstrip('f')) for x in m.groups())
 a=ranges(fov,rf'&settings\.{field}, ([\d.]+f?), ([\d.]+f?)')
 b=ranges(fov,rf'settings\.{field} = clampFinite\(settings\.{field}, [^,]+, ([\d.]+f?), ([\d.]+f?)')
 c=ranges(policy,rf'c\.{key} = clamp\(c\.{key}, [^,]+, ([\d.]+f?), ([\d.]+f?)')
 d=ranges(ux,rf'next\.{field} = read\("[^"]+", next\.{field}, ([\d.]+f?), ([\d.]+f?)')
 assert a==b==c==d,(name,a,b,c,d)
renderer=(src/'NeuralRendering/Renderer.cpp').read_text()
config=renderer[renderer.index('ResultShapingConfigKey MakeResultShapingConfigKey'):renderer.index('bool HasResultShapingEffect')]
assert 'nearBlack' not in config, 'Output-only protection invalidates raw history'
assert renderer.count('ApplyResultShaping(device, context,')==5
print('Inside-NR protection: 10000 bounded convex cases; disabled/darkening/highlight preservation; stronger protection; 16 UI/load/runtime/command range contracts; raw-history key and five output routes passed')
