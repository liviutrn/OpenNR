"""Independent paired-tone/image oracle. It does not execute HLSL or native NR."""
import math
import random
import json

rng = random.Random(73)
luma = (0.2126, 0.7152, 0.0722)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def fit(pairs, stops=0.5, cap=0.08):
    pairs=[(tuple(max(x,0) for x in b),tuple(max(x,0) for x in r)) for b,r in pairs
           if all(math.isfinite(x) and abs(x)<=16 for x in (*b,*r))]
    if not pairs: return (1,1,1),(0,0,0),0
    n=len(pairs)
    b=tuple(sum(x[0][c] for x in pairs)/n for c in range(3))
    r=tuple(sum(x[1][c] for x in pairs)/n for c in range(3))
    var=tuple(max(sum(x[0][c]**2 for x in pairs)/n-b[c]**2,0) for c in range(3))
    cov=tuple(sum(x[0][c]*x[1][c] for x in pairs)/n-b[c]*r[c] for c in range(3))
    g=tuple(max(2**-stops,min(2**stops,(cov[c]+0.0001)/(var[c]+0.0001))) for c in range(3))
    o=tuple(max(-cap,min(cap,r[c]-g[c]*b[c])) for c in range(3))
    err=tuple(max(sum(x[1][c]**2 for x in pairs)/n-r[c]**2+g[c]**2*var[c]-2*g[c]*cov[c],0) for c in range(3))
    return g,o,min(n/32,1)/(1+dot(err,luma)*100)
def apply(source,g,bias,confidence=1,brightness=1,color=1,weight=1,stops=.5,cap=.08):
    delta=tuple(max(source[c],0)*(g[c]-1)+bias[c] for c in range(3))
    y=dot(delta,luma)
    return tuple(max(source[c]+max(-max(source[c],0)*(2**stops-1)-cap,
                    min(max(source[c],0)*(2**stops-1)+cap,y*brightness+(delta[c]-y)*color))*confidence*weight,0) for c in range(3))

base=[tuple(rng.uniform(.08,.65) for _ in range(3)) for _ in range(64)]
fixtures=[('identity',(1,1,1),(0,0,0)),('lift',(1,1,1),(.06,.06,.06)),
          ('darken',(.8,.8,.8),(0,0,0)),('negative_offset',(1,1,1),(-.04,-.04,-.04)),
          ('shadow_lift_highlight_darkening',(.85,.85,.85),(.05,.05,.05)),
          ('tint',(1.2,.9,1.1),(.015,-.01,.005))]
max_error=0
for name,g,b in fixtures:
    pairs=[(x,tuple(g[c]*x[c]+b[c] for c in range(3))) for x in base]
    gain,bias,confidence=fit(pairs)
    for x in base:
        out=apply(x,gain,bias,confidence)
        target=tuple(g[c]*x[c]+b[c] for c in range(3))
        error=max(abs(a-b) for a,b in zip(out,target));max_error=max(max_error,error)
        assert error<.001, (name,error)
# Flat black must carry additive NR shadow lift; no luminance confidence suppression.
g,b,c=fit([((0,0,0),(.06,.06,.06))]*64)
assert c>.999 and max(abs(v-.06) for v in apply((0,0,0),g,b,c))<1e-9
# Uniform dark regions and strongly bounded edits.
for x in (0,.001,.01,.1,.8):
    g,b,c=fit([((x,)*3,(max(x-.03,0),)*3)]*64)
    assert max(abs(v-max(x-.03,0)) for v in apply((x,)*3,g,b,c))<1e-8
for value in (float('nan'),float('inf'),1e30):
    g,b,c=fit([((value,)*3,(value,)*3)]*64)
    assert g==(1,1,1) and b==(0,0,0) and c==0
# Sample the actual geometric boundary strip for varying crop shapes/tiers.
accepted=0
for w,h in ((1,1),(16,9),(180,140),(1200,1100)):
 for oval in (False,True):
  for scale in (1,.8,.6):
   lo=(w*(1-scale)/2+.5,h*(1-scale)/2+.5);hi=(w-lo[0],h-lo[1])
   rx,ry=max(.5,w*.5*scale),max(.5,h*.5*scale)
   for cy in range(16):
    for cx in range(16):
     p=((cx+.5)*w/16,(cy+.5)*h/16)
     if oval:
      dx,dy=p[0]-w/2,p[1]-h/2;radius=math.hypot(dx/rx,dy/ry)
      dx,dy=dx/max(radius,1e-5),dy/max(radius,1e-5)
      boundary=(w/2+dx,h/2+dy);nx,ny=dx/(rx*rx),dy/(ry*ry)
      length=math.hypot(nx,ny);normal=(nx/length,ny/length)
     else:
      p=(max(lo[0],min(hi[0],p[0])),max(lo[1],min(hi[1],p[1])))
      ds=(p[0]-lo[0],p[1]-lo[1],hi[0]-p[0],hi[1]-p[1]);edge=ds.index(min(ds))
      boundary=list(p);normal=((-1,0),(0,-1),(1,0),(0,1))[edge]
      boundary[edge%2]=(lo if edge<2 else hi)[edge%2]
     for y in range(8):
      for x in range(8):
       depth=1.5+(y+.5)*32/8;along=((x+.5)/8-.5)*32
       sx=max(0,min(w-1,int(max(boundary[0]-normal[0]*depth-normal[1]*along,0))))
       sy=max(0,min(h-1,int(max(boundary[1]-normal[1]*depth+normal[0]*along,0))))
       pos=(sx+.5,sy+.5)
       inside=((pos[0]-w/2)/rx)**2+((pos[1]-h/2)/ry)**2<=1 if oval else all(lo[c]<=pos[c]<=hi[c] for c in range(2))
       if inside:
        assert 0<=sx<w and 0<=sy<h;accepted+=1
# Outside application preserves the protected mask and alpha independently.
protected=outer=0
for oval in (False,True):
 for scale in (1,.8,.6):
  for eye in (0,1):
   x0,y0=eye*321+59,43;w,h=180,140
   for y in range(257):
    for x in range(eye*321,(eye+1)*321):
     lx,ly=x-x0,y-y0
     if oval:
      dx,dy=lx+.5-w/2,ly+.5-h/2;radius=math.hypot(dx/(w*.5*scale),dy/(h*.5*scale))
      inside=radius<=1;d=-1 if inside else math.hypot(dx,dy)*(1-1/radius)
     else:
      ix,iy=w*(1-scale)/2,h*(1-scale)/2
      inside=ix<=lx<=w-1-ix and iy<=ly<=h-1-iy
      d=math.hypot(max(ix-lx,lx-(w-1-ix),0),max(iy-ly,ly-(h-1-iy),0))
     original=(.02,.04,.06,.37);out=original
     if not inside and 0<d<128:
      t=min(d/128,1);fade=1-t*t*(3-2*t);t=min(d/8,1);weight=fade*t*t*(3-2*t)
      out=(*apply(original[:3],(1,1,1),(.05,.03,-.01),weight=weight),original[3]);outer+=1
     if inside: assert out==original;protected+=int(inside)
     assert out[3]==original[3] and all(math.isfinite(v) and v>=0 for v in out)
print(json.dumps({'affine_tone_fixtures':len(fixtures),'max_fixture_error':max_error,'black_shadow_lift':True,
                  'valid_boundary_samples':accepted,'protected_pixels':protected,'outside_pixels':outer,
                  'alpha_preserved':True,'nonfinite_extreme_rejected':True,'native_gpu_test':False},indent=2))
