from pathlib import Path
from typing import Any

from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

DEFAULT_SETTINGS = {
    "narration_min_duration": 3.0,
    "frame_interval": 1.2,
    "max_frames_per_segment": 10,
    "language": "ko",
    "pipeline_version": "mvp2",
}


def _segment_id(index: int) -> str:
    return f"seg_{index + 1:04d}"


def _audio_type(raw_segment: dict[str, Any]) -> str:
    if raw_segment.get("type") == "speech":
        return "speech"
    return "non_speech"


def _empty_persons() -> dict[str, Any]:
    return {"visible_person_ids": []}


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
        "narration_safe": bool(
            raw_segment.get("narration_safe", narration_candidate)
        ),
        "narration_candidate": narration_candidate,
        "context": {
            "previous_speech": None,
            "next_speech": None,
            "previous_segment_id": None,
            "next_segment_id": None,
        },
        "frames": [],
        "persons": _empty_persons(),
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


def finalize_segments_enriched(job_id: str) -> dict[str, Any]:
    """Build enriched output from voice segments, then attach face results."""
    paths = JobPaths(job_id)
    voice_data = read_json(paths.voice_segments_json)
    video_path = paths.find_input_video()
    enriched = build_segments_enriched(
        job_id=job_id,
        raw_segments=voice_data.get("segments", []),
        video_path=video_path,
        video_metadata=voice_data.get("video_metadata", {}),
        language=voice_data.get("language"),
    )
    atomic_write_json(paths.enriched_segments_json, enriched)
    return merge_face_segments_into_segments(
        paths.enriched_segments_json,
        paths.face_segments_json,
        job_id=job_id,
        save=True,
    )


def adapt_face_segments_samples(
    face_data: dict[str, Any],
    job_id: str,
) -> list[dict[str, Any]]:
    adapted: list[dict[str, Any]] = []

    for sample in face_data.get("samples") or []:
        relative_path = sample["path"]
        frame_id = Path(relative_path).stem
        annotated_path = _job_relative_path(job_id, relative_path)
        visible_person_ids = [
            person_id
            for person_id in sample.get("visible_person_ids") or []
            if person_id
        ]

        adapted.append(
            {
                "frame_id": frame_id,
                "timestamp": float(sample["timestamp"]),
                "path": annotated_path,
                "visible_person_ids": visible_person_ids,
            }
        )

    return adapted


def _apply_face_frames_to_segments(
    enriched: dict[str, Any],
    all_frames: list[dict[str, Any]],
    max_frames_per_segment: int,
) -> dict[str, Any]:
    for segment in enriched.get("segments", []):
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
            for person_id in frame.get("visible_person_ids") or []:
                if person_id and person_id not in person_ids:
                    person_ids.append(person_id)

        segment["persons"]["visible_person_ids"] = person_ids

    return enriched


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
        return sorted_frames

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
        selected.append(best)

    return sorted(selected, key=lambda frame: frame["timestamp"])


def merge_face_segments_into_segments(
    segments_enriched_path: str | Path,
    face_segments_path: str | Path,
    job_id: str | None = None,
    max_frames_per_segment: int | None = None,
    save: bool = True,
) -> dict[str, Any]:
    enriched_path = Path(segments_enriched_path)
    face_path = Path(face_segments_path)

    enriched = read_json(enriched_path)
    if not face_path.exists():
        return enriched

    face_data = read_json(face_path)
    resolved_job_id = job_id or enriched.get("job_id") or enriched_path.parent.name
    max_frames = max_frames_per_segment
    if max_frames is None:
        max_frames = int(
            enriched.get("settings", {}).get(
                "max_frames_per_segment",
                DEFAULT_SETTINGS["max_frames_per_segment"],
            )
        )

    all_frames = adapt_face_segments_samples(face_data, resolved_job_id)
    enriched = _apply_face_frames_to_segments(enriched, all_frames, max_frames)

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

    enriched = _apply_face_frames_to_segments(
        enriched,
        all_frames,
        max_frames_per_segment,
    )

    if save:
        atomic_write_json(enriched_path, enriched)

    return enriched
