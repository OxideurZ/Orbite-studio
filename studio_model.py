"""Desktop editor state, palette suggestions, previews and background jobs. No Tk dependency."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass,field
import colorsys
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from trace_image import trace_settings,detection_preview
from install import data_root

import numpy as np
from PIL import Image,ImageOps
from orbite import build_style,inputs
from render_social import DEFAULT,Film,validate_animation
from themes import (ROOT,VISUAL_FIELDS,load_theme,theme_path,merge_configs,
                    resolve_visual_paths,relative_visual_paths,validate_visual)


def write_json(file,data):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    temporary=file.with_name('.'+file.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        temporary.replace(file)
    finally:
        if temporary.exists():temporary.unlink()


@dataclass
class StudioState:
    source:str=''
    output:str=field(default_factory=lambda:str(data_root()/'output'))
    quality:str='social'
    fps:int|None=None
    mode:str='auto'
    detail:str='medium'
    recursive:bool=False
    jobs:int=0
    force:bool=False
    config:dict=field(default_factory=dict)
    theme_meta:dict=field(default_factory=lambda:{'version':1,'name':'Cosmos','description':''})

    @classmethod
    def initial(cls):
        c=merge_configs(DEFAULT,build_style())
        c.pop('svg',None);c['path_id']=None;c['contours']='all';c['title']=''
        state=cls(config=c);state.apply_theme('cosmos',preserve_text=True)
        return state

    def apply_theme(self,name,preserve_text=False):
        loaded=load_theme(name)
        raw=json.loads(theme_path(name).read_text(encoding='utf-8'))
        keep={k:self.config.get(k,'') for k in ['brand','tagline']}
        self.config=merge_configs(self.config,loaded)
        if preserve_text:self.config.update(keep)
        self.theme_meta={'version':1,'name':raw.get('name',Path(name).stem),'description':raw.get('description','')}

    def validate(self,require_source=False):
        if type(self.jobs) is not int or not 0<=self.jobs<=4:raise ValueError('Choisir entre 0 et 4 traitements en parallèle.')
        if type(self.force) is not bool:raise ValueError('force doit être vrai ou faux.')
        validate_visual(self.config)
        trace_settings(self.config.get('trace'))
        for key in ['intro','outro']:
            value=self.config.get(key)
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Les durées doivent être des nombres finis.')
        if any(type(n) is not int for n in self.config['steps']):raise ValueError('Les nombres de cercles doivent être entiers.')
        if any(isinstance(d,bool) or not isinstance(d,(int,float)) or not math.isfinite(d) for d in self.config['durations']):
            raise ValueError('Chaque durée d’étape doit être un nombre fini.')
        validate_animation(self.config)
        for key in ['title','final_title','source_credit','episode']:
            if not isinstance(self.config.get(key),str):raise ValueError(f'{key} doit être un texte.')
        if self.config['layout'] not in {'classic','classic_large','minimal','balanced'}:raise ValueError('Disposition inconnue.')
        if self.config['contours'] not in {'largest','all'}:raise ValueError('Choix de contours inconnu.')
        if self.config['path_id'] is not None and not isinstance(self.config['path_id'],str):raise ValueError('Identifiant SVG invalide.')
        if not isinstance(self.config['audio'],bool):raise ValueError('audio doit être vrai ou faux.')
        zoom=self.config.get('hero_scale')
        if isinstance(zoom,bool) or not isinstance(zoom,(int,float)) or not math.isfinite(zoom) or not .1<=zoom<=10:
            raise ValueError('Le zoom final doit être compris entre 0.1 et 10.')
        if self.quality not in {'social','master'}:raise ValueError('Qualité inconnue.')
        if self.mode not in {'auto','lineart','outline','edges'} or self.detail not in {'low','medium','high'}:
            raise ValueError('Réglage d’extraction inconnu.')
        if self.fps is not None and (type(self.fps) is not int or not 1<=self.fps<=120):
            raise ValueError('Choisir une cadence entre 1 et 120 images/s.')
        if not self.theme_meta.get('name','').strip():raise ValueError('Donner un nom au style.')
        if not self.output.strip():raise ValueError('Choisir un dossier de sortie.')
        if require_source:
            if not self.source.strip():raise ValueError('Choisir une image ou un dossier pour commencer.')
            if not inputs(self.source,self.recursive):raise ValueError('Aucune image prise en charge dans ce dossier.')
        return self

    def animation_config(self):
        c=deepcopy(self.config);c.pop('svg',None)
        c['theme_name']=self.theme_meta['name']
        if not c.get('title','').strip():c.pop('title',None)
        return c

    def save_project(self,file):
        self.validate();file=Path(file).resolve()
        c=relative_visual_paths(self.config,file.parent)
        c['_pipeline']={'jobs':self.jobs,'force':self.force}
        data={'format':'orbite-studio','version':1,'source':os.path.relpath(self.source,file.parent) if self.source else '',
              'output':os.path.relpath(self.output,file.parent),'quality':self.quality,'fps':self.fps,
              'mode':self.mode,'detail':self.detail,'recursive':self.recursive,
              'config':c,'theme':deepcopy(self.theme_meta)}
        write_json(file,data)

    @classmethod
    def load_project(cls,file):
        file=Path(file).resolve();data=json.loads(file.read_text(encoding='utf-8'))
        if data.get('format')!='orbite-studio' or data.get('version')!=1:raise ValueError('Ce fichier n’est pas un projet ORBITE Studio compatible.')
        allowed={'format','version','source','output','quality','fps','mode','detail','recursive','jobs','force','config','theme'}
        if set(data)-allowed:raise ValueError('Champs de projet inconnus : '+', '.join(sorted(set(data)-allowed)))
        base=cls.initial()
        c=resolve_visual_paths(data['config'],file.parent)
        options=c.pop('_pipeline',{})
        base.jobs=options.get('jobs',0);base.force=options.get('force',False)
        base.config=merge_configs(base.config,c)
        for name in ['source','output']:
            value=data.get(name,'');setattr(base,name,str((file.parent/value).resolve()) if value else '')
        for name in ['quality','fps','mode','detail','recursive','jobs','force']:
            if name in data:setattr(base,name,data[name])
        base.theme_meta=data.get('theme',base.theme_meta)
        # Missing assets can be repaired in the editor; validation happens before execution.
        return base

    def import_animation(self,file):
        file=Path(file).resolve();data=json.loads(file.read_text(encoding='utf-8'))
        if not isinstance(data,dict):raise ValueError('La configuration doit être un objet JSON.')
        data=resolve_visual_paths(data,file.parent)
        if data.get('svg'):self.source=str((file.parent/data.pop('svg')).resolve())
        self.config=merge_configs(self.config,data)

    def save_theme(self,file):
        self.validate();file=Path(file).resolve()
        c=relative_visual_paths(self.config,file.parent)
        theme={k:c[k] for k in VISUAL_FIELDS}
        write_json(file,{**self.theme_meta,**theme})

    def command(self,action):
        self.validate(require_source=True)
        if action not in {'check','stills','preview','export','music'}:raise ValueError('Action inconnue.')
        if action=='music' and not self.config['audio']:raise ValueError('Activer la musique dans l’onglet Musique.')
        folder=Path(self.output).resolve()/'fichiers'/'.studio'/'jobs'/uuid.uuid4().hex
        config=folder/'settings.json';write_json(config,self.animation_config())
        argv=[sys.executable,'-u',str(ROOT/'orbite.py'),str(Path(self.source).resolve()),
              '--config',str(config),'--output',str(Path(self.output).resolve()),
              '--quality',self.quality,'--mode',self.mode,'--detail',self.detail]
        argv+=['--jobs',str(self.jobs)]
        if self.force:argv.append('--force')
        if self.fps is not None:argv+=['--fps',str(self.fps)]
        if self.recursive:argv.append('--recursive')
        if self.config.get('path_id'):argv+=['--path-id',self.config['path_id']]
        if action=='music':argv.append('--audio-only')
        elif action!='export':argv.append('--'+action)
        return argv


def luminance(color):
    rgb=np.array([int(color[i:i+2],16)/255 for i in (1,3,5)])
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    return float(linear@np.array([.2126,.7152,.0722]))


def contrast(a,b):
    x,y=sorted([luminance(a),luminance(b)])
    return (y+.05)/(x+.05)


def palette_from_image(file):
    """Dominant hues produce editable, contrast-aware palette suggestions."""
    with Image.open(file) as original:
        image=ImageOps.exif_transpose(original).convert('RGBA')
        image.thumbnail((128,128),Image.Resampling.LANCZOS)
        image=Image.alpha_composite(Image.new('RGBA',image.size,'#101624'),image).convert('RGB')
    quantized=image.quantize(colors=12);palette=quantized.getpalette()
    colors=[(count,tuple(palette[index*3:index*3+3])) for count,index in quantized.getcolors()]
    colors.sort(reverse=True)
    ranked=[]
    for count,color in colors:
        h,s,v=colorsys.rgb_to_hsv(*(c/255 for c in color))
        ranked.append((count*(.15+s)*(.3+min(v,.8)),h,s,v))
    ranked.sort(reverse=True);h=ranked[0][1]
    h2=next((entry[1] for entry in ranked[1:] if min(abs(entry[1]-h),1-abs(entry[1]-h))>.16), (h+.30)%1)
    average=np.mean(np.asarray(image),axis=(0,1))/255
    light=float(np.mean(average))>.64
    def hx(hue,saturation,value):return '#'+''.join(f'{round(c*255):02x}' for c in colorsys.hsv_to_rgb(hue,saturation,value))
    bg=hx(h,.06,.96) if light else hx(h,.50,.09)
    ink='#17212b' if light else '#f2f4ff'
    def readable(color,minimum):
        a=np.array([int(color[i:i+2],16) for i in (1,3,5)])
        b=np.array([int(ink[i:i+2],16) for i in (1,3,5)])
        for t in np.linspace(0,1,21):
            c='#'+''.join(f'{round(v):02x}' for v in a*(1-t)+b*t)
            if contrast(c,bg)>=minimum:return c
        return ink
    x=readable(hx(h,.70,.44 if light else .94),3)
    y=readable(hx(h2,.65,.44 if light else .94),3)
    return {'background':bg,'ink':ink,'muted':readable('#657180' if light else '#a6b1c7',4.5),
            'trace':readable(hx(h,.25,.28 if light else .98),4.5),'x':x,'y':y}


class PreviewBuilder:
    def __init__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='orbite-studio-preview-');self.film=None;self.math_key=None
    def build(self,state,view='Construction'):
        state.validate();demo=not state.source.strip()
        source=ROOT/'examples/etoile.svg' if demo else inputs(state.source,state.recursive)[0]
        if view=='Source' and source.suffix.lower()!='.svg':
            return detection_preview(source,None,None,'Source'),source.name+' · source avant détection'
        if source.suffix.lower()=='.svg':vector=source
        else:
            from trace_image import trace
            key=hashlib.sha256(source.read_bytes()+(state.mode+state.detail+json.dumps(trace_settings(state.config.get('trace')),sort_keys=True)).encode()).hexdigest()
            vector=Path(self.temp.name)/(key+'.svg')
            if not vector.exists() or not vector.with_suffix('.trace.json').is_file():trace(source,vector,mode=state.mode,detail=state.detail,options=state.config.get('trace'))
        c=merge_configs(DEFAULT,state.animation_config())
        c['svg']=str(vector);c['title']=state.config.get('title') or ('Une étoile' if demo else source.stem.replace('_',' ').replace('-',' '))
        if demo:c['path_id']=None
        report=None
        if source.suffix.lower()!='.svg':
            c['contours']='all';c['path_id']=None
            report=json.loads(vector.with_suffix('.trace.json').read_text())
        if view in {'Source','Tracé détecté','Comparaison source / traits'}:
            if source.suffix.lower()=='.svg':
                from svg_diagnostics import svg_preview
                image,caption=svg_preview(source,view,None if view=='Source' else c['path_id'],'all' if view=='Source' else c['contours'])
                return image,caption
            caption=f"{report['mode']} · {report['strokes']} traits · seuil {report['threshold']} · {report['removed_components']} petits éléments filtrés"
            if report['warnings']:caption+='\n'+' '.join(report['warnings'])
            return detection_preview(source,vector,report,view),caption
        key=(hashlib.sha256(Path(c['svg']).read_bytes()).hexdigest(),c['samples'],c['path_id'],c['contours'],c['layout'],tuple(c['steps']))
        if key!=self.math_key:
            self.film=Film(c,360,640);self.math_key=key
        else:self.film.restyle(c)
        film=self.film
        if view=='Image finale':t=film.total-.3
        elif view=='Ouverture':t=min(.7,c['intro']*.7)
        else:t=float(film.ends[-1]-.4)
        caption='Démo · aperçu du style' if demo else source.name
        if report:caption+=f" · {report['mode']} · {report['strokes']} traits"
        caption+=f"\n{film.info['selected_components']}/{film.info['available_components']} tracés · erreur Fourier {film.errors[film.last]:.2f} px"
        if film.errors[film.last]>1.5:caption+=' · essayer Plus de détails Fourier'
        if c['contours']=='largest':caption+='\nContour principal uniquement : les détails intérieurs sont exclus.'
        return film.frame(t),caption
    def close(self):self.temp.cleanup()


class TaskRunner:
    """A cancellable process tree; UI communication goes through a thread-safe queue."""
    def __init__(self,events):
        self.events=events;self.thread=None;self.process=None
        self.cancelled=threading.Event();self.lock=threading.Lock()
    @property
    def running(self):return self.thread is not None and self.thread.is_alive()
    def start(self,argv):
        if self.running:raise RuntimeError('Un traitement est déjà en cours.')
        self.cancelled.clear()
        self.thread=threading.Thread(target=self._work,args=(argv,),daemon=True);self.thread.start()
    def _work(self,argv):
        try:
            if self.cancelled.is_set():self.events.put(('cancelled',None));return
            kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
            with self.lock:
                self.process=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                    text=True,encoding='utf-8',errors='replace',bufsize=1,**kwargs)
            if self.cancelled.is_set():self._terminate()
            current=total=1;parallel=False
            for line in self.process.stdout:
                self.events.put(('log',line.rstrip()))
                if 'Traitement parallèle :' in line:parallel=True
                lot=re.search(r'Lot : (\d+)/(\d+)',line)
                if lot:
                    done,count=map(int,lot.groups());self.events.put(('progress',100*done/max(1,count)))
                batch=re.match(r'\[(\d+)/(\d+)\]',line)
                if batch:current,total=map(int,batch.groups())
                progress=re.search(r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*s',line)
                if progress and not parallel:
                    now,duration=map(float,progress.groups())
                    self.events.put(('progress',100*((current-1)+min(now/max(duration,.01),1))/total))
            self.process.stdout.close()
            code=self.process.wait()
            self.events.put(('cancelled' if self.cancelled.is_set() else 'done' if code==0 else 'failed',code))
        except Exception as exc:self.events.put(('failed',str(exc)))
        finally:
            with self.lock:self.process=None
    def _terminate(self):
        with self.lock:process=self.process
        if process is None or process.poll() is not None:return
        try:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,check=False)
            else:os.killpg(process.pid,signal.SIGTERM)
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name!='nt':os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    def cancel(self):
        self.cancelled.set()
        threading.Thread(target=self._terminate,daemon=True).start()
