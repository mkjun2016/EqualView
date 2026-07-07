from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest

from pipeline import narrator
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

JOB_ID = "narrator-test-job"


@pytest.fixture
def job_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("config.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("utils.paths.UPLOAD_DIR", tmp_path)

    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    paths.annotated_frames_dir.mkdir(parents=True, exist_ok=True)

    return paths


def _write_sample_frame(path: Path, color: tuple[int, int, int]) -> None:
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:, :] = color
    cv2.imwrite(str(path), image)


def test_select_frames_evenly_samples_sorted_range():
    samples = [
        {"timestamp": 0.0, "path": "a.jpg"},
        {"timestamp": 1.0, "path": "b.jpg"},
        {"timestamp": 2.0, "path": "c.jpg"},
        {"timestamp": 3.0, "path": "d.jpg"},
        {"timestamp": 4.0, "path": "e.jpg"},
        {"timestamp": 10.0, "path": "f.jpg"},
    ]

    selected = narrator._select_frames(samples, 1.0, 4.0, 3)

    assert [frame["path"] for frame in selected] == ["b.jpg", "d.jpg", "e.jpg"]


def test_prepare_narration_jobs_builds_prompts(job_paths):
    frame_a = job_paths.annotated_frames_dir / "frame_5.00.jpg"
    frame_b = job_paths.annotated_frames_dir / "frame_7.00.jpg"
    _write_sample_frame(frame_a, (255, 0, 0))
    _write_sample_frame(frame_b, (0, 255, 0))

    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "speech": False,
            "narration_safe": False,
            "text": "",
        },
        {
            "start": 2.0,
            "end": 5.0,
            "speech": True,
            "narration_safe": False,
            "text": "Hello there.",
        },
        {
            "start": 5.0,
            "end": 10.0,
            "speech": False,
            "narration_safe": True,
            "text": "",
        },
    ]
    samples = [
        {
            "timestamp": 5.0,
            "path": "annotated_frames/frame_5.00.jpg",
            "visible_person_ids": ["person_001"],
        },
        {
            "timestamp": 7.0,
            "path": "annotated_frames/frame_7.00.jpg",
            "visible_person_ids": ["person_001"],
        },
    ]

    jobs = narrator._prepare_narration_jobs(segments, samples, job_paths.job_dir, 100.0)

    assert len(jobs) == 1
    assert jobs[0].frame_paths == [frame_a, frame_b]
    assert "Hello there." in jobs[0].prompt
    assert segments[2]["frames"] == [
        "annotated_frames/frame_5.00.jpg",
        "annotated_frames/frame_7.00.jpg",
    ]


def test_read_frame_jpeg_bytes_resizes_large_image(job_paths, monkeypatch):
    monkeypatch.setattr(narrator, "NARRATION_FRAME_MAX_PX", 512)
    monkeypatch.setattr(narrator, "NARRATION_JPEG_QUALITY", 80)

    frame_path = job_paths.annotated_frames_dir / "large.jpg"
    _write_sample_frame(frame_path, (10, 20, 30))

    encoded = narrator._read_frame_jpeg_bytes(frame_path)
    decoded = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)

    assert decoded is not None
    assert max(decoded.shape[:2]) <= 512


def test_execute_narration_jobs_runs_in_parallel(job_paths, monkeypatch):
    monkeypatch.setattr(narrator, "NARRATION_REQUEST_STAGGER_SECONDS", 0)
    frame_a = job_paths.job_dir / "a.jpg"
    frame_b = job_paths.job_dir / "b.jpg"
    _write_sample_frame(frame_a, (1, 2, 3))
    _write_sample_frame(frame_b, (4, 5, 6))

    jobs = [
        narrator.NarrationJob(
            segment={"start": 1.0},
            frame_paths=[job_paths.job_dir / "a.jpg"],
            prompt="prompt-a",
        ),
        narrator.NarrationJob(
            segment={"start": 2.0},
            frame_paths=[job_paths.job_dir / "b.jpg"],
            prompt="prompt-b",
        ),
    ]

    def generate_side_effect(*, model, contents):
        prompt = contents[0]
        if prompt == "prompt-a":
            return MagicMock(text=" narration-a ")
        raise RuntimeError("gemini failed")

    client = MagicMock()
    client.models.generate_content.side_effect = generate_side_effect

    narrated_count, failed_count = narrator._execute_narration_jobs(client, jobs)

    assert narrated_count == 1
    assert failed_count == 1
    assert jobs[0].segment["narration"] == "narration-a"
    assert jobs[1].segment["narration"] == ""
    assert jobs[1].segment["narration_error"] == "gemini failed"


def test_run_narration_writes_segments_json(job_paths):
    frame_path = job_paths.annotated_frames_dir / "frame_5.00.jpg"
    _write_sample_frame(frame_path, (100, 100, 100))

    segments = [
        {
            "start": 5.0,
            "end": 10.0,
            "speech": False,
            "narration_safe": True,
            "text": "",
        },
    ]
    atomic_write_json(job_paths.segments_json, {"segments": segments})
    atomic_write_json(
        job_paths.face_segments_json,
        {
            "samples": [
                {
                    "timestamp": 5.0,
                    "path": "annotated_frames/frame_5.00.jpg",
                    "visible_person_ids": [],
                }
            ]
        },
    )

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text=" 어두운 방 안, 한 남자가 창밖을 바라본다. "
    )

    with patch.object(narrator, "get_gemini_client", return_value=mock_client):
        result = narrator.run_narration(JOB_ID)

    saved = read_json(job_paths.segments_json)

    assert result == {
        "narration_job_count": 1,
        "narrated_segment_count": 1,
        "failed_segment_count": 0,
    }
    assert saved["segments"][0]["narration"] == "어두운 방 안, 한 남자가 창밖을 바라본다."


def test_frame_selection_range_uses_face_padding():
    start, end = narrator._frame_selection_range(
        {"start": 66.8, "end": 70.2},
        video_duration=100.0,
    )

    assert start == 66.3
    assert end == 70.7


def test_prepare_narration_jobs_uses_padded_frame_range(job_paths):
    frame_path = job_paths.annotated_frames_dir / "frame_66.30.jpg"
    _write_sample_frame(frame_path, (50, 50, 50))

    segments = [
        {
            "start": 66.8,
            "end": 70.2,
            "speech": False,
            "narration_safe": True,
            "text": "",
        },
    ]
    samples = [
        {
            "timestamp": 66.3,
            "path": "annotated_frames/frame_66.30.jpg",
            "visible_person_ids": [],
        },
    ]

    jobs = narrator._prepare_narration_jobs(
        segments,
        samples,
        job_paths.job_dir,
        video_duration=100.0,
    )

    assert len(jobs) == 1
    assert segments[0]["frames"] == ["annotated_frames/frame_66.30.jpg"]


def test_generate_narration_retries_transient_errors(job_paths, monkeypatch):
    frame_path = job_paths.annotated_frames_dir / "frame.jpg"
    _write_sample_frame(frame_path, (1, 2, 3))
    monkeypatch.setattr(narrator, "NARRATION_MAX_RETRIES", 2)
    monkeypatch.setattr(narrator, "NARRATION_RETRY_BASE_SECONDS", 0.01)
    monkeypatch.setattr(narrator, "NARRATION_RETRY_MAX_SECONDS", 0.05)

    client = MagicMock()
    client.models.generate_content.side_effect = [
        RuntimeError("503 UNAVAILABLE. high demand"),
        RuntimeError("429 RESOURCE_EXHAUSTED"),
        MagicMock(text=" recovered narration "),
    ]

    result = narrator._generate_narration(client, [frame_path], "prompt")

    assert result == "recovered narration"
    assert client.models.generate_content.call_count == 3


def test_resolve_narration_status():
    assert narrator.resolve_narration_status(
        {
            "narration_job_count": 0,
            "narrated_segment_count": 0,
            "failed_segment_count": 0,
        }
    ) == "COMPLETED"
    assert narrator.resolve_narration_status(
        {
            "narration_job_count": 3,
            "narrated_segment_count": 3,
            "failed_segment_count": 0,
        }
    ) == "COMPLETED"
    assert narrator.resolve_narration_status(
        {
            "narration_job_count": 3,
            "narrated_segment_count": 0,
            "failed_segment_count": 3,
        }
    ) == "FAILED"
    assert narrator.resolve_narration_status(
        {
            "narration_job_count": 3,
            "narrated_segment_count": 2,
            "failed_segment_count": 1,
        }
    ) == "PARTIAL"
