#!/usr/bin/env python3
"""Une image ou un dossier → une vidéo ORBITE.

python orbite.py image.jpg
python orbite.py mes_images/ --stills
python orbite.py image.jpg --preview
python orbite.py image.jpg --quality master
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
from runtime import ffmpeg_executable
import subprocess
import sys
import time
import unicodedata
import multiprocessing
from concurrent.futures import ProcessPoolExecutor,as_completed
from render_cache import products,receipt_path,completed,record

from trace_image import trace,trace_settings
from themes import (load_theme,list_themes,export_theme,merge_configs,resolve_visual_paths,
                    relative_visual_paths,validate_visual,validate_input,config_fingerprint)

ROOT=Path(__file__).resolve().parent
EXTENSIONS={'.svg','.jpg','.jpeg','.png','.webp','.bmp','.tif','.tiff'}


def slug(text):
    ascii_text=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode()
    return re.sub(r'[^a-z0-9]+','-',ascii_text.lower()).strip('-') or 'image'


def inputs(path,recursive=False):
    path=Path(path)
    if path.is_file():
        if path.suffix.lower() not in EXTENSIONS:raise ValueError('Format non pris en charge : '+path.suffix)
        return [path.resolve()]
    if not path.is_dir():raise FileNotFoundError(path)
    return sorted(p.resolve() for p in (path.rglob('*') if recursive else path.iterdir())
                  if p.is_file() and p.suffix.lower() in EXTENSIONS)


def build_style(config=None,theme=None,brand=None,background=None,opacity=None):
    style=merge_configs(load_theme('cosmos'),json.loads((ROOT/'presets/orbite.json').read_text(encoding='utf-8')))
    if config:
        file=Path(config).resolve()
        custom=resolve_visual_paths(json.loads(file.read_text(encoding='utf-8')),file.parent)
        style=merge_configs(style,custom)
    if theme:style=merge_configs(style,load_theme(theme))
    if brand is not None:style['brand']=brand
    if background is not None:style['background']=str(Path(background).resolve()) if background else ''
    if opacity is not None:style['background_opacity']=opacity
    from music import settings as music_settings
    style['music']=music_settings(style.get('music'))
    validate_visual(style)
    from render_social import DEFAULT,validate_animation
    validate_animation(merge_configs(DEFAULT,style))
    return style


def choose_jobs(requested,count):
    return max(1,min(count,requested or (2 if (os.cpu_count() or 1)>=4 else 1)))


def _process_source(payload):
    i,total,source,args,style,out,tool_hash,engine_hash,threads=payload
    started=time.monotonic()
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    source_id=hashlib.sha256(str(source.resolve()).encode()).hexdigest()[:6]
    source_root=out/(slug(source.stem)+'-'+digest[:8]+'-'+source_id)
    title=args.title or (style.get('title') if args.config else None) or source.stem.replace('_',' ').replace('-',' ')
    print(f'\n[{i}/{total}] {source.name}',flush=True)
    result={'input':str(source),'title':title,'theme':style.get('theme_name')}
    try:
        episode=style.get('episode')
        if episode is None:episode=f'{i:03d}'
        elif str(episode).isdigit():episode=f'{int(episode)+i-1:0{max(3,len(str(episode)))}d}'
        c={**style,'title':title,'episode':str(episode),
           'path_id':args.path_id if args.path_id is not None else style.get('path_id'),
           'contours':style.get('contours','all')}
        if source.suffix.lower()!='.svg':c['contours']='all';c['path_id']=None
        if args.no_audio:c['audio']=False
        key=hashlib.sha256((digest+args.mode+args.detail+json.dumps(trace_settings(c.get('trace')),sort_keys=True)+tool_hash).encode()).hexdigest()
        variant=config_fingerprint(c,salt=engine_hash+key)
        job=source_root/'variants'/(slug(style.get('theme_name','personnalise'))+'-'+variant[:10])
        job.mkdir(parents=True,exist_ok=True)
        prefix=job/'orbite';result['folder']=str(job)
        preset='preview' if args.preview or args.stills or args.audio_only else args.quality
        action='stills' if args.stills else 'audio' if args.audio_only else 'video'
        outputs=products(prefix,action,preset,args.quality=='master' and not(args.preview or args.stills or args.audio_only))
        receipt=receipt_path(job,{'action':action,'preset':preset,'fps':args.fps})
        if not args.force and completed(receipt,outputs):
            result.update(status='ok',cached=True,seconds=round(time.monotonic()-started,2),preset=preset)
            print('  Sorties inchangées déjà prêtes → '+str(job),flush=True)
            return result
        if source.suffix.lower()=='.svg':
            vector=source_root/'source.svg'
            if not vector.exists():shutil.copyfile(source,vector)
            result['mode']='svg'
        else:
            cache=source_root/'traces'/key[:12];cache.mkdir(parents=True,exist_ok=True)
            vector=cache/'strokes.svg';stamp=cache/'trace_cache.json'
            cached_info=None
            if not args.force and vector.is_file() and stamp.is_file():
                try:
                    if json.loads(stamp.read_text()).get('key')==key:
                        cached_info=json.loads(vector.with_suffix('.trace.json').read_text())
                        if not isinstance(cached_info,dict) or 'mode' not in cached_info:cached_info=None
                except (OSError,ValueError,TypeError):pass
            if cached_info is not None:
                print('  Tracé en cache.',flush=True)
                result['trace_cached']=True;result['mode']=cached_info['mode'];result['detection']=cached_info
            else:
                info=trace(source,vector,mode=args.mode,detail=args.detail,options=c.get('trace'))
                stamp.write_text(json.dumps({'key':key}),encoding='utf-8')
                result['mode']=info['mode'];result['trace_cached']=False;result['detection']=info
                print(f"  {info['strokes']} traits · {info['mode']}",flush=True)
                for warning in info.get('warnings',[]):print('  Détection : '+warning,flush=True)
        c['svg']=os.path.relpath(vector,job)
        c=relative_visual_paths(c,job)
        config=job/'episode.json'
        config.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding='utf-8')
        preset='preview' if args.preview or args.stills or args.audio_only else args.quality
        cmd=[sys.executable,str(ROOT/'render_social.py'),'--config',str(config),
             '--preset',preset,'--output',str(prefix)]
        cmd+=['--threads',str(threads)]
        if args.stills:cmd.append('--preview')
        if args.audio_only:cmd.append('--audio-only')
        if args.fps is not None:cmd+=['--fps',str(args.fps)]
        if args.no_audio:cmd.append('--silent')
        if args.quality=='master' and not (args.preview or args.stills or args.audio_only):cmd.append('--export-social')
        subprocess.run(cmd,check=True)
        record(receipt,outputs)
        result.update(status='ok',seconds=round(time.monotonic()-started,2),preset=preset)
        print(f"  Terminé → {job}",flush=True)
    except Exception as exc:
        result.update(status='failed',error=str(exc),seconds=round(time.monotonic()-started,2))
        print(f'  Échec : {exc}',file=sys.stderr,flush=True)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input',nargs='?',help='Image, SVG ou dossier')
    ap.add_argument('--title',help='Nom affiché seulement au début et à la fin')
    ap.add_argument('--quality',choices=['social','master'],default='social')
    ap.add_argument('--fps',type=int,help='Cadence personnalisée entre 1 et 120 images/s')
    ap.add_argument('--preview',action='store_true',help='Vidéo légère 540×960, avec le même rythme')
    ap.add_argument('--audio-only',action='store_true',help='Générer seulement la musique (WAV et MP3)')
    ap.add_argument('--stills',action='store_true',help='Trois images fixes, sans encoder de vidéo')
    ap.add_argument('--mode',choices=['auto','lineart','outline','edges'],default='auto')
    ap.add_argument('--detail',choices=['low','medium','high'],default='medium')
    ap.add_argument('--config',help='Personnaliser le style à partir d’un JSON')
    ap.add_argument('--theme',help='cosmos, aurore, papier ou fichier JSON personnalisé')
    ap.add_argument('--list-themes',action='store_true',help='Lister les identités disponibles')
    ap.add_argument('--init-theme',metavar='FICHIER.json',help='Créer un thème à personnaliser')
    ap.add_argument('--brand',help='Remplacer la signature du thème')
    ap.add_argument('--background',help='Image de fond ; "" pour un fond uni')
    ap.add_argument('--background-opacity',type=float,help='Présence du fond, entre 0 et 1')
    ap.add_argument('--check',action='store_true',help='Vérifier paramètres et sources sans aucun rendu')
    ap.add_argument('--path-id',help='Élément précis d’un SVG')
    ap.add_argument('--no-audio',action='store_true')
    ap.add_argument('--recursive',action='store_true',help='Parcourir aussi les sous-dossiers')
    ap.add_argument('--jobs',type=int,default=0,help='Images en parallèle : 0 auto (max 2), 1 à 4')
    ap.add_argument('--force',action='store_true',help='Recalculer même si les sorties complètes existent')
    ap.add_argument('--output',default=str(ROOT/'output'/'series'))
    args=ap.parse_args()
    if args.audio_only and (args.stills or args.preview or args.no_audio):ap.error("Audio seul : incompatible avec --stills, --preview et --no-audio.")
    if not 0<=args.jobs<=4:ap.error('Choisir entre 0 et 4 traitements en parallèle.')
    if args.fps is not None and not 1<=args.fps<=120:ap.error('La cadence doit être comprise entre 1 et 120 images/s.')
    if args.list_themes:
        print(json.dumps(list_themes(),ensure_ascii=False,indent=2));return 0
    if args.init_theme:
        try:print(export_theme(args.init_theme,args.theme or 'cosmos'))
        except (ValueError,OSError) as exc:ap.error(str(exc))
        return 0
    if not args.input:ap.error('Indiquer une image ou un dossier.')
    sources=inputs(args.input,args.recursive)
    if not sources:ap.error('Aucune image trouvée dans ce dossier.')
    try:style=build_style(args.config,args.theme,args.brand,args.background,args.background_opacity)
    except (ValueError,OSError,TypeError) as exc:ap.error(str(exc))
    if args.audio_only and not style.get('audio',True):ap.error('Activer audio dans la configuration pour générer la musique.')
    if args.check:
        checked=[]
        for source in sources:
            try:checked.append(validate_input(source,args.path_id if args.path_id is not None else style.get('path_id')))
            except Exception as exc:checked.append({'input':str(source),'status':'failed','error':str(exc)})
        ffmpeg=bool(ffmpeg_executable())
        ok=all(r['status']=='ok' for r in checked) and ffmpeg
        print(json.dumps({'status':'ok' if ok else 'failed','no_render':True,
            'theme':style.get('theme_name'),'brand':style['brand'],'colors':style['colors'],
            'background':style['background'],'background_opacity':style['background_opacity'],
            'background_dimming':style['background_dimming'],'fonts':style['fonts'],
            'safe_area':style['safe_area'],'music':style.get('music'),
            'trace':trace_settings(style.get('trace')),'trace_mode':args.mode,'detail':args.detail,
            'duration_s':sum(style['durations'])+style['intro']+style['outro'],
            'ffmpeg_available':ffmpeg,'inputs':checked},ensure_ascii=False,indent=2))
        return 0 if ok else 1
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    tool_hash=hashlib.sha256((ROOT/'trace_image.py').read_bytes()).hexdigest()
    engine_hash=hashlib.sha256(b''.join((ROOT/name).read_bytes() for name in ['render_social.py','composition.py','safe_area.py','music.py','runtime.py','render_cache.py'])).hexdigest()
    workers=choose_jobs(args.jobs,len(sources));threads=max(1,min(4,(os.cpu_count() or 2)//workers))
    payloads=[(i,len(sources),source,args,style,out,tool_hash,engine_hash,threads) for i,source in enumerate(sources,1)]
    results=[None]*len(sources)
    def collect(index,result):
        results[index]=result
        (out/'batch_report.json').write_text(json.dumps([r for r in results if r is not None],ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'Lot : {sum(r is not None for r in results)}/{len(sources)}',flush=True)
    if workers==1:
        for index,payload in enumerate(payloads):collect(index,_process_source(payload))
    else:
        print(f'Traitement parallèle : {workers} images · {threads} threads encodeur/image',flush=True)
        with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('spawn')) as pool:
            futures={pool.submit(_process_source,payload):index for index,payload in enumerate(payloads)}
            for future in as_completed(futures):
                index=futures[future]
                try:result=future.result()
                except Exception as exc:result={'input':str(sources[index]),'status':'failed','error':str(exc)}
                collect(index,result)
    failures=sum(r['status']!='ok' for r in results)
    print(f'\n{len(results)-failures}/{len(results)} terminé(s). Rapport : {out/"batch_report.json"}',flush=True)
    return 1 if failures else 0


if __name__=='__main__':sys.exit(main())
