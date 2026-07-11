import pytest

from services.job_store import FileJobStore, is_post_processing_ready
from utils.json_io import atomic_write_json
from utils.paths import JobPaths

JOB_ID = "job-store-test"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("config.UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("utils.paths.UPLOAD_DIR", tmp_path)
    return FileJobStore()


def _ready_job(extra: dict | None = None) -> dict:
    data = {
        "job_id": JOB_ID,
        "status": "COMPLETED",
        "face_status": "COMPLETED",
        "transition_status": "COMPLETED",
        "narration_status": "PENDING",
        "combine_status": "PENDING",
    }
    if extra:
        data.update(extra)
    return data


def test_is_post_processing_ready():
    assert is_post_processing_ready(_ready_job()) is True
    assert is_post_processing_ready(_ready_job({"face_status": "PROCESSING"})) is False
    assert is_post_processing_ready(_ready_job({"narration_status": "PROCESSING"})) is False


def test_try_begin_post_processing_claims_once(store):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths.job_json, _ready_job())

    assert store.try_begin_post_processing(JOB_ID) is True
    assert store.try_begin_post_processing(JOB_ID) is False

    job_data = store.get(JOB_ID)
    assert job_data["narration_status"] == "PROCESSING"
    assert job_data["current_step"] == "화면해설 생성 중"


def test_try_begin_post_processing_waits_for_face(store):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        paths.job_json,
        _ready_job({"status": "COMPLETED", "face_status": "PROCESSING"}),
    )

    assert store.try_begin_post_processing(JOB_ID) is False
