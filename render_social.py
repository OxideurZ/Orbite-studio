#!/usr/bin/env python3
"""ORBITE — SVG → Fourier → vertical video + original procedural music.

python render_social.py --config examples/gondor.json --preset master
python render_social.py --svg mon_logo.svg --title 'Mon logo' --preset social
python render_social.py --image portrait.jpg --title 'Mon portrait' --preset social
"""
from __future__ import annotations
import argparse
import json
import math
import shutil
import subprocess
import wave
from collections import OrderedDict
from copy import deepcopy
import hashlib
from composition import adaptive_composition,fit_bounds,value_bounds
from trace_image import DEFAULT_TRACE,trace_settings
from runtime import require_ffmpeg
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from svgpathtools import Document, Line
from safe_area import DEFAULT_SAFE_AREA,safe_settings,safe_transform,safe_box
from music import DEFAULT_MUSIC,settings as music_settings,validate_music,master_audio
from themes import (DEFAULT_FONTS, load_theme, merge_configs, resolve_visual_paths,
                    validate_visual, validate_input)

ROOT = Path(__file__).resolve().parent
PRESETS = {'master': (1440, 2560, 60), 'social': (1080, 1920, 60),
           'preview': (540, 960, 30)}
DEFAULT = {
    'brand': 'ORBITE', 'tagline': 'LE DESSIN DES FRÉQUENCES', 'episode': '001',
    'title': 'L’Arbre blanc', 'svg': 'examples/gondor.svg', 'path_id': 'white_tree',
    'contours': 'largest', 'samples': 8192,
    'steps': [1, 2, 3, 6, 12, 24, 64, 160, 384],
    'durations': [1.5, 1.5, 2, 2, 2.5, 3, 3.5, 4, 6.5],
    'intro': 1.0, 'outro': 4.5, 'background': 'assets/montagnes_orbite.png', 'background_opacity': .45,
    'colors': {'background': '#090d20', 'ink': '#f2efff', 'muted': '#9aa6c9',
               'trace': '#e4c9ff', 'x': '#82e4ff', 'y': '#b6a1ff'},
    'captions': {'early':'La silhouette.', 'middle':'La structure.', 'late':'Les détails.'},
    'final_title': 'Des cercles.\nUne constellation.', 'hero_scale': 1.4,
    'layout': 'classic',
    'fonts':DEFAULT_FONTS.copy(),'background_dimming':{'top':.25,'bottom':.03},
    'audio': True, 'source_credit': '',
    'safe_area':DEFAULT_SAFE_AREA.copy(),
    'music':DEFAULT_MUSIC.copy(),'trace':DEFAULT_TRACE.copy(),
}


def rgb(c):
    return tuple(bytes.fromhex(c.lstrip('#')))


def mix(a, b, amount):
    return tuple(int(x*(1-amount)+y*amount) for x, y in zip(rgb(a) if isinstance(a,str) else a,
                                                        rgb(b) if isinstance(b,str) else b))


def smooth(t):
    t = np.clip(t, 0, 1)
    return t*t*(3-2*t)


def read_config(args):
    c = merge_configs(DEFAULT,{})
    base = ROOT
    supplied = {}
    if args.config:
        file = Path(args.config).resolve()
        supplied = json.loads(file.read_text(encoding='utf-8'))
        base = file.parent
        supplied=resolve_visual_paths(supplied,file.parent)
        c=merge_configs(c,supplied)
        if 'svg' in supplied and 'path_id' not in supplied:
            c['path_id'] = None
    if getattr(args,'theme',None):c=merge_configs(c,load_theme(args.theme))
    for name in ['svg', 'title', 'brand', 'path_id', 'contours', 'background', 'layout']:
        value = getattr(args, name, None)
        if value is not None:
            c[name] = value
    # A new SVG selected on the CLI must not inherit Gondor's path selector.
    if args.svg is not None and args.path_id is None:
        c['path_id'] = None
    for name in ['svg', 'background']:
        if c[name]:
            p = Path(c[name])
            # Explicit CLI paths are relative to the caller, JSON paths to JSON.
            root = Path.cwd() if getattr(args,name,None) is not None else base if name in supplied else ROOT
            c[name] = str((root/p).resolve()) if not p.is_absolute() else str(p)
    c['audio'] = c['audio'] and not args.silent
    validate_animation(c)
    validate_visual(c)
    return c


def validate_animation(c):
    trace_settings(c.get('trace'))
    validate_music(music_settings(c.get("music")))
    if len(c['steps']) != len(c['durations']) or not c['steps']:
        raise ValueError('steps and durations must have the same nonzero length')
    if any(d <= .4 for d in c['durations']):
        raise ValueError('Each stage must last more than 0.4 second')
    if any(not isinstance(k,int) or k<1 for k in c['steps']):
        raise ValueError('steps must contain positive integer harmonic counts')
    if any(a>=b for a,b in zip(c['steps'],c['steps'][1:])):
        raise ValueError('steps must be strictly increasing')
    if c['samples'] % 2 or c['samples'] < 128 or max(c['steps']) >= c['samples']//2:
        raise ValueError('samples must be even, >=128 and >2*max(steps)')
    if c['intro'] < .2 or c['outro'] < .2:
        raise ValueError('intro and outro must be >=0.2 second')
    if not 0 <= c['background_opacity'] <= 1:
        raise ValueError('background_opacity must be between 0 and 1')


def svg_paths(filename, path_id=None):
    doc = Document(str(filename))
    paths = doc.paths(path_filter=lambda e: path_id is None or e.get('id') == path_id)
    if not paths:
        raise ValueError('No vector path found. Check --path-id, or convert text/use elements to paths.')
    return paths


GEOMETRY_CACHE=OrderedDict()


def load_contour(c):
    key=(hashlib.sha256(Path(c['svg']).read_bytes()).hexdigest(),c['path_id'],c['contours'],c['samples'],c.get('layout'),max(c['steps']))
    if key not in GEOMETRY_CACHE:
        GEOMETRY_CACHE[key]=_load_contour(c)
        if len(GEOMETRY_CACHE)>4:GEOMETRY_CACHE.popitem(last=False)
    GEOMETRY_CACHE.move_to_end(key)
    z,pen,info=GEOMETRY_CACHE[key]
    return z.copy(),pen.copy(),deepcopy(info)


def _load_contour(c):
    paths = svg_paths(c['svg'],c['path_id'])
    components = [p for path in paths for p in path.continuous_subpaths() if p.length()>1e-9]
    if not components:
        raise ValueError('SVG has no nonzero-length contour')
    count = len(components)
    if c['contours'] == 'largest':
        # Prefer a closed contour, avoiding an accidental straight closing edge.
        closed = [p for p in components if p.isclosed()]
        if not closed:
            raise ValueError('No closed contour. Use --contours all for an open stroke with pen-up return.')
        components = [max(closed,key=lambda p:p.length())]
    # Flatten each curve densely, then sample by global arc length, not SVG t.
    routes = []
    total_length=sum(p.length() for p in components)
    budget=max(32768,c['samples']*4)
    for p in components:
        z = []
        for seg in p:
            # A straight segment needs only its endpoints. Spend curve samples globally.
            n = 1 if isinstance(seg,Line) else int(np.clip(math.ceil(seg.length()/total_length*budget),8,8192))
            z.extend(seg.point(t) for t in np.linspace(0,1,n,endpoint=False))
        routes.append(np.array(z+[p.end]))
    # Order disconnected components by nearest endpoint; transfer strokes have pen lifted.
    ordered = [routes.pop(0)]
    while routes:
        end=ordered[-1][-1]
        j = min(range(len(routes)),key=lambda i:min(abs(routes[i][0]-end),abs(routes[i][-1]-end)))
        route=routes.pop(j)
        if abs(route[-1]-end)<abs(route[0]-end):route=route[::-1]
        ordered.append(route)
    vertices = [ordered[0][0]]
    pen_edges = []
    for route in ordered:
        if abs(vertices[-1]-route[0]) > 1e-10:
            vertices.append(route[0]); pen_edges.append(False)
        vertices.extend(route[1:]); pen_edges.extend([True]*(len(route)-1))
    if abs(vertices[-1]-vertices[0]) > 1e-10:
        vertices.append(vertices[0]); pen_edges.append(False)
    vertices = np.array(vertices)
    lengths = abs(np.diff(vertices))
    valid = lengths>1e-12
    lengths = lengths[valid]
    a,b = vertices[:-1][valid],vertices[1:][valid]
    pen_edges = np.array(pen_edges,dtype=bool)[valid]
    distances = np.r_[0,np.cumsum(lengths)]
    samples = np.linspace(0,distances[-1],c['samples'],endpoint=False)
    edge = np.minimum(np.searchsorted(distances,samples,side='right')-1,len(lengths)-1)
    ratio = (samples-distances[edge])/lengths[edge]
    z = a[edge]+ratio*(b[edge]-a[edge])
    pen = pen_edges[edge]
    center = (z.real.max()+z.real.min())/2+1j*(z.imag.max()+z.imag.min())/2
    z -= center
    # Legacy layouts retain their common drawing/chain unit scale.
    x,y = np.fft.rfft(z.real)/len(z),np.fft.rfft(z.imag)/len(z)
    large=c.get('layout')=='classic_large'
    balanced=c.get('layout')=='balanced'
    minimal=c.get('layout') in ('minimal','balanced','classic_large')
    max_width,max_height=(380,530) if balanced or large else (470,620) if minimal else (350,520)
    size = min(max_width/max(np.ptp(z.real),1e-8),max_height/max(np.ptp(z.imag),1e-8))
    auxiliary=[]
    for coeff,rotation,limits in [
        (x,0,(-265,285,-180,215) if large else (-335,285,-180,215) if balanced else (-550,305,-180,215) if minimal else (-240,215,-180,215)),
        (y,np.pi/2,(-230,235,-260,310) if large else (-230,235,-280,360) if balanced else (-230,235,-380,370) if minimal else (-230,235,-330,310))]:
        k = max(c['steps']); ns=np.arange(1,k+1)
        r = 2*abs(coeff[1:k+1])
        ts=np.linspace(0,1,512)
        vectors=r[:,None]*np.exp(1j*(2*np.pi*ns[:,None]*ts+np.angle(coeff[1:k+1,None])+rotation))
        starts=np.vstack([np.zeros((1,len(ts)),complex),np.cumsum(vectors,axis=0)[:-1]])
        if rotation==0:
            starts+=coeff[0].real
        else:
            starts+=1j*coeff[0].real
        bounds=[(starts.real-r[:,None]).min(),(starts.real+r[:,None]).max(),
                (starts.imag-r[:,None]).min(),(starts.imag+r[:,None]).max()]
        if minimal:
            lo,hi=(bounds[2],bounds[3]) if rotation==0 else (bounds[0],bounds[1])
            space=(400 if rotation==0 else 455) if large else (480 if rotation==0 else 460) if balanced else (520 if rotation==0 else 850)
            size=min(size,space/max(hi-lo,1e-8))
            auxiliary.append((lo,hi))
        for j,(bound,limit) in enumerate(zip(bounds,limits)):
            if minimal and ((rotation==0 and j>=2) or (rotation!=0 and j<2)):continue
            if bound*limit>0:
                size=min(size,abs(limit/bound))
    scale=size*.97;z*=scale
    info={'available_components':count,'selected_components':len(components),
          'pen_down_fraction':float(pen.mean()),'normalization_scale':float(scale)}
    if minimal:
        info['geometry']={'center':[715,1160] if large else [715,1080] if balanced else [620,1100],
            'x_root_y':float((670 if large else 510 if balanced else 480)-np.mean(auxiliary[0])*scale),
            'y_root_x':float((287.5 if large else 285 if balanced else 485)-np.mean(auxiliary[1])*scale)}
    return z,pen,info


class Canvas:
    """Draw in 1080×1920 logical coordinates, rasterize directly at output resolution."""
    def __init__(self,im,fonts=None,safe_area=None):
        self.im=im; self.draw=ImageDraw.Draw(im)
        scale,offset=safe_transform(safe_area) if safe_area is not None else (1.,(0.,0.))
        self.s=im.width/1080*scale
        self.offset=tuple(v*im.width/1080 for v in offset)
        self.fonts=fonts or DEFAULT_FONTS
        self.cache={};self._last_points=None;self._last_coords=None
    def xy(self,p): return tuple(float(a)*self.s+self.offset[i%2] for i,a in enumerate(p))
    def line(self,p,color,width=1):
        if len(p)>1:
            if p is self._last_points:coords=self._last_coords
            elif isinstance(p,np.ndarray) and len(p)>8:
                coords=[tuple(q) for q in (p*self.s+np.array(self.offset)).tolist()]
            else:coords=[self.xy(q) for q in p]
            self._last_points=p;self._last_coords=coords
            self.draw.line(coords,fill=color,width=max(1,round(width*self.s)),joint='curve')
    def circle(self,xy,r,color,width=1,fill=None):
        x,y=xy
        self.draw.ellipse(self.xy((x-r,y-r,x+r,y+r)),outline=color,fill=fill,
                          width=max(1,round(width*self.s)))
    def text(self,xy,value,size=20,color='#ffffff',kind='sans',anchor=None):
        self.draw.text(self.xy(xy),value,font=font_for(self.fonts,round(size*self.s),kind),fill=color,anchor=anchor,
                       spacing=round(10*self.s))


FONT_CACHE={}


def font_for(fonts,size,kind='sans'):
    # File path is part of the cache key: successive identities may change fonts.
    key=(str(Path(fonts[kind]).resolve()),size)
    if key not in FONT_CACHE:FONT_CACHE[key]=ImageFont.truetype(key[0],size)
    return FONT_CACHE[key]


class Film:
    def __init__(self,c,width,height,visual=True):
        self.c=c; self.w=width; self.h=height; self.colors=c['colors']
        self.z,self.pen,self.info=load_contour(c)
        self.cx=np.fft.rfft(self.z.real)/len(self.z)
        self.cy=np.fft.rfft(self.z.imag)/len(self.z)
        self.ends=np.cumsum(c['durations'])+c['intro']
        self.total=float(self.ends[-1]+c['outro'])
        self.approx={};self.errors={};self.visual=visual
        for k in c['steps'] if visual else []:
            x,y=self.cx.copy(),self.cy.copy();x[k+1:]=0;y[k+1:]=0
            a=np.fft.irfft(x*len(self.z),n=len(self.z))+1j*np.fft.irfft(y*len(self.z),n=len(self.z))
            self.approx[k]=a
            self.errors[k]=float(np.sqrt(np.mean(abs(a[self.pen]-self.z[self.pen])**2)))
        if not visual:
            self.last=max(c['steps']);self.bg=None;return
        self.bg=self.background()
        self.grid=np.arange(0,len(self.z),2)
        cuts=np.flatnonzero(np.diff(np.r_[False,self.pen,False]))
        self.visible_runs=[np.unique(np.r_[np.arange(a,b,2),b-1]) for a,b in zip(cuts[::2],cuts[1::2])]
        self.star_ids=np.unique(np.r_[np.linspace(0,len(self.z)-1,64,dtype=int),
            np.argmin(self.z.real),np.argmax(self.z.real),np.argmin(self.z.imag),np.argmax(self.z.imag)])
        self.final_transition=None
        self.last=max(c['steps'])
        self.minimal_hero_scale=min(c['hero_scale'],600/max(np.ptp(self.z.real),1e-8),800/max(np.ptp(self.z.imag),1e-8))
        self._chain_cache={};self._signal_cache={};self._stage_cache=OrderedDict();self._hero=None
        self.composition=adaptive_composition(self.z,self.pen,self.approx,self.cx,self.cy,self.last,self.info['geometry']) if visual and c.get('layout')=='classic_large' else None
        if self.composition:self.info['composition']=self.composition

    def background(self):
        # Original astrophotography artwork, dimmed under the scientific visualization.
        base=Image.new('RGB',(self.w,self.h),self.colors['background'])
        if self.c['background']:
            file=Path(self.c['background'])
            if not file.is_file(): raise FileNotFoundError(file)
            art=ImageOps.fit(Image.open(file).convert('RGB'),(self.w,self.h),method=Image.Resampling.LANCZOS)
            base=Image.blend(base,art,self.c['background_opacity'])
        # Darken center/top, leave more mountain texture visible near the bottom.
        yy=np.linspace(0,1,self.h)[:,None]
        dim=self.c.get('background_dimming',{'top':.25,'bottom':.03})
        alpha=np.clip(dim['top']+(dim['bottom']-dim['top'])*yy,0,1)
        pixels=np.asarray(base).astype(np.float32)
        pixels*=1-alpha[:,:,None]
        return Image.fromarray(np.uint8(pixels))

    def state(self,t):
        i=min(int(np.searchsorted(self.ends,t,side='right')),len(self.c['steps'])-1)
        start=self.c['intro'] if i==0 else self.ends[i-1]
        phase=float(np.clip((t-start-.08)/(self.c['durations'][i]-.32),0,1))
        return i,self.c['steps'][i],phase

    def draw_trace(self,cv,z,center=(690,1180),factor=1,color=None,width=2,upto=1,ghost=False):
        limit=int(upto*(len(z)-1))
        for ids in self.visible_runs:
            ids=ids[:np.searchsorted(ids,limit,side='right')]
            if not len(ids):continue
            values=z[ids]
            if len(values)==1:
                if not ghost:cv.circle((center[0]+values[0].real*factor,center[1]+values[0].imag*factor),max(.6,width/2),color or self.colors['trace'],fill=color or self.colors['trace'])
                continue
            if upto==1 and self.pen[-1] and self.pen[0] and len(self.visible_runs)==1:
                values=np.r_[values,values[0]]
            run=np.column_stack((center[0]+values.real*factor,center[1]+values.imag*factor))
            if not ghost:
                cv.line(run,mix(self.colors['background'],color or self.colors['trace'],.20),width+5)
            cv.line(run,color or self.colors['trace'],width)

    def brand(self,cv):
        # Two intersecting orbits: a compact, reusable vector brand mark.
        col=self.colors['x']
        cv.circle((98,174),13,col,1.5)
        cv.circle((107,174),13,self.colors['y'],1.5)
        cv.circle((109,162),2.5,col,fill=col)
        cv.text((137,158),self.c['brand'],24,self.colors['ink'],kind='bold')
        cv.text((866,164),f"N° {self.c['episode']}",17,self.colors['muted'],anchor='ra')

    def constellation(self,cv,z,t,phase=1,center=(690,1180),factor=1,opacity=1):
        for n,j in enumerate(self.star_ids):
            if j/len(z)>phase or not self.pen[j]:continue
            x,y=center[0]+z[j].real*factor,center[1]+z[j].imag*factor
            twinkle=.75+.25*np.sin(t*2.2+n*2.4)**2
            radius=(1.35+(n%7==0)*1.1)*twinkle
            # A brief sparkle when the drawing point passes this star.
            age=max(0,phase-j/len(z))
            radius*=1+.65*np.exp(-age*55)
            color=mix(self.colors['background'],self.colors['ink'],opacity)
            cv.circle((x,y),radius*3.1,mix(self.colors['background'],self.colors['y'],.15*opacity),fill=
                      mix(self.colors['background'],self.colors['y'],.15*opacity))
            cv.circle((x,y),radius,color,fill=color)
            if n%11==0:
                ray=radius*3.6
                raycol=mix(self.colors['background'],self.colors['x'],.65*opacity)
                cv.line([(x-ray,y),(x+ray,y)],raycol,1)
                cv.line([(x,y-ray),(x,y+ray)],raycol,1)
                cv.circle((x,y),radius,color,fill=color)

    def chain(self,cv,c,k,phase,root,rotation,color,quiet=False,display_scale=1):
        key=(id(c),k,rotation,display_scale,color,quiet)
        if key not in self._chain_cache:
            n=np.arange(1,k+1);r=2*abs(c[1:k+1])
            self._chain_cache[key]=(n,r,np.angle(c[1:k+1])+rotation,
                np.flatnonzero(r*display_scale>=.2),mix(self.colors['background'],color,.24 if quiet else .33),
                mix(self.colors['background'],color,.74) if quiet else mix(color,self.colors['ink'],.18))
        n,r,angle,visible,outline,ray=self._chain_cache[key]
        p=complex(*root)+np.r_[0,np.cumsum(r*np.exp(1j*(2*np.pi*n*phase+angle)))]*display_scale
        for j in visible:
            a,b=p[j],p[j+1];radius=r[j]*display_scale
            if radius>=.65:cv.circle((a.real,a.imag),radius,outline,1)
            cv.line([(a.real,a.imag),(b.real,b.imag)],ray,1.4 if radius>3 else 1)
        cv.circle((p[-1].real,p[-1].imag),4,color,fill=color)
        return p[-1]

    def signal(self,cv,v,phase,root,color,label,label_size=21,width=270,part='all'):
        key=(id(v.base) if v.base is not None else id(v),v.strides,root,width)
        if key not in self._signal_cache:
            x,y=root;a=v[::24]/max(abs(v).max(),1)*28
            self._signal_cache[key]=np.column_stack((x+np.linspace(0,width,len(a)),y+a))
        p=self._signal_cache[key];x,y=root
        if part!='dynamic':
            cv.text((x,y-62),label,label_size,color)
            cv.line([(x,y),(x+width,y)],mix(self.colors['background'],color,.2))
            cv.line(p,mix(self.colors['background'],color,.3),1)
        if part!='static':
            cv.line(p[:max(2,int(phase*len(p)))],color,2)
            at=phase*(len(p)-1);j=min(int(at),len(p)-2);height=p[j,1]+(p[j+1,1]-p[j,1])*(at-j)
            cv.circle((x+phase*width,height),3,color,fill=color)

    def restyle(self,c):
        self.c=c;self.colors=c['colors'];self.ends=np.cumsum(c['durations'])+c['intro'];self.total=float(self.ends[-1]+c['outro'])
        self.bg=self.background();self._chain_cache.clear();self._signal_cache.clear();self._stage_cache.clear();self.final_transition=None;self._hero=None

    def hero_transform(self):
        if self._hero is None:
            a=self.approx[self.last];bbox=value_bounds(a,self.pen)
            hero=fit_bounds(bbox,(85,500,995,1460),36)
            drawing=self.composition['drawing'] if self.composition else {'scale':1.}
            hero['scale']=min(hero['scale'],drawing['scale']*self.c['hero_scale'])
            hero['center']=[540-hero['scale']*(bbox[0]+bbox[2])/2,980-hero['scale']*(bbox[1]+bbox[3])/2]
            self._hero=hero
        return self._hero

    def frame_hero(self,t):
        im=self.bg.copy();cv=Canvas(im,self.c.get('fonts'),safe_settings(self.c.get('safe_area')));col=self.colors
        a=self.approx[self.last];hero=self.hero_transform()
        drawing=self.composition['drawing'] if self.composition else {'center':self.info.get('geometry',{}).get('center',[690,1180]),'scale':1.}
        intro=t<self.c['intro']
        if intro:
            title=f'Ce dessin cache\n{2*self.last} cercles.';subtitle='REGARDE LES FRÉQUENCES DESSINER.'
            scale=hero['scale'];center=hero['center'];opacity=float(smooth(t/.24))
        else:
            title=self.c['final_title'];subtitle=self.c['title'].upper();opacity=1
            amount=float(smooth((t-self.ends[-1])/.8))
            scale=drawing['scale']+(hero['scale']-drawing['scale'])*amount
            center=np.array(drawing['center'])+(np.array(hero['center'])-drawing['center'])*amount
        self.brand(cv);cv.text((84,257),title,49,col['ink'],kind='bold');cv.text((86,425),subtitle,20,col['x'])
        self.draw_trace(cv,a,center,scale,mix(col['background'],col['trace'],opacity),1.7)
        self.constellation(cv,a,t,center=center,factor=scale,opacity=opacity)
        cv.text((86,1505),f"1 → {self.last} cercles par axe",28,col['ink']);cv.text((86,1555),self.c['tagline'],18,col['muted'])
        cv.line([(86,1612),(995,1612)],mix(col['background'],col['trace'],.28))
        cv.text((86,1635),self.c['brand']+'  /  '+self.c['episode'],17,col['muted'])
        if not intro and t-self.ends[-1]<.65:
            if self.final_transition is None:self.final_transition=self.frame(float(self.ends[-1]-.00001))
            im=Image.blend(self.final_transition,im,float(smooth((t-self.ends[-1])/.65)))
        return im

    def frame_adaptive(self,t):
        i,k,phase=self.state(t);a=self.approx[k];g=self.composition;col=self.colors
        landscape=g['landscape'];drawing=g['drawing'];center=drawing['center'];scale=drawing['scale']
        signals=[(a.real,(85,520) if landscape else (85,610),col['x'],'x(t) · cos'),
                 (a.imag,(690,520) if landscape else (85,745),col['y'],'y(t) · sin')]
        if k not in self._stage_cache:
            base=self.bg.copy();cv=Canvas(base,self.c.get('fonts'),safe_settings(self.c.get('safe_area')))
            self.brand(cv);cv.text((83,244),self.c['title'],44,col['ink'],kind='serif');cv.text((86,305),self.c['tagline'],18,col['muted'])
            cv.text((84,350),f'{k:03d}',64,col['trace'],kind='bold')
            cv.text((300 if k>=1000 else 254,376),'CERCLES / AXE',21,col['muted'])
            cv.text((995,380),f'{i+1:02d} / {len(self.c["steps"]):02d}',18,col['muted'],anchor='ra')
            cv.line([(86,432),(995,432)],mix(col['background'],col['trace'],.22))
            for v,root,color,label in signals:self.signal(cv,v,phase,root,color,label,width=265,part='static')
            cv.text((575,550) if landscape else (555,475),'PROJECTION X',17,col['x'])
            cv.text((85,550) if landscape else (85,795),'PROJECTION Y',17,col['y'])
            self.draw_trace(cv,self.z,center,scale,mix(col['background'],col['trace'],.17),1,ghost=True)
            caption=self.c['captions']['early' if k<=3 else 'middle' if k<=24 else 'late']
            cv.text((86,1508),caption,28,col['ink']);cv.text((86,1556),'Deux signaux. Un seul tracé.',21,col['muted'])
            for n,step in enumerate(self.c['steps']):
                x=90+n*min(110,900/max(len(self.c['steps'])-1,1))
                cv.circle((x,1613),3.5,col['trace'] if n<=i else col['muted'],fill=col['trace'] if n<=i else None)
                cv.text((x,1637),str(step),16,col['ink'] if n==i else col['muted'],anchor='ma')
            cv.line([(86,1690),(995,1690)],mix(col['background'],col['muted'],.2))
            self._stage_cache[k]=base
            if len(self._stage_cache)>2:self._stage_cache.popitem(last=False)
        im=self._stage_cache[k].copy();cv=Canvas(im,self.c.get('fonts'),safe_settings(self.c.get('safe_area')))
        for v,root,color,label in signals:self.signal(cv,v,phase,root,color,label,width=265,part='dynamic')
        xr,yr=g['x'],g['y'];xs,ys=xr['scale'],yr['scale']
        ex=self.chain(cv,self.cx,k,phase,(xr['center'][0]+self.cx[0].real*xs,xr['center'][1]),0,col['x'],display_scale=xs)
        ey=self.chain(cv,self.cy,k,phase,(yr['center'][0],yr['center'][1]+self.cy[0].real*ys),np.pi/2,col['y'],display_scale=ys)
        pen=(center[0]+scale*(ex.real-xr['center'][0])/xs,center[1]+scale*(ey.imag-yr['center'][1])/ys)
        cv.line([(ex.real,ex.imag),pen],mix(col['background'],col['x'],.52),1)
        cv.line([(ey.real,ey.imag),pen],mix(col['background'],col['y'],.52),1)
        self.draw_trace(cv,a,center,scale,col['trace'],1.7,upto=phase);self.constellation(cv,a,t,phase,center=center,factor=scale)
        j=min(int(phase*len(a)),len(a)-1)
        if self.pen[j]:cv.circle(pen,8,col['trace'],1);cv.circle(pen,3.5,col['ink'],fill=col['ink'])
        cv.line([(86,1690),(86+909*t/self.total,1690)],mix(col['background'],col['x'],.7),2)
        return im

    def frame(self,t):
        image=self._frame_content(t)
        area=safe_settings(self.c.get('safe_area'))
        if not area['enabled']:return image
        # Keep decorative backgrounds full bleed. Clip only the content, including
        # unusually long titles or overshooting low-frequency approximations.
        box=safe_box(area,self.w,self.h)
        result=self.bg.copy();result.paste(image.crop(box),box)
        return result

    def _frame_content(self,t):
        if t<self.c['intro'] or t>=self.ends[-1]:return self.frame_hero(t)
        if self.composition:return self.frame_adaptive(t)
        if self.c.get('layout') in ('minimal','balanced'):return self.frame_minimal(t)
        im=self.bg.copy();cv=Canvas(im,self.c.get('fonts'),safe_settings(self.c.get('safe_area')));col=self.colors
        large=self.c.get('layout')=='classic_large'
        geom=self.info.get('geometry',{})
        center=tuple(geom.get('center',[690,1180]))
        hero_scale=min(self.c['hero_scale'],640/max(np.ptp(self.z.real),1e-8),670/max(np.ptp(self.z.imag),1e-8)) if large else self.c['hero_scale']
        self.brand(cv)
        intro=t<self.c['intro'];outro=t>=self.ends[-1]
        i,k,phase=self.state(t);a=self.approx[k]
        cv.text((83,244),self.c['title'],50,col['ink'],kind='serif')
        cv.text((86,315),self.c['tagline'],18,col['muted'])
        cv.text((84,363),f'{k:03d}',66,col['trace'],kind='bold')
        cv.text((254,386),'CERCLES / AXE',21,col['muted'])
        cv.text((866,391),f'{i+1:02d} / {len(self.c["steps"]):02d}',18,col['muted'],anchor='ra')
        cv.line([(86,456),(865,456)],mix(col['background'],col['trace'],.22))

        self.signal(cv,a.real,phase,(86,615),col['x'],'x(t) · cos')
        self.signal(cv,a.imag,phase,(86,764),col['y'],'y(t) · sin')
        cv.text((552,481),'PROJECTION X',17,col['x'])
        cv.text((87,877),'PROJECTION Y',17,col['y'])
        self.draw_trace(cv,self.z,center=center,color=mix(col['background'],col['trace'],.21),width=1,ghost=True)
        ex=self.chain(cv,self.cx,k,phase,(center[0]+self.cx[0].real,geom.get('x_root_y',630)),0,col['x'])
        ey=self.chain(cv,self.cy,k,phase,(geom.get('y_root_x',300),center[1]+self.cy[0].real),np.pi/2,col['y'])
        pen=(ex.real,ey.imag)
        cv.line([(ex.real,ex.imag),pen],mix(col['background'],col['x'],.52),1)
        cv.line([(ey.real,ey.imag),pen],mix(col['background'],col['y'],.52),1)
        self.draw_trace(cv,a,center=center,color=col['trace'],width=1.7,upto=phase)
        self.constellation(cv,a,t,phase,center=center)
        j=min(int(phase*len(a)),len(a)-1)
        if self.pen[j]:
            cv.circle(pen,9,col['trace'],1)
            cv.circle(pen,3.8,col['ink'],fill=col['ink'])
        caption=self.c['captions']['early' if k<=3 else 'middle' if k<=24 else 'late']
        cv.text((86,1508),caption,30,col['ink'])
        cv.text((86,1556),'Deux signaux. Un seul tracé.',21,col['muted'])
        for n,step in enumerate(self.c['steps']):
            x=90+n*min(96,768/max(len(self.c['steps'])-1,1))
            cv.circle((x,1613),3.5,col['trace'] if n<=i else mix(col['background'],col['ink'],.25),
                      fill=col['trace'] if n<=i else None)
            cv.text((x,1637),str(step),16,col['ink'] if n==i else col['muted'],anchor='ma')
        # A tiny moving playhead adds continuity without obscuring the shape.
        cv.line([(86,1690),(865,1690)],mix(col['background'],col['muted'],.2))
        cv.line([(86,1690),(86+779*t/self.total,1690)],mix(col['background'],col['x'],.7),2)
        return im

    def frame_minimal(self,t):
        """A large drawing, two circle chains, one quiet counter. No chart panels."""
        im=self.bg.copy();cv=Canvas(im,self.c.get('fonts'),safe_settings(self.c.get('safe_area')));col=self.colors
        balanced=self.c.get('layout')=='balanced'
        cv.circle((90,177),8,col['x'],1)
        cv.circle((96,177),8,col['y'],1)
        cv.text((116,165),self.c['brand'],16,col['muted'])
        intro=t<self.c['intro'];outro=t>=self.ends[-1]
        center=tuple(self.info['geometry']['center'])
        if intro or outro:
            if intro:
                scale=self.minimal_hero_scale*.94
                location=(480,970) if balanced else (500,1030);opacity=float(smooth(t/.22))
            else:
                p=float(smooth((t-self.ends[-1])/.8))
                scale=1+(self.minimal_hero_scale-1)*p
                hero=(480,970) if balanced else (500,1030)
                location=(center[0]+(hero[0]-center[0])*p,center[1]+(hero[1]-center[1])*p)
                opacity=1
            self.draw_trace(cv,self.approx[self.last],location,scale,
                            mix(col['background'],col['trace'],opacity),1.7)
            self.constellation(cv,self.approx[self.last],t,center=location,factor=scale,opacity=opacity)
            # The subject's name is the only title. Opening/closing durations are preserved.
            cv.text((480,310) if balanced else (500,1515),self.c['title'],34 if balanced else 25,
                    mix(col['background'],col['ink'],opacity),anchor='ma',kind='serif' if balanced else 'sans')
            if outro and t-self.ends[-1]<.65:
                if self.final_transition is None:
                    self.final_transition=self.frame_minimal(float(self.ends[-1]-.00001))
                im=Image.blend(self.final_transition,im,float(smooth((t-self.ends[-1])/.65)))
            return im
        i,k,phase=self.state(t);a=self.approx[k]
        if balanced:
            cv.text((85,238),self.c['title'],34,col['ink'],kind='serif')
            self.signal(cv,a.real,phase,(85,470),col['x'],'x(t) = x₀ + Σ Aₙ cos(...)',17,260)
            self.signal(cv,a.imag,phase,(85,650),col['y'],'y(t) = y₀ + Σ Bₙ sin(...)',17,260)
        cv.text((900,249 if balanced else 169),f'{k} cercle'+('s' if k>1 else '')+' / axe',18,col['muted'],anchor='ra')
        geom=self.info['geometry']
        ex=self.chain(cv,self.cx,k,phase,(center[0]+self.cx[0].real,geom['x_root_y']),0,col['x'],True)
        ey=self.chain(cv,self.cy,k,phase,(geom['y_root_x'],center[1]+self.cy[0].real),np.pi/2,col['y'],True)
        pen=(ex.real,ey.imag)
        cv.line([(ex.real,ex.imag),pen],mix(col['background'],col['x'],.38),1)
        cv.line([(ey.real,ey.imag),pen],mix(col['background'],col['y'],.38),1)
        self.draw_trace(cv,a,center=center,color=col['trace'],width=1.7,upto=phase)
        self.constellation(cv,a,t,phase,center=center)
        j=min(int(phase*len(a)),len(a)-1)
        if self.pen[j]:
            cv.circle(pen,7,col['trace'],1)
            cv.circle(pen,3.2,col['ink'],fill=col['ink'])
        start=self.c['intro'] if i==0 else self.ends[i-1]
        age=t-start
        # Three short captions, briefly visible, leave most of the video quiet.
        if k in (5,64,self.last) and age<1.5:
            fade=float(smooth(age/.25)*smooth((1.5-age)/.4))
            key='early' if k==5 else 'middle' if k==64 else 'late'
            cv.text((500,1515),self.c['captions'][key],20,
                    mix(col['background'],col['muted'],fade),anchor='ma')
        return im

    def synthesize(self,path):
        m=music_settings(self.c.get('music'))
        if m['mode']=='classic':
            report=self._synthesize_classic(path);report['mode']='classic';report['settings']=m
            return report
        from music import synthesize
        return synthesize(self.z,self.pen,self.cx,self.cy,self.c,self.total,path)

    def _synthesize_classic(self,path):
        """Original C-pentatonic score plus Fourier-controlled harmonic drone."""
        sr=48000;n=round(self.total*sr);t=np.arange(n)/sr
        audio=np.zeros((n,2),np.float64)
        # Soft pentatonic arpeggio. No samples or external music.
        notes=[72,76,79,74,81,79,76,74,72,79,81,76,74,79,76,67]
        for j,on in enumerate(np.arange(0,self.total,.5)):
            a=round(on*sr);length=min(round(1.5*sr),n-a)
            u=np.arange(length)/sr
            midi=notes[j%len(notes)]
            f=440*2**((midi-69)/12)
            env=(1-np.exp(-u/.012))*np.exp(-u/.4)*np.minimum(1,(1.5-u)/.12)
            sound=(np.sin(2*np.pi*f*u)+.16*np.sin(2*np.pi*2*f*u)*np.exp(-u/.2))*env*.065
            pan=.25+.5*(.5+.5*np.sin(j*1.7))
            audio[a:a+length,0]+=sound*np.sqrt(1-pan)
            audio[a:a+length,1]+=sound*np.sqrt(pan)
        # Actual normalized x/y FFT magnitudes control partial amplitudes.
        # Playback is transposed to C3; twelve partials cap brightness.
        count=min(12,self.last)
        for axis,coeff in enumerate([self.cx,self.cy]):
            weights=2*abs(coeff[1:count+1]);weights/=max(np.linalg.norm(weights),1e-9)
            for harmonic in range(1,count+1):
                gate=np.zeros(n)
                for k,start,end in zip(self.c['steps'],[self.c['intro']]+list(self.ends[:-1]),self.ends):
                    if k>=harmonic:
                        a=round(start*sr);b=round(end*sr)
                        gate[a:b]=1
                if self.last>=harmonic:gate[round(self.ends[-1]*sr):]=1
                # Smooth entry of each partial and each stage boundary.
                from scipy.ndimage import gaussian_filter1d
                gate=gaussian_filter1d(gate[::240],sigma=8,mode='nearest')
                gate=np.interp(np.arange(n),np.arange(len(gate))*240,gate)
                frequency=130.81278265*harmonic
                tone=np.sin(2*np.pi*frequency*t+np.angle(coeff[harmonic]))
                breath=.82+.18*np.sin(2*np.pi*.25*t+axis)
                value=tone*gate*breath*weights[harmonic-1]*np.exp(-harmonic/7)*.075
                audio[:,axis]+=value
                audio[:,1-axis]+=.38*value
        # Low, warm tonic breathing on the half-second beat.
        beat_phase=t%.5
        bass=np.sin(2*np.pi*65.4063913*t)*np.exp(-beat_phase/.11)*.035
        bass*=1-np.exp(-beat_phase/.006)
        audio+=bass[:,None]
        # Delicate stage chimes: accents tied to the visible circle-count changes.
        for index,on in enumerate([self.c['intro']]+list(self.ends[:-1])):
            a=round(on*sr);length=min(sr,n-a);u=np.arange(length)/sr
            freq=440*2**(([79,81,84,86,88][index%5]-69)/12)
            env=(1-np.exp(-u/.004))*np.exp(-u/.18)
            bell=np.sin(2*np.pi*freq*u)*env*.055
            audio[a:a+length]+=(bell[:,None]*np.array([.72,.72]))
        # A restrained two-tap stereo echo; deterministic, without feedback.
        dry=audio.copy()
        for delay,gain in [(.25,.17),(.375,.10)]:
            shift=round(delay*sr);audio[shift:]+=dry[:-shift,::-1]*gain
        fade_in=smooth(t/.3);fade_out=smooth((self.total-t)/1.2)
        audio*= (fade_in*fade_out)[:,None]
        audio=np.tanh(audio*1.15)
        audio*=.85/max(np.max(abs(audio)),1e-8)
        with wave.open(str(path),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr)
            f.writeframes((audio*32767).astype('<i2').tobytes())
        return {'sample_rate':sr,'channels':2,'synthesis_peak_dbfs':float(20*np.log10(np.max(abs(audio)))),
                'pitch_reference_hz':130.81278265,'audible_fourier_partials_per_axis':count}


def command(cmd):
    subprocess.run(cmd,check=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config')
    ap.add_argument('--theme',help='Nom du thème intégré ou fichier JSON')
    ap.add_argument('--check',action='store_true',help='Valider sans tracer ni produire de rendu')
    source=ap.add_mutually_exclusive_group()
    source.add_argument('--svg');source.add_argument('--image',help='dark line art on a light background')
    ap.add_argument('--trace-mode',choices=['auto','lineart','outline','edges'],default='auto')
    ap.add_argument('--detail',choices=['low','medium','high'],default='medium')
    ap.add_argument('--path-id')
    ap.add_argument('--title');ap.add_argument('--brand');ap.add_argument('--background')
    ap.add_argument('--contours',choices=['largest','all'])
    ap.add_argument('--layout',choices=['classic','classic_large','minimal','balanced'])
    ap.add_argument('--preset',choices=PRESETS,default='social')
    ap.add_argument('--threads',type=int,default=4,help='Threads encodeur, de 1 à 16')
    ap.add_argument('--fps',type=int);ap.add_argument('--silent',action='store_true')
    ap.add_argument('--list-paths',action='store_true');ap.add_argument('--preview',action='store_true')
    ap.add_argument('--audio-only',action='store_true',help='Bande sonore seule, WAV et MP3, sans images ni vidéo')
    ap.add_argument('--export-social',action='store_true',help='also downscale a master to 1080×1920')
    ap.add_argument('--output',default=str(ROOT/'output'/'orbite'))
    args=ap.parse_args();c=read_config(args)
    if not 1<=args.threads<=16:ap.error('Threads encodeur : de 1 à 16.')
    if args.audio_only and (args.preview or not c['audio']):ap.error('Audio seul : activer la musique et ne pas utiliser --preview.')
    if args.check:
        source=Path(args.image or args.svg or c['svg']).resolve()
        result=validate_input(source,args.path_id if args.image else c['path_id'])
        width,height,fps=PRESETS[args.preset];fps=args.fps or fps
        if not 1<=fps<=120:raise ValueError('fps must be between 1 and 120')
        print(json.dumps({'status':'ok','no_render':True,'source':result,
            'theme':c.get('theme_name','configuration'),'resolution':[width,height],
            'fps':fps,'colors':c['colors'],'background':c['background'],'fonts':c['fonts'],'safe_area':c['safe_area'],'music':c['music']},ensure_ascii=False,indent=2))
        return
    prefix=Path(args.output).resolve();prefix.parent.mkdir(parents=True,exist_ok=True)
    if args.image:
        from trace_image import trace
        traced=Path(str(prefix)+'_trace.svg')
        print(json.dumps(trace(Path(args.image).resolve(),traced,mode=args.trace_mode,detail=args.detail,options=c.get('trace')),ensure_ascii=False),flush=True)
        c['svg']=str(traced);c['path_id']=args.path_id
        c['contours']=args.contours or 'all'
        if not args.config:
            c['samples']=32768
            c['steps']=[1,2,3,6,12,32,96,256,768]
            c['durations']=[1.5,1.5,2,2,2.5,3,3.5,4.5,7]
            c['title']=args.title or 'Dessin céleste'
            c['hero_scale']=2
    if args.list_paths:
        for p in svg_paths(c['svg']):
            components=p.continuous_subpaths()
            print(json.dumps({'id':p.element.get('id'),'tag':p.element.tag.split('}')[-1],
                  'components':len(components),'length':round(p.length(),3),
                  'closed':all(q.isclosed() for q in components)},ensure_ascii=False))
        return
    require_ffmpeg()
    width,height,fps=PRESETS[args.preset];fps=args.fps or fps
    if not 1<=fps<=120:raise ValueError('fps must be between 1 and 120')
    film=Film(c,width,height,visual=not args.audio_only)
    print(f'{width}×{height} · {fps} fps · {film.total:g} s',flush=True)
    report={'resolution':[width,height],'fps':fps,'duration_s':film.total,'svg':film.info,
            'rms_logical_pixels':film.errors,'config':c}
    reportfile=Path(str(prefix)+'_report.json')
    if not args.audio_only:
        # Save PNGs only when a visual render was requested.
        for tag,t in [('cover',film.total-.2),('drawing',float(film.ends[min(5,len(film.ends)-1)]-.3)),
                      ('hook',min(.7,c['intro']*.7))]:
            film.frame(t).save(str(prefix)+f'_{tag}.png')
    if args.preview:
        reportfile.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        return
    wavfile=Path(str(prefix)+'_soundtrack.wav')
    if c['audio']:
        print('Composition musicale et normalisation du niveau…',flush=True)
        raw=Path(str(prefix)+'_raw.wav');report['audio']=film.synthesize(raw)
        report['audio']['mastering']=master_audio(raw,wavfile,c.get('music'))
        raw.unlink()
    if args.audio_only:
        mp3=Path(str(prefix)+'_soundtrack.mp3')
        command([require_ffmpeg(),'-v','error','-nostdin','-y','-i',str(wavfile),'-c:a','libmp3lame','-b:a','192k',str(mp3)])
        reportfile.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Musique prête : {mp3}',flush=True)
        return
    tempfile=Path(str(prefix)+'_silent.mp4')
    cmd=[require_ffmpeg(),'-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}',
         '-r',str(fps),'-i','-','-an','-c:v','libx264','-threads',str(args.threads),'-preset','fast','-crf','18',
         '-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709',
         '-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709,'
               'setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709',
         '-movflags','+faststart',str(tempfile)]
    proc=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    frames=round(film.total*fps)
    try:
        for frame in range(frames):
            proc.stdin.write(film.frame(frame/fps).tobytes())
            if frame%(fps*2)==0:print(f'{frame/fps:04.1f} / {film.total:04.1f} s',flush=True)
    finally:
        proc.stdin.close()
    if proc.wait():raise RuntimeError('FFmpeg encode failed')
    final=Path(str(prefix)+f'_{width}x{height}.mp4')
    if c['audio']:
        command([require_ffmpeg(),'-v','error','-y','-i',str(tempfile),'-i',str(wavfile),
                 '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','192k',
                 '-t',str(frames/fps),'-movflags','+faststart',str(final)])
        tempfile.unlink()
    else:tempfile.replace(final)
    if args.export_social and width>1080:
        social=Path(str(prefix)+'_1080x1920.mp4')
        command([require_ffmpeg(),'-v','error','-y','-i',str(final),'-vf','scale=1080:1920:flags=lanczos,'
                 'setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709',
                 '-c:v','libx264','-threads',str(args.threads),'-preset','fast','-crf','18','-pix_fmt','yuv420p',
                 '-c:a','copy','-movflags','+faststart',str(social)])
    reportfile.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Done: {final}',flush=True)


if __name__=='__main__':
    main()
