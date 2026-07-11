from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np

from config import (
    ANNOTATED_FRAME_INTERVAL_SECONDS,
    FACE_FRAME_SIMILARITY_THRESHOLD,
)
from pipeline.face_ranges import build_sample_timestamps_in_ranges
from pipeline.face_renderer import (
    draw_face_annotations,
    save_annotated_frame,
)
from pipeline.face_tracker import FaceTracker
from utils.ffmpeg_paths import extract_video_frame_jpeg_bytes, probe_media_info
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


def run_face_analysis(
    job_id: str,
    time_ranges: list[dict[str, float]] | None = None,
) -> dict[str, Any]:
    """
    Sample the source video at a fixed interval using ffmpeg timestamp seeks,
    detect/track faces on those frames only, and save annotated JPG frames
    plus face_segments.json.

    When ``time_ranges`` is provided, only those windows are sampled.
    ``None`` keeps the legacy full-video behavior.
    """
    paths = JobPaths(job_id)
    input_video = paths.find_input_video()

    paths.annotated_frames_dir.mkdir(parents=True, exist_ok=True)

    video_metadata = probe_media_info(input_video).metadata
    duration = float(video_metadata.get("duration") or 0.0)
    fps = float(video_metadata.get("fps") or 30.0)
    frame_width = int(video_metadata.get("width") or 0)
    frame_height = int(video_metadata.get("height") or 0)
    reported_frame_count = int(duration * fps) if duration > 0 and fps > 0 else 0

    sample_interval = _sample_interval_seconds()
    analyzed_ranges = _resolve_analyzed_ranges(time_ranges, duration)
    tracker = FaceTracker()
    samples: list[dict[str, Any]] = []
    last_saved_fingerprint: np.ndarray | None = None
    sampled_candidate_count = 0
    similarity_skipped_count = 0
    decoded_frame_count = 0
    last_processed_timestamp = 0.0
    last_sample_candidate_timestamp = None
    last_saved_timestamp = None

    if not analyzed_ranges:
        result = _build_face_segments_result(
            duration=duration,
            fps=fps,
            frame_width=frame_width,
            frame_height=frame_height,
            reported_frame_count=reported_frame_count,
            decoded_frame_count=decoded_frame_count,
            sample_interval=sample_interval,
            sampled_candidate_count=sampled_candidate_count,
            samples=samples,
            similarity_skipped_count=similarity_skipped_count,
            last_processed_timestamp=last_processed_timestamp,
            last_sample_candidate_timestamp=last_sample_candidate_timestamp,
            last_saved_timestamp=last_saved_timestamp,
            analyzed_ranges=analyzed_ranges,
            tracker=tracker,
        )
        atomic_write_json(paths.face_segments_json, result)

        return {
            "duration": round(duration, 3),
            "face_count": 0,
            "sample_count": 0,
            "analyzed_ranges": analyzed_ranges,
            "face_segments_json": paths.face_segments_json.name,
        }

    for range_index, time_range in enumerate(analyzed_ranges):
        if range_index > 0:
            last_saved_fingerprint = None

        sample_timestamps = build_sample_timestamps_in_ranges(
            [time_range],
            sample_interval,
        )

        for timestamp in sample_timestamps:
            frame, actual_timestamp = _read_frame_at(input_video, timestamp)
            if frame is None:
                continue

            if frame_width <= 0 or frame_height <= 0:
                frame_height, frame_width = frame.shape[:2]

            decoded_frame_count += 1
            last_processed_timestamp = actual_timestamp
            sampled_candidate_count += 1
            last_sample_candidate_timestamp = actual_timestamp
            fingerprint = _frame_fingerprint(frame)

            if last_saved_fingerprint is not None:
                similarity = _frame_similarity(
                    last_saved_fingerprint,
                    fingerprint,
                )

                if similarity >= FACE_FRAME_SIMILARITY_THRESHOLD:
                    similarity_skipped_count += 1
                    continue

            faces = tracker.detect(frame) 


            detections = tracker.assign_faces(
                faces=faces,
                timestamp=actual_timestamp,
                frame_width=frame_width,
                frame_height=frame_height,
            )

            annotated_frame = draw_face_annotations(
                frame=frame,
                detections=detections,
            )

            filename = _frame_filename(actual_timestamp)
            output_path = paths.annotated_frames_dir / filename

            save_annotated_frame(
                frame=annotated_frame,
                output_path=output_path,
            )

            samples.append(
                {
                    "timestamp": actual_timestamp,
                    "path": f"annotated_frames/{filename}",
                    "visible_person_ids": [
                        detection["person_id"]
                        for detection in detections
                    ],
                }
            )

            last_saved_fingerprint = fingerprint
            last_saved_timestamp = actual_timestamp

    if frame_width <= 0 or frame_height <= 0:
        raise RuntimeError("Video has invalid dimensions.")

    if duration <= 0 and decoded_frame_count > 0:
        duration = last_processed_timestamp

    duration_gap = max(0.0, duration - last_processed_timestamp)

    result = _build_face_segments_result(
        duration=duration,
        fps=fps,
        frame_width=frame_width,
        frame_height=frame_height,
        reported_frame_count=reported_frame_count,
        decoded_frame_count=decoded_frame_count,
        sample_interval=sample_interval,
        sampled_candidate_count=sampled_candidate_count,
        samples=samples,
        similarity_skipped_count=similarity_skipped_count,
        last_processed_timestamp=last_processed_timestamp,
        last_sample_candidate_timestamp=last_sample_candidate_timestamp,
        last_saved_timestamp=last_saved_timestamp,
        analyzed_ranges=analyzed_ranges,
        tracker=tracker,
    )

    atomic_write_json(paths.face_segments_json, result)

    return {
        "duration": round(duration, 3),
        "face_count": len(tracker.identities),
        "sample_count": len(samples),
        "analyzed_ranges": analyzed_ranges,
        "face_segments_json": paths.face_segments_json.name,
    }


def _build_face_segments_result(
    *,
    duration: float,
    fps: float,
    frame_width: int,
    frame_height: int,
    reported_frame_count: int,
    decoded_frame_count: int,
    sample_interval: float,
    sampled_candidate_count: int,
    samples: list[dict[str, Any]],
    similarity_skipped_count: int,
    last_processed_timestamp: float,
    last_sample_candidate_timestamp: float | None,
    last_saved_timestamp: float | None,
    analyzed_ranges: list[dict[str, float]],
    tracker: FaceTracker,
) -> dict[str, Any]:
    duration_gap = max(0.0, duration - last_processed_timestamp)

    return {
        "schema_version": "1.0",
        "source": {
            "duration": round(duration, 3),
            "fps": round(fps, 3),
            "width": frame_width,
            "height": frame_height,
            "reported_frame_count": reported_frame_count,
            "processed_frame_count": decoded_frame_count,
            "processed_duration": round(last_processed_timestamp, 3),
            "sample_interval_seconds": sample_interval,
            "similarity_threshold": FACE_FRAME_SIMILARITY_THRESHOLD,
            "sample_candidate_count": sampled_candidate_count,
            "saved_sample_count": len(samples),
            "similarity_skipped_count": similarity_skipped_count,
            "last_processed_timestamp": round(last_processed_timestamp, 3),
            "last_sample_candidate_timestamp": (
                round(last_sample_candidate_timestamp, 3)
                if last_sample_candidate_timestamp is not None
                else None
            ),
            "last_saved_timestamp": (
                round(last_saved_timestamp, 3)
                if last_saved_timestamp is not None
                else None
            ),
            "duration_gap": round(duration_gap, 3),
            "analyzed_ranges": analyzed_ranges,
            "sampling_mode": "ffmpeg_seek",
        },
        "samples": samples,
    }


def _resolve_analyzed_ranges(
    time_ranges: list[dict[str, float]] | None,
    duration: float,
) -> list[dict[str, float]]:
    if time_ranges is not None:
        return time_ranges

    if duration <= 0:
        return []

    return [{"start": 0.0, "end": round(duration, 3)}]


def _sample_interval_seconds() -> float:
    if ANNOTATED_FRAME_INTERVAL_SECONDS <= 0:
        return 1 / 30

    return ANNOTATED_FRAME_INTERVAL_SECONDS


def _build_sample_timestamps(duration: float, interval: float) -> list[float]:
    if duration <= 0 or interval <= 0:
        return []

    return build_sample_timestamps_in_ranges(
        [{"start": 0.0, "end": round(duration, 3)}],
        interval,
    )


def _read_frame_at(
    video_path: Path,
    timestamp: float,
) -> tuple[np.ndarray | None, float]:
    jpeg_bytes = extract_video_frame_jpeg_bytes(video_path, timestamp)
    if not jpeg_bytes:
        return None, round(timestamp, 3)

    frame = cv2.imdecode(
        np.frombuffer(jpeg_bytes, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )
    if frame is None:
        return None, round(timestamp, 3)

    return frame, round(timestamp, 3)


def _frame_filename(timestamp: float) -> str:
    timestamp_text = f"{timestamp:.3f}".rstrip("0").rstrip(".")
    return f"frame_{timestamp_text}.jpg"


def _frame_fingerprint(frame: np.ndarray) -> np.ndarray:
    resized = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    return gray.astype(np.float32)


def _frame_similarity(
    previous: np.ndarray,
    current: np.ndarray,
) -> float:
    difference = np.mean(np.abs(previous - current))

    return float(1.0 - (difference / 255.0))
