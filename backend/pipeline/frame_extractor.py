from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from config import FRAME_INTERVAL_SECONDS, FRAME_SIMILARITY_THRESHOLD
from utils.ffmpeg_paths import probe_media_info
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


def run_frame_extraction(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    input_video = paths.find_input_video()
    paths.frames_dir.mkdir(parents=True, exist_ok=True)

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
        duration = probe_media_info(input_video).duration
    except Exception:
        duration = reported_frame_count / fps if reported_frame_count > 0 else 0

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
                similarity = _frame_similarity(last_saved_fingerprint, fingerprint)
                if similarity >= FRAME_SIMILARITY_THRESHOLD:
                    similarity_skipped_count += 1
                    continue

            filename = _frame_filename(timestamp)
            output_path = paths.frames_dir / filename
            _save_frame(frame, output_path)

            samples.append(
                {
                    "frame_id": output_path.stem,
                    "timestamp": round(timestamp, 3),
                    "path": f"frames/{filename}",
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
            "similarity_threshold": FRAME_SIMILARITY_THRESHOLD,
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
        "samples": samples,
    }

    atomic_write_json(paths.frame_samples_json, result)

    return {
        "duration": round(duration, 3),
        "sample_count": len(samples),
        "frame_samples_json": paths.frame_samples_json.name,
    }


def _sample_interval_seconds() -> float:
    if FRAME_INTERVAL_SECONDS <= 0:
        return 1 / 30
    return FRAME_INTERVAL_SECONDS


def _frame_filename(timestamp: float) -> str:
    return f"frame_{timestamp:.2f}.jpg"


def _frame_fingerprint(frame: np.ndarray) -> np.ndarray:
    resized = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    return gray.astype(np.float32)


def _frame_similarity(previous: np.ndarray, current: np.ndarray) -> float:
    difference = np.mean(np.abs(previous - current))
    return float(1.0 - (difference / 255.0))


def _save_frame(frame: np.ndarray, output_path) -> None:
    success, encoded_image = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, 95],
    )
    if not success:
        raise RuntimeError(f"Could not encode frame: {output_path}")

    output_path.write_bytes(encoded_image.tobytes())
