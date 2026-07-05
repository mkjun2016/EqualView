import importlib
import os
import sys
import time
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
        result = runner.run_analysis(job_id, job_store)

        face_time_ranges = result.get("face_time_ranges")
        celery_app.send_task(
            "tasks.process_face_job",
            args=[job_id],
            kwargs={"time_ranges": face_time_ranges},
        )
    except Exception as exc:
        job_store.update(
            job_id,
            status="FAILED",
            error=str(exc),
            current_step="실패",
        )
        raise


@celery_app.task(name="tasks.process_face_job")
def process_face_job(
    job_id: str,
    time_ranges: list[dict[str, float]] | None = None,
) -> None:
    started_at = time.monotonic()

    try:
        _ensure_backend_path()

        job_store.update(
            job_id,
            face_status="PROCESSING",
            face_progress=10,
            face_current_step="얼굴 분석 시작",
            face_error=None,
        )

        face_runner = importlib.import_module("pipeline.face_runner")
        result = face_runner.run_face_analysis(job_id, time_ranges=time_ranges)

        segment_enricher = importlib.import_module("pipeline.segment_enricher")
        segment_enricher.try_merge_face_segments_for_job(job_id)

        job_store.update(
            job_id,
            face_status="COMPLETED",
            face_progress=100,
            face_current_step="얼굴 분석 완료",
            face_error=None,
            face_result=result,
            face_seconds=round(time.monotonic() - started_at, 2),
            face_sample_count=result.get("sample_count", 0),
        )
        _run_post_processing_if_ready(job_id)

    except Exception as exc:
        job_store.update(
            job_id,
            face_status="FAILED",
            face_error=str(exc),
            face_current_step="얼굴 분석 실패",
        )
        raise


def _run_post_processing_if_ready(job_id: str) -> None:
    if not job_store.try_begin_post_processing(job_id):
        return

    narration_started_at = time.monotonic()

    try:
        narrator = importlib.import_module("pipeline.narrator")
        narration_result = narrator.run_narration(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            narration_status="FAILED",
            narration_error=str(exc),
            current_step="화면해설 생성 실패",
        )
        return

    job_store.update(
        job_id,
        narration_status="COMPLETED",
        narration_result=narration_result,
        narration_seconds=round(time.monotonic() - narration_started_at, 2),
        combine_status="PROCESSING",
        current_step="화면해설 음성 합성 중",
    )

    combine_started_at = time.monotonic()

    try:
        tts = importlib.import_module("pipeline.tts")
        tts_result = tts.run_tts(job_id)

        synthesizer = importlib.import_module("pipeline.synthesizer")
        synthesis_result = synthesizer.run_synthesis(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            combine_status="FAILED",
            combine_error=str(exc),
            current_step="최종 영상 합성 실패",
        )
        return

    job_store.update(
        job_id,
        combine_status="COMPLETED",
        combine_result={**tts_result, **synthesis_result},
        combine_seconds=round(time.monotonic() - combine_started_at, 2),
        current_step="처리 완료",
    )
