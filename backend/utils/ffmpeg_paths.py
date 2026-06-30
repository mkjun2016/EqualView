import os
import re
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Any


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
        encoding="utf-8",
        errors="replace",
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


_VIDEO_SIZE_RE = re.compile(r"Video:.*?, (\d+)x(\d+)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr")


def parse_video_metadata(stderr: str, duration: float | None = None) -> dict[str, Any]:
    width = None
    height = None
    fps = None

    size_match = _VIDEO_SIZE_RE.search(stderr)
    if size_match:
        width = int(size_match.group(1))
        height = int(size_match.group(2))

    fps_match = _FPS_RE.search(stderr)
    if fps_match:
        fps = round(float(fps_match.group(1)), 3)
    else:
        tbr_match = _TBR_RE.search(stderr)
        if tbr_match:
            fps = round(float(tbr_match.group(1)), 3)

    result: dict[str, Any] = {
        "fps": fps,
        "width": width,
        "height": height,
    }
    if duration is not None:
        result["duration"] = round(duration, 2)
    return result


def get_video_metadata(file_path: Path) -> dict[str, Any]:
    stderr = probe_media(file_path)
    duration = parse_duration(stderr)
    metadata = parse_video_metadata(stderr, duration=duration)
    return metadata
