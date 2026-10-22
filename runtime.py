"""Find system FFmpeg or the platform binary installed by imageio-ffmpeg."""
import shutil


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
