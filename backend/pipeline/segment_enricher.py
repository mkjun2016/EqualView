from pathlib import Path
from typing import Any

from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

DEFAULT_SETTINGS = {
    "narration_min_duration": 3.0,
    "frame_interval": 0.5,
    "max_frames_per_segment": 5,
    "language": "ko",
    "pipeline_version": "mvp2",
}


def _segment_id(index: int) -> str:
    return f"seg_{index + 1:04d}"


def _audio_type(raw_segment: dict[str, Any]) -> str:
    if raw_segment.get("type") == "speech":
        return "speech"
    return "non_speech"


def _default_sound_category(raw_segment: dict[str, Any], audio_type: str) -> str:
    existing = raw_segment.get("sound_category")
    if existing:
        return existing
    if audio_type == "speech":
        return "human_speech"
    return "silence_or_background"


def _candidate_reason(audio_type: str, duration: float, min_duration: float) -> str:
    if audio_type == "speech":
        return "speech_segment"
    if duration >= min_duration:
        return "non_speech_duration_over_3s"
    return "duration_under_3s"


def _empty_persons() -> dict[str, Any]:
    return {
        "visible_person_ids": [],
        "main_person_id": None,
        "face_status": "pending",
    }


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

    text = raw_segment.get("text") or ""
    speaker = "unknown" if audio_type == "speech" else None

    return {
        "segment_id": _segment_id(index),
        "start": start,
        "end": end,
        "duration": duration,
        "audio_type": audio_type,
        "sound_category": _default_sound_category(raw_segment, audio_type),
        "speaker": speaker,
        "text": text,
        "narration_candidate": narration_candidate,
        "candidate_reason": _candidate_reason(audio_type, duration, min_duration),
        "duration_limit": duration,
        "context": {
            "previous_speech": None,
            "next_speech": None,
            "previous_segment_id": None,
            "next_segment_id": None,
        },
        "frames": [],
        "persons": _empty_persons(),
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


def _select_frames_for_segment(
    frames: list[dict[str, Any]],
    segment_start: float,
    segment_end: float,
    max_frames: int,
) -> list[dict[str, Any]]:
    if not frames or max_frames <= 0:
        return []

    sorted_frames = sorted(frames, key=lambda frame: frame["timestamp"])
    if len(sorted_frames) <= max_frames:
        return [{**frame, "selected": True} for frame in sorted_frames]

    target_times = [segment_start, (segment_start + segment_end) / 2, segment_end]
    if max_frames > 3:
        step = (segment_end - segment_start) / (max_frames - 1)
        target_times = [segment_start + step * i for i in range(max_frames)]

    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for target in target_times[:max_frames]:
        candidates = [
            frame for frame in sorted_frames if frame["frame_id"] not in used_ids
        ]
        if not candidates:
            break
        best = min(candidates, key=lambda frame: abs(frame["timestamp"] - target))
        used_ids.add(best["frame_id"])
        selected.append({**best, "selected": True})

    return sorted(selected, key=lambda frame: frame["timestamp"])


def merge_face_frames_into_segments(
    segments_enriched_path: str | Path,
    face_frames_path: str | Path,
    max_frames_per_segment: int = 5,
    save: bool = True,
) -> dict[str, Any]:
    enriched_path = Path(segments_enriched_path)
    face_path = Path(face_frames_path)

    enriched = read_json(enriched_path)
    if not face_path.exists():
        return enriched

    face_data = read_json(face_path)
    all_frames = face_data.get("frames") or []

    for segment in enriched.get("segments", []):
        if not segment.get("narration_candidate"):
            continue

        start = float(segment["start"])
        end = float(segment["end"])
        matching = [
            frame
            for frame in all_frames
            if start <= float(frame["timestamp"]) <= end
        ]

        selected_frames = _select_frames_for_segment(
            matching,
            start,
            end,
            max_frames_per_segment,
        )
        segment["frames"] = selected_frames

        person_ids: list[str] = []
        for frame in selected_frames:
            for face in frame.get("faces") or []:
                person_id = face.get("person_id")
                if person_id and person_id not in person_ids:
                    person_ids.append(person_id)

        segment["persons"]["visible_person_ids"] = person_ids
        segment["persons"]["main_person_id"] = person_ids[0] if person_ids else None
        segment["persons"]["face_status"] = (
            "completed" if selected_frames else "missing"
        )

    if save:
        atomic_write_json(enriched_path, enriched)

    return enriched
