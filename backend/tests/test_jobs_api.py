import json

import pytest
from fastapi.testclient import TestClient

from utils.json_io import atomic_write_json
from utils.paths import JobPaths

JOB_ID = "api-test-job-001"

MOCK_SEGMENTS = {
    "segments": [
        {
            "start": 0.0,
            "end": 2.0,
            "type": "non_speech",
            "sound_category": "silence_or_background",
            "text": "",
        },
        {
            "start": 2.0,
            "end": 5.0,
            "type": "speech",
            "sound_category": "human_speech",
            "text": "hello",
        },
    ]
}

MOCK_ENRICHED = {
    "job_id": JOB_ID,
    "video": {"filename": "input.mp4"},
    "settings": {"pipeline_version": "mvp2"},
    "summary": {"total_segments": 2},
    "segments": [{"segment_id": "seg_0001"}],
}


@pytest.fixture
def client(upload_dir):
    from api.main import app

    return TestClient(app)


@pytest.fixture
def completed_job(upload_dir):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    job_data = {
        "job_id": JOB_ID,
        "status": "COMPLETED",
        "progress": 100,
        "current_step": "분석 완료",
        "error": None,
    }
    atomic_write_json(paths.job_json, job_data)
    atomic_write_json(paths.segments_json, MOCK_SEGMENTS)
    atomic_write_json(paths.segments_enriched_json, MOCK_ENRICHED)

    return paths


def test_get_job_segments_returns_raw_segments(client, completed_job):
    response = client.get(f"/api/jobs/{JOB_ID}/segments")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == MOCK_SEGMENTS, "legacy endpoint must return raw segments.json unchanged"
    assert "segments" in body
    assert body["segments"][1]["type"] == "speech"


def test_get_job_segments_enriched_returns_enriched_json(client, completed_job):
    response = client.get(f"/api/jobs/{JOB_ID}/segments/enriched")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == MOCK_ENRICHED
    assert body["job_id"] == JOB_ID
    assert body["segments"][0]["segment_id"] == "seg_0001"


def test_get_job_segments_enriched_not_found_when_missing_file(client, upload_dir):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.job_json,
        {
            "job_id": JOB_ID,
            "status": "COMPLETED",
            "progress": 100,
            "current_step": "done",
            "error": None,
        },
    )
    atomic_write_json(paths.segments_json, MOCK_SEGMENTS)

    response = client.get(f"/api/jobs/{JOB_ID}/segments/enriched")
    assert response.status_code == 404


def test_get_annotated_frame(client, completed_job):
    frame_name = "frame_1.00.jpg"
    frame_path = completed_job.annotated_frames_dir / frame_name
    completed_job.annotated_frames_dir.mkdir(parents=True, exist_ok=True)
    frame_path.write_bytes(b"fake-jpeg")

    response = client.get(f"/api/jobs/{JOB_ID}/frames/{frame_name}")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"fake-jpeg"


def test_get_annotated_frame_not_found(client, completed_job):
    response = client.get(f"/api/jobs/{JOB_ID}/frames/missing.jpg")
    assert response.status_code == 404
