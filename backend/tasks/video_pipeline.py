import importlib
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _ensure_backend_path() -> None:
    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)
    os.chdir(backend)


_ensure_backend_path()

from celery_app import celery_app
from services.job_store import job_store


@celery_app.task(name="tasks.process_video_job")
def process_video_job(job_id: str) -> None:
    try:
        _ensure_backend_path()
        runner = importlib.import_module("pipeline.runner")
        runner.run_analysis(job_id, job_store)
    except Exception as exc:
        job_store.update(
            job_id,
            status="FAILED",
            error=str(exc),
            current_step="Failed",
        )
        raise


@celery_app.task(name="tasks.process_frame_job")
def process_frame_job(job_id: str) -> None:
    try:
        _ensure_backend_path()

        job_store.update(
            job_id,
            frame_status="PROCESSING",
            frame_progress=10,
            frame_current_step="프레임 추출 시작",
            frame_error=None,
        )

        frame_extractor = importlib.import_module("pipeline.frame_extractor")
        result = frame_extractor.run_frame_extraction(job_id)

        segment_enricher = importlib.import_module("pipeline.segment_enricher")
        segment_enricher.try_merge_frame_samples_for_job(job_id)

        job_store.update(
            job_id,
            frame_status="COMPLETED",
            frame_progress=100,
            frame_current_step="프레임 추출 완료",
            frame_error=None,
            frame_result=result,
        )
    except Exception as exc:
        job_store.update(
            job_id,
            frame_status="FAILED",
            frame_error=str(exc),
            frame_current_step="프레임 추출 실패",
        )
        raise
