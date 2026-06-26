import os
import re
import shutil
from functools import lru_cache


class FFmpegNotFoundError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_ffmpeg_binary() -> str:
    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and os.path.isfile(bundled):
            return bundled
    except ImportError:
        pass

    raise FFmpegNotFoundError(
        "ffmpeg not found. Install system ffmpeg (e.g. brew install ffmpeg) "
        "or pip install imageio-ffmpeg."
    )


def probe_media(file_path) -> str:
    command = [
        get_ffmpeg_binary(),
        "-hide_banner",
        "-i",
        str(file_path),
        "-f",
        "null",
        "-",
    ]

    result = subprocess_run(command)
    return result.stderr


def subprocess_run(command):
    import subprocess

    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


_DURATION_RE = re.compile(
    r"Duration:\s*(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d+(?:\.\d+)?)"
)


def parse_duration(stderr: str) -> float:
    match = _DURATION_RE.search(stderr)
    if not match:
        raise RuntimeError("Could not determine media duration from ffmpeg output.")

    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    seconds = float(match.group("seconds"))
    return hours * 3600 + minutes * 60 + seconds


def has_audio_in_probe(stderr: str) -> bool:
    return bool(re.search(r"^\s*Stream .* Audio:", stderr, re.MULTILINE))
