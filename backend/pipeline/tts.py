# narration(텍스트)을 무료 TTS(edge-tts)로 음성 파일로 합성해
# narration_audio/seg_{start}.mp3 에 저장하고 segments.json에 경로를 채운다.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import edge_tts

from config import TTS_VOICE
from pipeline.audio_extractor import get_media_duration
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


async def _synthesize_one(text: str, output_path: Path) -> None:
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    await communicate.save(str(output_path))


async def _synthesize_all(
    jobs: list[tuple[dict[str, Any], str, Path]],
) -> list[tuple[dict[str, Any], Path | None, str | None]]:
    async def run_one(
        segment: dict[str, Any],
        text: str,
        output_path: Path,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        try:
            await _synthesize_one(text, output_path)
            return segment, output_path, None
        except Exception as exc:
            return segment, None, str(exc)

    return await asyncio.gather(*(run_one(*job) for job in jobs))


def run_tts(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    segments_data = read_json(paths.segments_json)
    segments = segments_data.get("segments", [])

    paths.narration_audio_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[dict[str, Any], str, Path]] = []

    for segment in segments:
        text = segment.get("narration", "")

        if not segment.get("narration_safe") or not text:
            continue

        filename = f"seg_{segment['start']:.2f}.mp3"
        output_path = paths.narration_audio_dir / filename
        jobs.append((segment, text, output_path))

    synthesized_count = 0
    failed_count = 0

    if jobs:
        results = asyncio.run(_synthesize_all(jobs))

        for segment, output_path, error in results:
            if error is not None:
                segment["narration_audio"] = None
                segment["narration_audio_error"] = error
                failed_count += 1
                continue

            filename = output_path.name
            segment["narration_audio"] = f"narration_audio/{filename}"
            segment["narration_audio_duration"] = round(
                get_media_duration(output_path), 2
            )
            synthesized_count += 1

    atomic_write_json(paths.segments_json, segments_data)

    return {
        "synthesized_count": synthesized_count,
        "failed_count": failed_count,
    }
