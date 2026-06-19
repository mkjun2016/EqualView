from datetime import datetime, timezone
from typing import Any

from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


job_store = FileJobStore()
