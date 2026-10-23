"""Find system FFmpeg or the platform binary installed by imageio-ffmpeg."""
from functools import lru_cache
import subprocess
import shutil
import sys


def ffmpeg_executable():
    system=shutil.which('ffmpeg')
    if system:return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError):return None


def require_ffmpeg():
    file=ffmpeg_executable()
    if not file:raise RuntimeError('FFmpeg manque. Installer les dépendances : python -m pip install -r requirements.txt')
    return file


@lru_cache(maxsize=4)
def _supports_encoder(ffmpeg,name):
    try:
        result=subprocess.run([ffmpeg,'-hide_banner','-encoders'],capture_output=True,text=True,timeout=8)
        return result.returncode==0 and name in result.stdout
    except (OSError,subprocess.SubprocessError):
        return False


def video_encoder(ffmpeg=None):
    """Use Apple's hardware H.264 encoder on macOS when FFmpeg exposes it."""
    ffmpeg=ffmpeg or ffmpeg_executable()
    if sys.platform=='darwin' and ffmpeg and _supports_encoder(ffmpeg,'h264_videotoolbox'):
        return 'h264_videotoolbox'
    return 'libx264'


def video_encoder_args(encoder,threads,width,height):
    if encoder=='h264_videotoolbox':
        # VideoToolbox owns encoding on Apple's media engine; keep a generous
        # bitrate for delicate line art without the x264-only preset/CRF flags.
        bitrate='5M' if width<=540 else '12M' if width<=1080 else '24M'
        return ['-c:v',encoder,'-b:v',bitrate]
    return ['-c:v','libx264','-threads',str(threads),'-preset','fast','-crf','18']
