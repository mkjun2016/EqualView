import fcntl
import json
from datetime import datetime, timezone
from typing import Any

from utils.json_io import atomic_write_json, read_json, to_json_safe
from utils.paths import JobPaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_post_processing_ready(job_data: dict[str, Any]) -> bool:
    return (
        job_data.get("status") == "COMPLETED"
        and job_data.get("face_status") == "COMPLETED"
        and job_data.get("narration_status", "PENDING") == "PENDING"
        and job_data.get("combine_status", "PENDING") == "PENDING"
    )


class JobStore:
    def create(self, job_id: str, data: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def get(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def update(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def exists(self, job_id: str) -> bool:
        raise NotImplementedError


class FileJobStore(JobStore):
    def create(self, job_id: str, data: dict[str, Any]) -> dict[str, Any]:
        paths = JobPaths(job_id)
        paths.job_dir.mkdir(parents=True, exist_ok=True)

        now = _utc_now()
        job_data = {
            "job_id": job_id,
            "status": "PENDING",
            "progress": 0,
            "current_step": "작업 대기 중",
            "error": None,
            "created_at": now,
            "updated_at": now,
            **data,
        }

        atomic_write_json(paths.job_json, job_data)
        return job_data

    def get(self, job_id: str) -> dict[str, Any] | None:
        paths = JobPaths(job_id)
        if not paths.job_json.exists():
            return None
        return read_json(paths.job_json)

    def update(self, job_id: str, **kwargs: Any) -> dict[str, Any]:
        job_data = self.get(job_id)
        if job_data is None:
            raise FileNotFoundError(f"Job not found: {job_id}")

        job_data.update(kwargs)
        job_data["updated_at"] = _utc_now()

        paths = JobPaths(job_id)
        atomic_write_json(paths.job_json, job_data)
        return job_data

    def exists(self, job_id: str) -> bool:
        return JobPaths(job_id).job_json.exists()

    def try_begin_post_processing(self, job_id: str) -> bool:
        """
        Whisper + Face가 모두 끝났을 때 후처리(narration/TTS)를 단 한 번만 시작한다.
        두 Celery task가 동시에 완료해도 file lock으로 중복 실행을 막는다.
        """
        paths = JobPaths(job_id)
        if not paths.job_json.exists():
            return False

        with open(paths.job_json, "r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                job_data = json.load(handle)

                if not is_post_processing_ready(job_data):
                    return False

                job_data["narration_status"] = "PROCESSING"
                job_data["current_step"] = "화면해설 생성 중"
                job_data["updated_at"] = _utc_now()

                handle.seek(0)
                json.dump(
                    to_json_safe(job_data),
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
                handle.truncate()
                handle.flush()
                return True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


job_store = FileJobStore()
