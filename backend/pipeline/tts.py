# narration(텍스트)을 무료 TTS(edge-tts)로 음성 파일로 합성해
# narration_audio/seg_{start}.mp3 에 저장하고 segments.json에 경로를 채운다.

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import edge_tts

from config import TRANSITION_TTS_VOICE, TTS_VOICE
from utils.ffmpeg_paths import probe_media_info
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


async def _synthesize_one(text: str, output_path: Path, voice: str) -> None:
    # Some additional Korean Edge voices are advertised by Azure but can be
    # intermittently unavailable through the consumer Edge endpoint. Keep a
    # distinct female transition voice when possible and fall back safely so
    # a voice availability issue never removes all transition narration.
    voices = [voice]
    if voice == TRANSITION_TTS_VOICE:
        voices.extend(["ko-KR-HyunsuNeural", "ko-KR-BongJinNeural"])

    last_error: Exception | None = None
    for candidate in dict.fromkeys(voices):
        try:
            output_path.unlink(missing_ok=True)
            communicate = edge_tts.Communicate(text, voice=candidate)
            await communicate.save(str(output_path))
            if output_path.exists() and output_path.stat().st_size > 0:
                return
        except Exception as exc:
            last_error = exc

    output_path.unlink(missing_ok=True)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Edge TTS returned no transition audio")


async def _synthesize_all(
    jobs: list[tuple[dict[str, Any], str, Path, str]],
) -> list[tuple[dict[str, Any], Path | None, str | None]]:
    async def run_one(
        segment: dict[str, Any],
        text: str,
        output_path: Path,
        voice: str,
    ) -> tuple[dict[str, Any], Path | None, str | None]:
        try:
            await _synthesize_one(text, output_path, voice)
            return segment, output_path, None
        except Exception as exc:
            return segment, None, str(exc)

    return await asyncio.gather(*(run_one(*job) for job in jobs))


def run_tts(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    segments_data = read_json(paths.enriched_segments_json)
    transitions_data = read_json(paths.transition_segments_json)
    segments = segments_data.get("segments", [])

    paths.narration_audio_dir.mkdir(parents=True, exist_ok=True)
    paths.transition_audio_dir.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[dict[str, Any], str, Path, str]] = []

    for segment in segments:
        text = segment.get("narration", "")

        if not (
            segment.get("narration_safe")
            or segment.get("narration_candidate")
        ) or not text:
            continue

        filename = f"seg_{segment['start']:.2f}.mp3"
        output_path = paths.narration_audio_dir / filename
        jobs.append((segment, text, output_path, TTS_VOICE))

    for index, transition in enumerate(transitions_data.get("scenes", [])):
        text = transition.get("transition_segment_description", "").strip()
        if not text:
            continue
        filename = f"transition_{index:04d}.mp3"
        output_path = paths.transition_audio_dir / filename
        jobs.append((transition, text, output_path, TRANSITION_TTS_VOICE))

    synthesized_count = 0
    failed_count = 0

    if jobs:
        results = asyncio.run(_synthesize_all(jobs))

        for segment, output_path, error in results:
            if error is not None:
                if "segment_id" in segment:
                    segment["narration_audio"] = None
                    segment["narration_audio_error"] = error
                else:
                    segment["tts_audio"] = None
                    segment["tts_error"] = error
                failed_count += 1
                continue

            filename = output_path.name
            duration = round(probe_media_info(output_path).duration, 2)
            if "segment_id" in segment:
                segment["narration_audio"] = f"narration_audio/{filename}"
                segment["narration_audio_duration"] = duration
            else:
                segment["tts_audio"] = f"transition_audio/{filename}"
                segment["tts_duration"] = duration
            synthesized_count += 1

    # When a transition anchor intersects a regular narration, insert the
    # transition freeze immediately before that narration starts. The regular
    # narration then resumes after the transition and its trailing silence.
    for segment in segments:
        if not segment.get("narration_audio"):
            continue
        narration_start = float(segment["start"])
        narration_end = narration_start + (
            float(segment.get("narration_audio_duration") or 0.0) / 1.1
        )
        for transition in transitions_data.get("scenes", []):
            anchor = float(transition["anchor_timestamp"])
            if narration_start <= anchor < narration_end:
                guarded_start = min(
                    float(segment["end"]),
                    narration_start + 0.7,
                )
                transition["insertion_timestamp"] = guarded_start
                transition["collision_segment_id"] = segment["segment_id"]
                segment["narration_start_timestamp"] = guarded_start
                segment["collision_action"] = "transition_before_narration"

    atomic_write_json(paths.enriched_segments_json, segments_data)
    atomic_write_json(paths.transition_segments_json, transitions_data)

    return {
        "synthesized_count": synthesized_count,
        "failed_count": failed_count,
    }
