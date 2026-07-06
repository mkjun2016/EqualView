from pathlib import Path
from typing import Any

from config import FRAME_INTERVAL_SECONDS
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

DEFAULT_SETTINGS = {
    "narration_min_duration": 3.0,
    "frame_interval": FRAME_INTERVAL_SECONDS,
    "language": "ko",
    "pipeline_version": "mvp2",
}


def _segment_id(index: int) -> str:
    return f"seg_{index + 1:04d}"


def _audio_type(raw_segment: dict[str, Any]) -> str:
    if raw_segment.get("type") == "speech":
        return "speech"
    return "non_speech"


def _build_enriched_segment(
    raw_segment: dict[str, Any],
    index: int,
    min_duration: float,
) -> dict[str, Any]:
    start = round(float(raw_segment["start"]), 2)
    end = round(float(raw_segment["end"]), 2)
    duration = round(end - start, 2)
    audio_type = _audio_type(raw_segment)
    narration_candidate = audio_type == "non_speech" and duration >= min_duration

    return {
        "segment_id": _segment_id(index),
        "start": start,
        "end": end,
        "duration": duration,
        "audio_type": audio_type,
        "text": raw_segment.get("text") or "",
        "narration_candidate": narration_candidate,
        "context": {
            "previous_speech": None,
            "next_speech": None,
            "previous_segment_id": None,
            "next_segment_id": None,
        },
        "frames": [],
        "scene_analysis": None,
        "generated_narration": None,
        "tts": None,
    }


def _attach_speech_context(segments: list[dict[str, Any]]) -> None:
    speech_indices = [
        i for i, segment in enumerate(segments) if segment["audio_type"] == "speech"
    ]

    for index, segment in enumerate(segments):
        previous = None
        previous_id = None
        for speech_index in reversed(speech_indices):
            if speech_index < index:
                previous = segments[speech_index]["text"]
                previous_id = segments[speech_index]["segment_id"]
                break

        next_speech = None
        next_id = None
        for speech_index in speech_indices:
            if speech_index > index:
                next_speech = segments[speech_index]["text"]
                next_id = segments[speech_index]["segment_id"]
                break

        segment["context"] = {
            "previous_speech": previous,
            "next_speech": next_speech,
            "previous_segment_id": previous_id,
            "next_segment_id": next_id,
        }


def _build_summary(segments: list[dict[str, Any]]) -> dict[str, int]:
    speech_count = sum(1 for segment in segments if segment["audio_type"] == "speech")
    non_speech_count = len(segments) - speech_count
    narration_candidates = sum(
        1 for segment in segments if segment["narration_candidate"]
    )

    return {
        "total_segments": len(segments),
        "speech_segments": speech_count,
        "non_speech_segments": non_speech_count,
        "narration_candidate_count": narration_candidates,
    }


def _job_relative_path(job_id: str, filename: str) -> str:
    return f"uploads/{job_id}/{filename}"


def build_segments_enriched(
    job_id: str,
    raw_segments: list[dict[str, Any]],
    video_path: Path,
    video_metadata: dict[str, Any],
    language: str | None = None,
    settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_settings = {**DEFAULT_SETTINGS, **(settings or {})}
    if language:
        merged_settings["language"] = language

    min_duration = float(merged_settings["narration_min_duration"])
    enriched_segments = [
        _build_enriched_segment(raw_segment, index, min_duration)
        for index, raw_segment in enumerate(raw_segments)
    ]
    _attach_speech_context(enriched_segments)

    return {
        "job_id": job_id,
        "video": {
            "filename": video_path.name,
            "input_video_path": _job_relative_path(job_id, video_path.name),
            "audio_path": _job_relative_path(job_id, "audio.wav"),
            "duration": round(float(video_metadata.get("duration", 0)), 2),
            "fps": video_metadata.get("fps"),
            "width": video_metadata.get("width"),
            "height": video_metadata.get("height"),
        },
        "settings": merged_settings,
        "summary": _build_summary(enriched_segments),
        "segments": enriched_segments,
    }


def save_segments_enriched(job_id: str, enriched: dict[str, Any]) -> Path:
    path = JobPaths(job_id).segments_enriched_json
    atomic_write_json(path, enriched)
    return path


def merge_frame_samples_into_segments(
    segments_enriched_path: str | Path,
    frame_samples_path: str | Path,
    job_id: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    enriched_path = Path(segments_enriched_path)
    samples_path = Path(frame_samples_path)

    enriched = read_json(enriched_path)
    if not samples_path.exists():
        return enriched

    frame_data = read_json(samples_path)
    resolved_job_id = job_id or enriched.get("job_id") or enriched_path.parent.name
    samples = _adapt_frame_samples(frame_data, resolved_job_id)

    for segment in enriched.get("segments", []):
        if segment.get("audio_type") != "non_speech":
            segment["frames"] = []
            continue

        start = float(segment["start"])
        end = float(segment["end"])
        segment["frames"] = [
            sample
            for sample in samples
            if start <= float(sample["timestamp"]) <= end
        ]

    if save:
        atomic_write_json(enriched_path, enriched)

    return enriched


def try_merge_frame_samples_for_job(job_id: str) -> bool:
    paths = JobPaths(job_id)
    if not paths.segments_enriched_json.exists():
        return False
    if not paths.frame_samples_json.exists():
        return False

    merge_frame_samples_into_segments(
        paths.segments_enriched_json,
        paths.frame_samples_json,
        job_id=job_id,
    )
    return True


def _adapt_frame_samples(
    frame_data: dict[str, Any],
    job_id: str,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []

    for sample in frame_data.get("samples") or []:
        relative_path = sample["path"]
        samples.append(
            {
                "frame_id": sample.get("frame_id") or Path(relative_path).stem,
                "timestamp": float(sample["timestamp"]),
                "path": _job_relative_path(job_id, relative_path),
            }
        )

    return samples
