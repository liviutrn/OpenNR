"""Read-only raw capture audit; writes decoded previews and statistics to a separate output."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

STAGES = ['gbuffer_albedo', 'gbuffer_normal_roughness', 'gbuffer_masks',
          'gbuffer_masks2', 'gbuffer_specular', 'gbuffer_reflectance']

def unsigned_float(bits, mantissa):
    exponent = bits >> mantissa
    fraction = bits & ((1 << mantissa) - 1)
    value = np.where(exponent == 0, np.ldexp(fraction.astype(float), 1-15-mantissa),
                     np.ldexp(1 + fraction.astype(float)/(1 << mantissa), exponent.astype(int)-15))
    return np.where(exponent == 31, np.where(fraction == 0, np.inf, np.nan), value)

def decode(path, a):
    raw = path.read_bytes()
    fmt = a['format']
    dtype = '<u2' if fmt == 56 else '<u4'
    bpp = 2 if fmt == 56 else 4
    assert len(raw) == a['row_pitch'] * a['height']
    v = np.frombuffer(raw, dtype=dtype).reshape(a['height'], a['row_pitch']//bpp)[:, :a['width']]
    if fmt == 24:
        x = np.stack([(v >> shift) & 1023 for shift in (0,10,20)] + [(v >> 30) & 3], -1).astype(float)
        x /= np.array([1023,1023,1023,3])
    elif fmt == 26:
        x = np.stack([unsigned_float(v & 2047,6), unsigned_float((v >> 11)&2047,6),
                      unsigned_float((v >> 22)&1023,5)], -1)
    elif fmt == 56:
        x = v[...,None].astype(float)/65535
    elif fmt == 28:
        x = np.stack([(v >> shift)&255 for shift in (0,8,16)],-1)/255.0
    else:
        raise ValueError(fmt)
    return x, hashlib.sha256(raw).hexdigest()

def normals(x):
    f=x[...,:2]*2-1
    n=np.concatenate([f, (1-np.abs(f).sum(-1))[...,None]],-1)
    t=np.clip(-n[...,2:3],0,1)
    n[...,:2] += np.where(n[...,:2]>=0,-t,t)
    return -n/np.maximum(np.linalg.norm(n,axis=-1,keepdims=True),1e-12)

def align(x,a,color):
    s,c=a['source_rect'],a['crop_rect']
    ts,tc=color['source_rect'],color['crop_rect']
    sx,sy=s['width']/ts['width'],s['height']/ts['height']
    # PIL affine maps destination pixel centers into the native crop.
    tx,ty=tc['x']*sx-c['x'],tc['y']*sy-c['y']
    covered=tx>=0 and ty>=0 and tx+color['width']*sx<=a['width'] and ty+color['height']*sy<=a['height']
    channels=[np.asarray(Image.fromarray(x[...,i].astype('float32')).transform(
        (color['width'],color['height']),Image.Transform.AFFINE,(sx,0,tx,0,sy,ty),
        resample=Image.Resampling.BILINEAR)) for i in range(x.shape[-1])]
    return np.stack(channels,-1), {'scale':[sx,sy],'offset':[tx,ty],'covered':bool(covered)}

def picture(x, scale=1):
    x=np.nan_to_num(x[...,:3],nan=0,posinf=0,neginf=0)
    if x.shape[-1]==1: x=np.repeat(x,3,-1)
    return Image.fromarray((np.clip(x/scale,0,1)*255).astype('uint8'))

def sheet(cells, cols, output, size=220):
    rows=(len(cells)+cols-1)//cols
    img=Image.new('RGB',(cols*size,rows*(size+28)),(22,24,29))
    draw=ImageDraw.Draw(img)
    for i,(label,im) in enumerate(cells):
        x,y=i%cols*size,i//cols*(size+28)
        draw.text((x+4,y+5),label,fill='white')
        img.paste(im.resize((size,size)),(x,y+28))
    img.save(output)

def edge(x):
    im=np.asarray(picture(x).convert('L').resize((96,96)),dtype=float)/255
    dy,dx=np.gradient(im)
    return np.hypot(dx,dy).ravel()

def corr(a,b):
    return float(np.corrcoef(a,b)[0,1]) if a.std()>1e-9 and b.std()>1e-9 else None

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('sequences',nargs='+',type=Path)
    args=p.parse_args()
    for seq in args.sequences:
        if args.output.resolve().is_relative_to(seq.resolve()):
            raise ValueError('Output must be outside source sequences')
    args.output.mkdir(parents=True,exist_ok=True)
    report={'scope':'Content and coordinate audit; edge similarity is diagnostic, not proof of frame or eye identity.', 'sequences':[]}
    for seq in args.sequences:
        frames=[json.loads(line) for line in (seq/'frames.jsonl').read_text().splitlines() if line.strip()]
        records=[]; previews={}; hashes={}; changes={}; prior={}; edges={}; metadata_hashes={}
        for file in ('sequence.json','frames.jsonl'):
            metadata_hashes[file]=hashlib.sha256((seq/file).read_bytes()).hexdigest()
        for fi,f in enumerate(frames):
            for eye in (0,1):
                arts={a['stage']:a for a in f['artifacts'] if a['eye']==eye and a['crop_index']==0 and not a['full_frame']}
                views={}
                for stage in ['input','teacher']+STAGES:
                    a=arts[stage];x,h=decode(seq/a['raw_path'],a)
                    key=(eye,stage);hashes.setdefault(str(key),[]).append(h)
                    finite=np.isfinite(x)
                    stats={'frame':f['frame_id'],'eye':eye,'stage':stage,'sha256':h,
                           'nonfinite':int((~finite).sum()),'min':np.nanmin(x,axis=(0,1)).tolist(),
                           'max':np.nanmax(x,axis=(0,1)).tolist(),'std':np.nanstd(x,axis=(0,1)).tolist(),
                           'zero_fraction':float((x==0).mean())}
                    if key in prior: changes.setdefault(str(key),[]).append(float(np.mean(np.abs(x-prior[key]))))
                    prior[key]=x
                    if stage in STAGES:
                        x,mapping=align(x,a,arts['teacher']);stats['alignment']=mapping
                    if stage=='gbuffer_normal_roughness':
                        views['normals']=picture(normals(x)*.5+.5)
                        views['roughness']=picture(1-x[...,2:3])
                    if stage in ('input','teacher','gbuffer_albedo'):
                        edges[(fi,eye,stage)]=edge(x)
                    # Float light/mask previews use a labelled per-image p99 scale.
                    scale=max(float(np.nanquantile(x,.99)),1e-8) if a['format']==26 else 1
                    views[stage]=picture(x,scale)
                    stats['preview_scale']=scale;records.append(stats)
                previews[(fi,eye)]=views
        scores=[]
        for fi in range(len(frames)):
            for eye in (0,1):
                for offset in (-1,0,1):
                    if not 0<=fi+offset<len(frames): continue
                    for candidate_eye in (0,1):
                        scores.append({'frame_index':fi,'eye':eye,'offset':offset,'candidate_eye':candidate_eye,
                            'edge_correlation':corr(edges[(fi,eye,'input')],edges[(fi+offset,candidate_eye,'gbuffer_albedo')])})
        overview=[]
        for fi in (0,len(frames)-1):
            for eye in (0,1):
                for stage in ('input','teacher','gbuffer_albedo','normals','roughness'):
                    overview.append((f'F{fi+1} E{eye} {stage.replace("gbuffer_","")}',previews[(fi,eye)][stage]))
        sheet(overview,5,args.output/(seq.name+'_aligned.png'))
        timeline=[]
        for eye in (0,1):
            for stage in ('input','gbuffer_albedo','normals'):
                for fi in range(len(frames)):
                    timeline.append((f'E{eye} F{fi+1} {stage.replace("gbuffer_","")}',previews[(fi,eye)][stage]))
        sheet(timeline,len(frames),args.output/(seq.name+'_timeline.png'),128)
        scales={(r['eye'],r['stage']):r['preview_scale'] for r in records if r['frame']==frames[0]['frame_id']}
        sheet([(f'E{e} {s.replace("gbuffer_","")} /{scales[e,s]:.3g}',previews[(0,e)][s]) for e in (0,1) for s in STAGES],6,
              args.output/(seq.name+'_channels.png'))
        report['sequences'].append({'sequence':seq.name,'frames':len(frames),'records':records,
            'unique_hashes':{k:len(set(v)) for k,v in hashes.items()},'adjacent_mae':changes,
            'edge_scores':scores,'metadata_hashes':metadata_hashes})
    (args.output/'audit.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    sections=[]
    for s in report['sequences']:
        name=s['sequence']
        sections.append('<h2>'+html.escape(name)+'</h2>')
        for suffix in ('aligned','timeline','channels'):
            filename=html.escape(name+'_'+suffix+'.png')
            sections.append(f'<h3>{suffix}</h3><a href="{filename}"><img src="{filename}"></a>')
    (args.output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>OpenNR conditioning audit</title>'
        '<style>body{background:#15171b;color:#eee;font:16px system-ui;margin:24px}img{max-width:100%}a{color:#8df}</style>'
        '<h1>OpenNR conditioning content and alignment audit</h1>'
        '<p>Aligned: input, teacher, albedo, decoded view-space normals, roughness. First/last frame, both eyes.</p>'
        '<p>Timeline: all captured frames, input/albedo/normals for each eye. Channel sheets show packed normal XY/glossiness; '
        'floating-point channels use the indicated per-image divisor, so brightness is not comparable between tiles.</p>'
        '<p>Native crops mapped to the teacher region; bilinear previews are diagnostic, not a training cache. '
        'Edge correlations do not prove exact frame identity or subpixel alignment.</p>'
        '<a href="audit.json">Full statistics and provenance hashes</a>'+''.join(sections),encoding='utf-8')
    print(json.dumps({'sequences':len(report['sequences']),'output':str(args.output)}))

if __name__=='__main__': main()
