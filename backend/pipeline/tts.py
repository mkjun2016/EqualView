# narration(텍스트)을 무료 TTS(edge-tts)로 음성 파일로 합성해
# narration_audio/seg_{start}.mp3 에 저장하고 segments.json에 경로를 채운다.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import edge_tts

from config import TTS_VOICE
from utils.ffmpeg_paths import probe_media_info
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


async def _synthesize_one(text: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    await communicate.save(str(output_path))


def _synthesize(text: str, output_path: Path) -> None:
    asyncio.run(_synthesize_one(text, output_path))


def run_tts(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    segments_data = read_json(paths.segments_json)
    segments = segments_data.get("segments", [])

    paths.narration_audio_dir.mkdir(parents=True, exist_ok=True)

    synthesized_count = 0
    failed_count = 0

    for segment in segments:
        text = segment.get("narration", "")

        if not segment.get("narration_safe") or not text:
            continue

        filename = f"seg_{segment['start']:.2f}.mp3"
        output_path = paths.narration_audio_dir / filename

        try:
            _synthesize(text, output_path)
            segment["narration_audio"] = f"narration_audio/{filename}"
            segment["narration_audio_duration"] = round(
                probe_media_info(output_path).duration, 2
            )
            synthesized_count += 1
        except Exception as exc:
            segment["narration_audio"] = None
            segment["narration_audio_error"] = str(exc)
            failed_count += 1

    atomic_write_json(paths.segments_json, segments_data)

    return {
        "synthesized_count": synthesized_count,
        "failed_count": failed_count,
    }
