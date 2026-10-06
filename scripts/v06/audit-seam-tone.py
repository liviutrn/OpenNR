"""Independent tone fixtures and interpolation checks; not an execution of NR or HLSL."""
import math
import json
import random
import struct

LUMA = (.2126,.7152,.0722)
def dot(a,b): return sum(x*y for x,y in zip(a,b))
def clamp(x,a,b): return max(a,min(b,x))
def f32(x): return struct.unpack('f',struct.pack('f',x))[0]
def fit(pairs, float32=False, focus=.5):
    round_value = f32 if float32 else lambda x:x
    def add(a,b): return round_value(a+round_value(b))
    total = square = 0.
    moments = [0.]*4
    base = [0.]*3; base2 = [0.]*3; delta = [0.]*3; delta2 = [0.]*3
    bd = [0.]*3; y2d = [0.]*3; by2 = [0.]*3
    for i,(b,r) in enumerate(pairs):
        if not all(math.isfinite(v) and abs(v)<=16 for v in (*b,*r)): continue
        b = [max(v,0) for v in b]; r = [max(v,0) for v in r]
        weight = 1/(1+6*focus*((i//8+.5)/8)**2)
        value = min(dot(b,LUMA),1)
        for c in range(3):
            d = r[c]-b[c]
            base[c] = add(base[c],b[c]*weight);base2[c] = add(base2[c],b[c]*b[c]*weight)
            delta[c] = add(delta[c],d*weight);delta2[c] = add(delta2[c],d*d*weight)
            bd[c] = add(bd[c],b[c]*d*weight)
            y2d[c] = add(y2d[c],value*value*d*weight);by2[c] = add(by2[c],b[c]*value*value*weight)
        for c in range(4): moments[c] = add(moments[c],value**(c+1)*weight)
        total = add(total,weight);square = add(square,weight*weight)
    if not total: return ((0.,)*3,(0.,)*3,(0.,)*3,(0.,)*3,0.,0.,0.)
    for array in (moments,base,base2,delta,delta2,bd,y2d,by2):
        for i in range(len(array)): array[i] = round_value(array[i]/total)
    mean = moments[0]; variance = max(moments[1]-mean*mean,0)
    rgb_variance = [max(base2[i]-base[i]**2,0) for i in range(3)]
    qvariance = max(moments[3]-moments[1]**2,0)
    cov = [bd[i]-base[i]*delta[i] for i in range(3)]
    qcov = [y2d[i]-moments[1]*delta[i] for i in range(3)]
    cross = [by2[i]-base[i]*moments[1] for i in range(3)]
    a = [v+1e-5 for v in rgb_variance];c = qvariance+1e-6
    determinant = [max(a[i]*c-cross[i]**2,1e-11) for i in range(3)]
    slope = [clamp((c*cov[i]-cross[i]*qcov[i])/determinant[i],-2,2) for i in range(3)]
    curve = [clamp((a[i]*qcov[i]-cross[i]*cov[i])/determinant[i],-4,4) for i in range(3)]
    error = [max(delta2[i]-delta[i]**2+slope[i]**2*rgb_variance[i]+curve[i]**2*qvariance+2*slope[i]*curve[i]*cross[i]-2*slope[i]*cov[i]-2*curve[i]*qcov[i],0) for i in range(3)]
    confidence = min(total*total/max(square,1e-5)/32,1)/(1+dot(error,LUMA)*100)
    intercept = [delta[i]+slope[i]*(.25-base[i])-curve[i]*moments[1] for i in range(3)]
    return intercept,slope,curve,base,mean,variance,confidence

def prediction(model,source,contrast=1,nonlinear=1):
    value,slope,curve,reference,mean,variance,_ = model
    support = max(.04,3*math.sqrt(max(variance,0)))
    position = clamp(min(dot(source,LUMA),1)-mean,-support,support)
    mean_square = mean*mean+variance
    return tuple(value[c]+slope[c]*(reference[c]-.25)+curve[c]*mean_square+slope[c]*(source[c]-reference[c])*contrast+curve[c]*((mean+position)**2-mean_square)*nonlinear for c in range(3))

def apply(model,source,weight=1,brightness=1,color=1,stops=.5,offset=.08,black=0):
    delta = prediction(model,source)
    value = dot(delta,LUMA)
    bright = value*brightness
    y = dot(source,LUMA)
    t = clamp((y-.001)/(.035-.001),0,1)
    if bright>0: bright *= 1-black+black*t*t*(3-2*t)
    return tuple(max(source[c]+clamp(bright+(delta[c]-value)*color,-max(source[c],0)*(2**stops-1)-offset,max(source[c],0)*(2**stops-1)+offset)*weight*model[-1],0) for c in range(3))

def oracle():
    rng = random.Random(191)
    values = [.005+.94*i/63 for i in range(64)]
    fixtures = {
        'identity':lambda y:(y,)*3,
        'lift':lambda y:(y+.04,)*3,
        'darken':lambda y:(.82*y,)*3,
        'contrast':lambda y:(.78*y+.06,)*3,
        'curved_shadows_highlights':lambda y:(y+.055-.13*y+.085*y*y,)*3,
        'colored_curve':lambda y:(y+.03-.08*y+.04*y*y,y+.015-.02*y-.02*y*y,y+.04-.06*y+.01*y*y),
    }
    maximum = 0
    for name,function in fixtures.items():
        pairs = [((y,)*3,function(y)) for y in values]
        for float32 in (False,True):
            model = fit(pairs,float32)
            for y in values:
                result = apply(model,(y,)*3)
                error = max(abs(result[c]-function(y)[c]) for c in range(3))
                maximum = max(maximum,error)
                assert error < .0015,(name,float32,y,error)
    for level in (0,.00001,.001,.02,.5,.99,1):
        for float32 in (False,True):
            model = fit([((level,)*3,(level+.04,)*3)]*64,float32)
            assert max(abs(v-(level+.04)) for v in apply(model,(level,)*3)) < .0005
    model = fit([((0,)*3,(.06,)*3)]*64)
    assert max(apply(model,(0,)*3,black=1))==0
    assert min(apply(model,(0,)*3,black=0))>.0599
    assert fit([((float('nan'),)*3,(0,)*3)]*64)[-1]==0
    colored = [tuple(rng.uniform(.08,.65) for _ in range(3)) for i in range(64)]
    rgb_max = 0
    for nonlinear in (False,True):
        pairs=[]
        for b in colored:
            y=dot(b,LUMA)
            pairs.append((b,tuple((1.2,.9,1.1)[c]*b[c]+(.015,-.01,.005)[c]+((.04,-.03,.02)[c]*y*y if nonlinear else 0) for c in range(3))))
        for float32 in (False,True):
            model=fit(pairs,float32)
            for b,target in pairs:
                error=max(abs(v-t) for v,t in zip(apply(model,b),target));rgb_max=max(rgb_max,error)
                assert error<.0015,(nonlinear,float32,error)
    # Global RGB and squared-luminance coefficients interpolate independently of patch origins.
    coeff = ((.03,.02,.01),(-.12,-.08,-.05),(.1,.08,.04))
    for _ in range(1000):
        source=tuple(rng.random() for c in range(3));reference=tuple(rng.random() for c in range(3))
        mean=dot(reference,LUMA);variance=rng.random()*.04;y=dot(source,LUMA)
        out=[coeff[0][c]+coeff[1][c]*(reference[c]-.25)+coeff[2][c]*(mean*mean+variance)+coeff[1][c]*(source[c]-reference[c])+coeff[2][c]*(y*y-mean*mean-variance) for c in range(3)]
        expected=[coeff[0][c]+coeff[1][c]*(source[c]-.25)+coeff[2][c]*y*y for c in range(3)]
        assert max(abs(a-b) for a,b in zip(out,expected))<1e-12
    for _ in range(10000):
        pairs = [(tuple(rng.random() for _ in range(3)),tuple(rng.random() for _ in range(3))) for _ in range(16)]
        model = fit(pairs,True)
        source = tuple(rng.random() for _ in range(3))
        out = apply(model,source,black=rng.random())
        assert all(math.isfinite(v) and v>=0 for v in out)
        assert all(abs(out[c]-source[c]) <= source[c]*(2**.5-1)+.080001 for c in range(3))
    return {'fixtures':len(fixtures),'max_fixture_error':maximum,'max_mixed_color_error':rgb_max,'mixed_color_fixtures':2,'random_bounded_cases':10000,'common_basis_cases':1000,'gpu_executed':False}

if __name__ == '__main__': print(json.dumps(oracle(),indent=2))
