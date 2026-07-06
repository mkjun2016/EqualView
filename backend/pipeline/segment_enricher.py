from pathlib import Path
from typing import Any

from config import ANNOTATED_FRAME_INTERVAL_SECONDS
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

DEFAULT_SETTINGS = {
    "narration_min_duration": 3.0,
    "frame_interval": ANNOTATED_FRAME_INTERVAL_SECONDS,
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

    text = raw_segment.get("text") or ""

    return {
        "segment_id": _segment_id(index),
        "start": start,
        "end": end,
        "duration": duration,
        "audio_type": audio_type,
        "text": text,
        "narration_candidate": narration_candidate,
        "context": {
            "previous_speech": None,
            "next_speech": None,
            "previous_segment_id": None,
            "next_segment_id": None,
        },
        "frames": [],
        "visible_person_in_segment": None,
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


def _face_person_ids(faces: list[Any]) -> list[str]:
    person_ids: list[str] = []

    for face in faces:
        person_id = face if isinstance(face, str) else face.get("person_id")
        if person_id and person_id not in person_ids:
            person_ids.append(person_id)

    return person_ids


def adapt_face_segments_samples(
    face_data: dict[str, Any],
    job_id: str,
) -> list[dict[str, Any]]:
    adapted: list[dict[str, Any]] = []

    for sample in face_data.get("samples") or []:
        relative_path = sample["path"]
        frame_id = Path(relative_path).stem
        frame_path = _job_relative_path(job_id, relative_path)

        adapted.append(
            {
                "frame_id": frame_id,
                "timestamp": float(sample["timestamp"]),
                "path": frame_path,
                "faces": _face_person_ids(sample.get("faces") or []),
            }
        )

    return adapted


def _adapt_face_frames(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "frame_id": frame["frame_id"],
            "timestamp": float(frame["timestamp"]),
            "path": frame.get("path") or "",
            "faces": _face_person_ids(frame.get("faces") or []),
        }
        for frame in frames
    ]


def _apply_face_frames_to_segments(
    enriched: dict[str, Any],
    all_frames: list[dict[str, Any]],
) -> dict[str, Any]:
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

        chosen_frames = sorted(matching, key=lambda frame: frame["timestamp"])
        segment["frames"] = chosen_frames

        person_ids: list[str] = []
        for frame in chosen_frames:
            for person_id in frame.get("faces") or []:
                if person_id and person_id not in person_ids:
                    person_ids.append(person_id)

        segment["visible_person_in_segment"] = person_ids or None

    return enriched


def merge_face_segments_into_segments(
    segments_enriched_path: str | Path,
    face_segments_path: str | Path,
    job_id: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    enriched_path = Path(segments_enriched_path)
    face_path = Path(face_segments_path)

    enriched = read_json(enriched_path)
    if not face_path.exists():
        return enriched

    face_data = read_json(face_path)
    resolved_job_id = job_id or enriched.get("job_id") or enriched_path.parent.name

    all_frames = adapt_face_segments_samples(face_data, resolved_job_id)
    enriched = _apply_face_frames_to_segments(enriched, all_frames)

    if save:
        atomic_write_json(enriched_path, enriched)

    return enriched


def try_merge_face_segments_for_job(job_id: str) -> bool:
    paths = JobPaths(job_id)

    if not paths.segments_enriched_json.exists():
        return False

    if not paths.face_segments_json.exists():
        return False

    merge_face_segments_into_segments(
        paths.segments_enriched_json,
        paths.face_segments_json,
        job_id=job_id,
    )
    return True


def merge_face_frames_into_segments(
    segments_enriched_path: str | Path,
    face_frames_path: str | Path,
    save: bool = True,
) -> dict[str, Any]:
    enriched_path = Path(segments_enriched_path)
    face_path = Path(face_frames_path)

    enriched = read_json(enriched_path)
    if not face_path.exists():
        return enriched

    face_data = read_json(face_path)
    all_frames = _adapt_face_frames(face_data.get("frames") or [])

    enriched = _apply_face_frames_to_segments(
        enriched,
        all_frames,
    )

    if save:
        atomic_write_json(enriched_path, enriched)

    return enriched
