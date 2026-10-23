"""Completed-output receipts. Partial or modified products never count as a hit."""
import hashlib
import json
from pathlib import Path
import os
import tempfile


def products(prefix,action,preset,export_social=False,video_prefix=None):
    prefix=str(prefix)
    if action=='stills':return [Path(prefix+'_'+name+'.png') for name in ['cover','drawing','hook']]
    if action=='audio':return [Path(prefix+'_soundtrack.'+ext) for ext in ['wav','mp3']]
    width,height={'preview':(540,960),'social':(1080,1920),'master':(1440,2560)}[preset]
    video_prefix=str(video_prefix or prefix)
    files=[Path(video_prefix+f'_{width}x{height}.mp4')]
    if export_social and preset=='master':files.append(Path(video_prefix+'_1080x1920.mp4'))
    return files


def receipt_path(folder,request):
    key=hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()[:16]
    return Path(folder)/('.completed-'+key+'.json')


def completed(receipt,files):
    try:
        data=json.loads(Path(receipt).read_text(encoding='utf-8'))
        return data['files']==[{ 'name':p.name,'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in files] and all(p.stat().st_size>0 for p in files)
    except (OSError,ValueError,KeyError,TypeError):return False


def record(receipt,files):
    if not all(p.is_file() and p.stat().st_size>0 for p in files):return
    payload={'files':[{'name':p.name,'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for p in files]}
    receipt=Path(receipt);fd,temp=tempfile.mkstemp(prefix='.receipt-',dir=receipt.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as file:json.dump(payload,file)
        os.replace(temp,receipt)
    finally:
        if Path(temp).exists():Path(temp).unlink()
