#!/usr/bin/env python3
"""ORBITE installer/update manager. Python standard library only; no Git required.

Download this file, then run: python install_orbite.py
Versions are installed in separate environments; current.json switches last.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError,URLError
from urllib.parse import quote,urlparse
from urllib.request import Request,urlopen
import venv
import zipfile

REPOSITORY='OxideurZ/Orbite-studio'
BRANCH='main'
APP_ID='orbite-studio'
MAX_ARCHIVE=128*1024*1024
MAX_EXPANDED=512*1024*1024
IGNORED={'.git','.venv','venv','output','__pycache__','.pytest_cache','releases','data'}


def install_root():
    if os.environ.get('ORBITE_HOME'):return Path(os.environ['ORBITE_HOME']).expanduser().resolve()
    if sys.platform=='win32':base=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))
    elif sys.platform=='darwin':base=Path.home()/'Library/Application Support'
    else:base=Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))
    return base/'ORBITEStudio'


def data_root():
    return Path(os.environ.get('ORBITE_DATA_DIR',str(install_root()/'data'))).expanduser().resolve()


def read_json(file,default=None):
    try:return json.loads(Path(file).read_text(encoding='utf-8'))
    except FileNotFoundError:return default


def atomic_json(file,value):
    file=Path(file);file.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+file.name,dir=file.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')
        os.replace(name,file)
    finally:
        if Path(name).exists():Path(name).unlink()


def valid_repository(repository):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Dépôt GitHub invalide.')
    return repository


def manifest(value,repository=None):
    if not isinstance(value,dict) or value.get('app_id')!=APP_ID or value.get('schema')!=1:
        raise ValueError('Ce dépôt ne contient pas une version compatible d’ORBITE Studio.')
    if not re.fullmatch(r'\d+\.\d+\.\d+',str(value.get('version',''))):raise ValueError('Version ORBITE invalide.')
    valid_repository(value.get('repository',''))
    if repository and value['repository'].lower()!=repository.lower():raise ValueError('Le dépôt ne correspond pas à la version téléchargée.')
    minimum=value.get('python_min')
    if not isinstance(minimum,list) or len(minimum)!=2 or any(type(x) is not int for x in minimum):raise ValueError('Version minimale de Python invalide.')
    if tuple(sys.version_info[:2])<tuple(minimum):raise ValueError('Installer Python '+'.'.join(map(str,minimum))+' ou plus récent.')
    return value


def _request(url,limit):
    if urlparse(url).scheme!='https':raise ValueError('Le téléchargement doit utiliser HTTPS.')
    request=Request(url,headers={'User-Agent':'ORBITE-Studio/0.8','Accept':'application/vnd.github+json'})
    try:
        with urlopen(request,timeout=25) as response:
            if urlparse(response.url).scheme!='https':raise ValueError('Redirection non sécurisée refusée.')
            value=response.read(limit+1)
            if len(value)>limit:raise ValueError('Téléchargement trop volumineux.')
            return value
    except HTTPError as exc:
        if exc.code==404:raise RuntimeError('Dépôt/version introuvable. Le dépôt doit être public et contenir le programme.') from exc
        if exc.code in (403,429):raise RuntimeError('GitHub limite les vérifications. Réessayer plus tard.') from exc
        raise RuntimeError(f'GitHub répond HTTP {exc.code}.') from exc
    except (URLError,TimeoutError) as exc:raise RuntimeError('GitHub est inaccessible. Vérifier la connexion ; l’application reste utilisable hors ligne.') from exc


def remote_release(repository=REPOSITORY,branch=BRANCH):
    valid_repository(repository)
    commit=json.loads(_request(f'https://api.github.com/repos/{repository}/commits/{quote(branch,safe="")}',2*1024*1024))
    sha=commit.get('sha','')
    if not re.fullmatch(r'[0-9a-f]{40}',sha):raise ValueError('Révision GitHub invalide.')
    meta=manifest(json.loads(_request(f'https://raw.githubusercontent.com/{repository}/{sha}/app_version.json',65536)),repository)
    return {'commit':sha,'version':meta['version'],'repository':repository,'branch':branch,'manifest':meta}


def check_update(root=None,repository=REPOSITORY,branch=BRANCH):
    root=Path(root or install_root());latest=remote_release(repository,branch)
    current=read_json(root/'current.json',{})
    latest['available']=latest['commit']!=current.get('commit')
    return latest


def extract_archive(blob,destination):
    """Only normal files under one GitHub root; reject traversal, links and bombs."""
    import io
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries=archive.infolist()
        if len(entries)>5000 or sum(e.file_size for e in entries)>MAX_EXPANDED:raise ValueError('Archive trop volumineuse.')
        roots=set();seen=set()
        for entry in entries:
            path=PurePosixPath(entry.filename)
            if '\\' in entry.filename or path.is_absolute() or '..' in path.parts or not path.parts or ':' in entry.filename:
                raise ValueError('Chemin invalide dans l’archive.')
            roots.add(path.parts[0])
            if stat.S_ISLNK(entry.external_attr>>16):raise ValueError('Les liens symboliques ne sont pas acceptés.')
            if entry.is_dir():continue
            relative=Path(*path.parts[1:])
            if not relative.parts:raise ValueError('Structure d’archive invalide.')
            if str(relative).casefold() in seen:raise ValueError('Fichier dupliqué dans l’archive.')
            seen.add(str(relative).casefold())
        if len(roots)!=1:raise ValueError('L’archive doit contenir un seul dossier racine.')
        destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
        for entry in entries:
            if entry.is_dir():continue
            relative=Path(*PurePosixPath(entry.filename).parts[1:])
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True)
            with archive.open(entry) as source,target.open('wb') as out:shutil.copyfileobj(source,out)


@contextmanager
def installation_lock(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    with (root/'install.lock').open('a+b') as file:
        if file.tell()==0:file.write(b'0');file.flush()
        file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as exc:raise RuntimeError('Une installation est déjà en cours.') from exc
        try:yield
        finally:
            file.seek(0)
            if os.name=='nt':msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(file.fileno(),fcntl.LOCK_UN)


def environment_python(release):
    return Path(release)/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def prepare_environment(app,release):
    print('Création d’un environnement Python isolé…',flush=True)
    venv.EnvBuilder(with_pip=True).create(Path(release)/'venv')
    python=environment_python(release)
    try:subprocess.run([str(python),'-c','import tkinter'],check=True)
    except subprocess.CalledProcessError as exc:raise RuntimeError('Tkinter manque dans Python. Sous Linux : installer python3-tk ; sous Windows/macOS : utiliser Python avec Tcl/Tk.') from exc
    print('Installation des dépendances et de FFmpeg (première installation plus longue)…',flush=True)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(Path(app)/'requirements.txt')],check=True)
    smoke="import tkinter,numpy,scipy,svgpathtools;from PIL import Image;from studio_model import StudioState;from runtime import ffmpeg_executable;StudioState.initial().validate();assert ffmpeg_executable();print('Contrôle ORBITE réussi.')"
    subprocess.run([str(python),'-c',smoke],cwd=app,check=True)


def _revision(value):
    if not re.fullmatch(r'(?:[0-9a-f]{40}|local-[0-9a-f]{16})',str(value)):raise ValueError('Révision d’installation invalide.')
    return value


def installed_release(root,info):
    if not isinstance(info,dict):raise ValueError('Installation introuvable. Relancer l’installateur.')
    release=Path(root)/'releases'/_revision(info.get('commit'))
    if not (release/'ready.json').is_file() or not environment_python(release).is_file():raise ValueError('Installation incomplète. Relancer l’installateur.')
    return release


def launch(root=None,project=None):
    root=Path(root or install_root()).resolve();info=read_json(root/'current.json');release=installed_release(root,info)
    env=os.environ.copy();env['ORBITE_HOME']=str(root);env['ORBITE_DATA_DIR']=str(root/'data')
    python=environment_python(release)
    if os.name=='nt' and python.with_name('pythonw.exe').exists():python=python.with_name('pythonw.exe')
    argv=[str(python),str(release/'app/studio.py')]
    if project:argv+=['--project',str(Path(project).resolve())]
    with (root/'launch.log').open('ab') as log:
        kwargs={'start_new_session':True} if os.name!='nt' else {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP}
        return subprocess.Popen(argv,cwd=release/'app',env=env,stdout=log,stderr=subprocess.STDOUT,**kwargs)


def create_launchers(root,app):
    root=Path(root);manager=root/'manager.py'
    temporary=root/'manager.py.tmp';shutil.copyfile(Path(app)/'install.py',temporary);os.replace(temporary,manager)
    base=str(getattr(sys,'_base_executable',sys.executable))
    if os.name=='nt':
        (root/'ORBITE.cmd').write_text('@echo off\r\n"'+base+'" "%~dp0manager.py" --root "%~dp0." --launch %*\r\nif errorlevel 1 pause\r\n',encoding='utf-8')
    else:
        file=root/('ORBITE.command' if sys.platform=='darwin' else 'ORBITE.sh')
        file.write_text('#!/bin/sh\nexec '+shlex.quote(base)+' '+shlex.quote(str(manager))+' --root '+shlex.quote(str(root))+' --launch "$@"\n',encoding='utf-8');file.chmod(0o755)


def _copy_source(source,app):
    def ignore(directory,names):return [name for name in names if name in IGNORED or name.endswith('.pyc')]
    shutil.copytree(source,app,ignore=ignore,symlinks=False)


def install_release(root=None,release=None,source=None,repository=REPOSITORY,branch=BRANCH,prepare=prepare_environment):
    root=Path(root or install_root()).resolve()
    if source:
        source=Path(source).resolve()
        if root==source or source in root.parents:raise ValueError('Le dossier d’installation doit être séparé du code source.')
        meta=manifest(read_json(source/'app_version.json'),repository)
        digest=hashlib.sha256()
        for file in sorted(source.rglob('*')):
            if file.is_file() and not any(p in IGNORED for p in file.relative_to(source).parts) and file.suffix!='.pyc':
                digest.update(str(file.relative_to(source)).encode());digest.update(file.read_bytes())
        release={'commit':'local-'+digest.hexdigest()[:16],'version':meta['version'],'repository':repository,'branch':branch,'manifest':meta}
    release=release or remote_release(repository,branch);commit=_revision(release['commit'])
    with installation_lock(root):
        previous=read_json(root/'current.json')
        if previous and previous.get('commit')==commit:
            installed_release(root,previous);print('ORBITE est déjà à jour.',flush=True);return previous
        target=root/'releases'/commit;app=target/'app'
        if not (target/'ready.json').exists():
            if target.exists():shutil.rmtree(target)  # incomplete immutable version only
            target.mkdir(parents=True)
            try:
                if source:_copy_source(source,app)
                else:
                    print('Téléchargement de la version '+release['version']+' ('+commit[:8]+')…',flush=True)
                    blob=_request(f'https://codeload.github.com/{valid_repository(repository)}/zip/{commit}',MAX_ARCHIVE)
                    extract_archive(blob,app)
                meta=manifest(read_json(app/'app_version.json'),repository)
                if meta['version']!=release['version']:raise ValueError('La version téléchargée ne correspond pas à la vérification.')
                for required in ['studio.py','studio_model.py','install.py','requirements.txt','runtime.py']:
                    if not (app/required).is_file():raise ValueError('Installation incomplète : '+required)
                prepare(app,target)
                atomic_json(target/'ready.json',{'commit':commit,'version':meta['version']})
            except BaseException:
                shutil.rmtree(target,ignore_errors=True);raise
        info={'commit':commit,'version':release['version'],'repository':repository,'branch':branch}
        create_launchers(root,app)
        if previous:atomic_json(root/'previous.json',previous)
        atomic_json(root/'current.json',info)  # last: leave the old version active on any earlier failure
        print('ORBITE '+info['version']+' est prêt. Projets et exports conservés dans '+str(root/'data'),flush=True)
        print('Lanceur : '+str(root/('ORBITE.cmd' if os.name=='nt' else 'ORBITE.command' if sys.platform=='darwin' else 'ORBITE.sh')),flush=True)
        return info


def rollback(root=None):
    root=Path(root or install_root()).resolve()
    with installation_lock(root):
        previous=read_json(root/'previous.json');installed_release(root,previous)
        current=read_json(root/'current.json');atomic_json(root/'current.json',previous)
        if current:atomic_json(root/'previous.json',current)
    return previous


def main(argv=None):
    p=argparse.ArgumentParser(description='Installer, lancer ou mettre à jour ORBITE Studio, sans Git.')
    action=p.add_mutually_exclusive_group();action.add_argument('--launch',action='store_true');action.add_argument('--check',action='store_true');action.add_argument('--rollback',action='store_true');action.add_argument('--update',action='store_true')
    p.add_argument('--no-launch',action='store_true');p.add_argument('--root',type=Path);p.add_argument('--project',type=Path)
    p.add_argument('--repo',default=REPOSITORY);p.add_argument('--branch',default=BRANCH);p.add_argument('--from-source',type=Path)
    args=p.parse_args(argv);root=(args.root or install_root()).resolve()
    try:
        if args.launch:launch(root,args.project);return 0
        if args.check:print(json.dumps(check_update(root,args.repo,args.branch),ensure_ascii=False,indent=2));return 0
        if args.rollback:rollback(root)
        else:install_release(root,source=args.from_source,repository=args.repo,branch=args.branch)
        if not args.no_launch:launch(root,args.project)
        return 0
    except Exception as exc:
        print('ORBITE : '+str(exc),file=sys.stderr)
        print('La version précédente et les données personnelles sont conservées.',file=sys.stderr)
        return 1

if __name__=='__main__':raise SystemExit(main())
