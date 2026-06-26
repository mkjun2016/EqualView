from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from config import (
    ANNOTATED_FRAME_INTERVAL_SECONDS,
    FACE_FRAME_SIMILARITY_THRESHOLD,
)
from pipeline.face_renderer import (
    draw_face_annotations,
    save_annotated_frame,
)
from pipeline.face_tracker import FaceTracker
from pipeline.audio_extractor import get_media_duration
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


def run_face_analysis(job_id: str) -> dict[str, Any]:
    """
    Sample the source video at a fixed interval, detect/track faces on those
    frames only, and save annotated JPG frames plus face_segments.json.
    """
    paths = JobPaths(job_id)
    input_video = paths.find_input_video()

    paths.annotated_frames_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(input_video))

    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {input_video}")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    if fps <= 0:
        fps = 30.0

    frame_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    reported_frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    if frame_width <= 0 or frame_height <= 0:
        capture.release()
        raise RuntimeError("Video has invalid dimensions.")

    try:
        duration = get_media_duration(input_video)
    except Exception:
        duration = (
            reported_frame_count / fps
            if reported_frame_count > 0
            else 0
        )

    tracker = FaceTracker()
    sample_interval = _sample_interval_seconds()
    next_sample_timestamp = 0.0
    processed_frame_count = 0
    samples: list[dict[str, Any]] = []
    last_saved_fingerprint: np.ndarray | None = None
    sampled_candidate_count = 0
    similarity_skipped_count = 0
    last_processed_timestamp = 0.0
    last_sample_candidate_timestamp = None
    last_saved_timestamp = None

    try:
        while True:
            success, frame = capture.read()

            if not success:
                break

            frame_index = processed_frame_count
            timestamp = frame_index / fps
            processed_frame_count += 1
            last_processed_timestamp = timestamp

            if timestamp + 0.001 < next_sample_timestamp:
                continue

            while next_sample_timestamp <= timestamp + 0.001:
                next_sample_timestamp += sample_interval

            sampled_candidate_count += 1
            last_sample_candidate_timestamp = timestamp
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
                timestamp=timestamp,
                frame_width=frame_width,
                frame_height=frame_height,
            )

            annotated_frame = draw_face_annotations(
                frame=frame,
                detections=detections,
            )

            filename = _frame_filename(timestamp)
            output_path = paths.annotated_frames_dir / filename

            save_annotated_frame(
                frame=annotated_frame,
                output_path=output_path,
            )

            samples.append(
                {
                    "timestamp": round(timestamp, 3),
                    "path": f"annotated_frames/{filename}",
                    "visible_person_ids": [
                        detection["person_id"]
                        for detection in detections
                    ],
                    "faces": [
                        {
                            "person_id": detection["person_id"],
                            "color": detection["color"],
                            "confidence": detection["confidence"],
                            "bbox": detection["bbox"],
                        }
                        for detection in detections
                    ],
                }
            )

            last_saved_fingerprint = fingerprint
            last_saved_timestamp = timestamp

    finally:
        capture.release()

    if duration <= 0 and processed_frame_count > 0:
        duration = processed_frame_count / fps

    processed_duration = processed_frame_count / fps if fps > 0 else 0
    duration_gap = max(0.0, duration - processed_duration)

    result = {
        "schema_version": "1.0",
        "source": {
            "duration": round(duration, 3),
            "fps": round(fps, 3),
            "width": frame_width,
            "height": frame_height,
            "reported_frame_count": reported_frame_count,
            "processed_frame_count": processed_frame_count,
            "processed_duration": round(processed_duration, 3),
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
        },
        "identities": tracker.get_identities(),
        "samples": samples,
    }

    atomic_write_json(paths.face_segments_json, result)

    return {
        "duration": round(duration, 3),
        "face_count": len(tracker.identities),
        "sample_count": len(samples),
        "face_segments_json": paths.face_segments_json.name,
    }


def _sample_interval_seconds() -> float:
    if ANNOTATED_FRAME_INTERVAL_SECONDS <= 0:
        return 1 / 30

    return ANNOTATED_FRAME_INTERVAL_SECONDS


def _frame_filename(timestamp: float) -> str:
    return f"frame_{timestamp:.1f}.jpg"


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

