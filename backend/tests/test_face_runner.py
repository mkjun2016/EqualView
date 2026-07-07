from pathlib import Path

import cv2
import numpy as np
import pytest

from pipeline import face_runner
from utils.ffmpeg_paths import extract_video_frame_jpeg_bytes


def test_build_sample_timestamps_includes_zero_and_end():
    timestamps = face_runner._build_sample_timestamps(3.2, 1.0)

    assert timestamps == [0.0, 1.0, 2.0, 3.0]


def test_build_sample_timestamps_returns_empty_for_invalid_input():
    assert face_runner._build_sample_timestamps(0, 1.0) == []
    assert face_runner._build_sample_timestamps(10, 0) == []


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        10.0,
        (320, 240),
    )

    for index in range(30):
        frame = np.full((240, 320, 3), index * 8, dtype=np.uint8)
        writer.write(frame)

    writer.release()
    return path


def test_extract_video_frame_jpeg_bytes_reads_target_timestamp(sample_video: Path):
    jpeg_bytes = extract_video_frame_jpeg_bytes(sample_video, 2.0)

    assert jpeg_bytes
    frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert frame is not None
    assert frame.shape == (240, 320, 3)


def test_read_frame_at_uses_ffmpeg(sample_video: Path):
    frame, timestamp = face_runner._read_frame_at(sample_video, 2.0)

    assert frame is not None
    assert timestamp == 2.0
