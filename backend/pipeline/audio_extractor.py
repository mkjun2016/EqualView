from pathlib import Path

from utils.ffmpeg_paths import (
    get_ffmpeg_binary,
    probe_media_info,
    subprocess_run,
)


def extract_audio_from_video(video_path: Path, audio_path: Path):
    command = [
        get_ffmpeg_binary(),
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(audio_path),
    ]

    result = subprocess_run(command)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def get_media_duration(file_path: Path):
    return probe_media_info(file_path).duration


def has_audio_stream(video_path: Path):
    return probe_media_info(video_path).has_audio


def create_silent_wav(audio_path: Path, duration: float):
    command = [
        get_ffmpeg_binary(),
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=mono:sample_rate=16000",
        "-t",
        str(duration),
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]

    result = subprocess_run(command)

    if result.returncode != 0:
        raise RuntimeError(result.stderr)
