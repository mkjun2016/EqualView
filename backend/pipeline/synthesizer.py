# 원본 영상 + 원본(또는 무음) 오디오 + 구간별 화면해설 음성을
# ffmpeg로 합성해 uploads/{job_id}/output.mp4를 만든다.
# 화면해설 음성이 침묵 구간보다 길면 atempo로 살짝 빨리 읽게 만들어 구간 안에 맞춘다.

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.audio_extractor import get_media_duration
from utils.ffmpeg_paths import get_ffmpeg_binary, subprocess_run
from utils.json_io import read_json
from utils.paths import JobPaths

MIN_ATEMPO = 1.0
MAX_ATEMPO = 1.6


def _narrated_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in segments
        if segment.get("narration_safe") and segment.get("narration_audio")
    ]


def run_synthesis(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    video_path = paths.find_input_video()
    segments_data = read_json(paths.segments_json)
    segments = _narrated_segments(segments_data.get("segments", []))

    if not segments:
        _mux_passthrough(video_path, paths.audio_wav, paths.output_video)
        return {"narrated_segment_count": 0}

    inputs = [video_path, paths.audio_wav]
    filter_parts = []
    mix_labels = ["1:a"]

    for index, segment in enumerate(segments):
        narration_path = paths.job_dir / segment["narration_audio"]
        inputs.append(narration_path)
        input_index = index + 2

        available = max(0.1, segment["end"] - segment["start"])
        tts_duration = segment.get("narration_audio_duration") or get_media_duration(
            narration_path
        )
        tempo = min(MAX_ATEMPO, max(MIN_ATEMPO, tts_duration / available))
        delay_ms = round(segment["start"] * 1000)

        label = f"a{index}"
        filter_parts.append(
            f"[{input_index}:a]atempo={tempo:.3f},adelay={delay_ms}:all=1[{label}]"
        )
        mix_labels.append(label)

    mix_inputs = "".join(f"[{label}]" for label in mix_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(mix_labels)}:duration=first:"
        "dropout_transition=0:normalize=0[aout]"
    )
    filter_complex = ";".join(filter_parts)

    command = [get_ffmpeg_binary(), "-y"]
    for input_path in inputs:
        command += ["-i", str(input_path)]

    command += [
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(paths.output_video),
    ]

    result = subprocess_run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return {"narrated_segment_count": len(segments)}


def _mux_passthrough(video_path: Path, audio_path: Path, output_path: Path) -> None:
    command = [
        get_ffmpeg_binary(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]

    result = subprocess_run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
