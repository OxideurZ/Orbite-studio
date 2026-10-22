"""Visual identities, path resolution and validation, independent of Fourier geometry."""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re

from PIL import Image, ImageFont
from safe_area import DEFAULT_SAFE_AREA,validate_safe_area

ROOT=Path(__file__).resolve().parent
DEFAULT_FONTS={key:str(ROOT/'fonts'/name) for key,name in {
    'sans':'DejaVuSans.ttf','bold':'DejaVuSans-Bold.ttf','serif':'DejaVuSerif.ttf'}.items()}
VISUAL_DEFAULTS={
    'brand':'ORBITE','tagline':'LE DESSIN DES FRÉQUENCES',
    'colors':{'background':'#090d20','ink':'#f2efff','muted':'#9aa6c9',
              'trace':'#e4c9ff','x':'#82e4ff','y':'#b6a1ff'},
    'background':str(ROOT/'assets/montagnes_orbite.png'),'background_opacity':.45,
    'background_dimming':{'top':.25,'bottom':.03},'fonts':DEFAULT_FONTS,
    'safe_area':DEFAULT_SAFE_AREA.copy(),
}
VISUAL_FIELDS=set(VISUAL_DEFAULTS)
NESTED_FIELDS={'colors','fonts','background_dimming','captions','safe_area','music','trace'}


def merge_configs(base,override):
    """Partial palettes/font maps keep their unspecified values; never mutate the source."""
    result=deepcopy(base)
    for key,value in override.items():
        if key in NESTED_FIELDS and isinstance(value,dict) and isinstance(result.get(key),dict):
            result[key]={**result[key],**deepcopy(value)}
        else:result[key]=deepcopy(value)
    return result


def resolve_visual_paths(config,base):
    result=deepcopy(config);base=Path(base)
    if 'background' in result and not isinstance(result['background'],str):
        raise ValueError('background doit être un chemin ou "".')
    if result.get('background'):
        result['background']=str((base/Path(result['background'])).resolve())
    if isinstance(result.get('fonts'),dict):
        if any(not isinstance(v,str) for v in result['fonts'].values()):
            raise ValueError('Les valeurs de fonts doivent être des chemins de fichiers.')
        result['fonts']={k:str((base/Path(v)).resolve()) for k,v in result['fonts'].items()}
    return result


def validate_visual(config):
    validate_safe_area(config.get("safe_area",DEFAULT_SAFE_AREA))
    for field in ['brand','tagline']:
        if not isinstance(config.get(field),str):raise ValueError(f'{field} doit être un texte.')
    if not config['brand'].strip():raise ValueError('brand ne peut pas être vide.')
    colors=config.get('colors')
    if not isinstance(colors,dict):raise ValueError('colors doit être un objet JSON.')
    expected=set(VISUAL_DEFAULTS['colors'])
    if set(colors)!=expected:
        raise ValueError('colors : clés attendues '+', '.join(sorted(expected)))
    for name,value in colors.items():
        if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):
            raise ValueError(f'colors.{name} : utiliser #RRGGBB.')
    def unit(value,name):
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) or not 0<=value<=1:
            raise ValueError(f'{name} doit être un nombre entre 0 et 1.')
    unit(config.get('background_opacity'),'background_opacity')
    dimming=config.get('background_dimming')
    if not isinstance(dimming,dict) or set(dimming)!={'top','bottom'}:
        raise ValueError('background_dimming attend top et bottom.')
    for key,value in dimming.items():unit(value,'background_dimming.'+key)
    background=config.get('background')
    if not isinstance(background,str):raise ValueError('background doit être un chemin ou "".')
    if background:
        if not Path(background).is_file():raise ValueError('Fond introuvable : '+background)
        try:
            with Image.open(background) as image:image.verify()
        except Exception as exc:raise ValueError('Fond illisible : '+background) from exc
    fonts=config.get('fonts')
    if not isinstance(fonts,dict) or set(fonts)!=set(DEFAULT_FONTS):
        raise ValueError('fonts attend les clés sans, bold et serif.')
    for key,file in fonts.items():
        if not isinstance(file,str) or not Path(file).is_file():raise ValueError(f'Police {key} introuvable : {file}')
        try:ImageFont.truetype(file,16)
        except Exception as exc:raise ValueError(f'Police {key} illisible : {file}') from exc


def theme_path(name):
    explicit=Path(name).expanduser()
    if explicit.is_file():return explicit.resolve()
    # Built-in lookup accepts a plain name only; explicit missing paths stay errors.
    if explicit.parent==Path('.'):
        builtin=ROOT/'themes'/(explicit.stem+'.json')
        if builtin.is_file():return builtin
    raise ValueError(f'Thème introuvable : {name}. Utiliser --list-themes.')


def load_theme(name='cosmos'):
    file=theme_path(name)
    raw=json.loads(file.read_text(encoding='utf-8'))
    if not isinstance(raw,dict):raise ValueError('Un thème doit être un objet JSON.')
    unknown=set(raw)-VISUAL_FIELDS-{'name','description','version'}
    if unknown:raise ValueError('Paramètres de thème inconnus : '+', '.join(sorted(unknown)))
    if raw.get('version',1)!=1:raise ValueError('Version de thème non prise en charge.')
    for field,expected in [('colors',set(VISUAL_DEFAULTS['colors'])),('fonts',set(DEFAULT_FONTS)),
                            ('background_dimming',{'top','bottom'}),('safe_area',set(DEFAULT_SAFE_AREA))]:
        if field in raw and (not isinstance(raw[field],dict) or not set(raw[field])<=expected):
            raise ValueError(f'Clés invalides dans {field}.')
    partial=resolve_visual_paths({k:v for k,v in raw.items() if k in VISUAL_FIELDS},file.parent)
    result=merge_configs(VISUAL_DEFAULTS,partial)
    result['theme_name']=str(raw.get('name',file.stem))
    validate_visual(result)
    return result


def list_themes():
    return [{'id':p.stem,'name':json.loads(p.read_text(encoding='utf-8')).get('name',p.stem),
             'description':json.loads(p.read_text(encoding='utf-8')).get('description','')}
            for p in sorted((ROOT/'themes').glob('*.json'))]


def relative_visual_paths(config,base):
    result=deepcopy(config)
    if result.get('background'):result['background']=os.path.relpath(result['background'],base)
    result['fonts']={k:os.path.relpath(v,base) for k,v in result['fonts'].items()}
    return result


def export_theme(destination,source='cosmos'):
    file=Path(destination).resolve()
    if file.exists():raise ValueError('Ce fichier existe déjà : '+str(file))
    theme=load_theme(source)
    result={k:v for k,v in theme.items() if k in VISUAL_FIELDS}
    result=relative_visual_paths(result,file.parent)
    result={'version':1,'name':file.stem,**result}
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return file


def config_fingerprint(config,salt=''):
    """Independent variants also notice replacement image/font files at the same path."""
    digest=hashlib.sha256(json.dumps(config,ensure_ascii=False,sort_keys=True).encode()+salt.encode())
    assets=list(config.get('fonts',{}).values())
    if config.get('background'):assets.append(config['background'])
    for file in sorted(set(assets)):
        digest.update(Path(file).read_bytes())
    return digest.hexdigest()


def validate_input(source,path_id=None):
    """Read-only preflight. No tracing, frames, audio or FFmpeg subprocesses."""
    source=Path(source)
    if source.suffix.lower()=='.svg':
        from svgpathtools import Document
        paths=Document(str(source)).paths(path_filter=lambda e:path_id is None or e.get('id')==path_id)
        if not any(len(p) for p in paths):raise ValueError('Aucun chemin SVG utilisable : '+str(source))
        return {'input':str(source),'format':'SVG','paths':len(paths),'status':'ok'}
    with Image.open(source) as image:
        result={'input':str(source),'format':image.format,'size':list(image.size),'status':'ok'}
        image.verify()
    return result
