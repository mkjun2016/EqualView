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
        runner.run_analysis(job_id, job_store)
        _run_enrichment_if_ready(job_id)
        _run_narration_if_ready(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            status="FAILED",
            error=str(exc),
            current_step="?ㅽ뙣",
        )
        raise


@celery_app.task(name="tasks.process_face_job")
def process_face_job(job_id: str) -> None:
    started_at = time.monotonic()

    try:
        _ensure_backend_path()

        job_store.update(
            job_id,
            face_status="PROCESSING",
            face_progress=10,
            face_current_step="?쇨뎬 遺꾩꽍 ?쒖옉",
            face_error=None,
        )

        face_runner = importlib.import_module("pipeline.face_runner")
        result = face_runner.run_face_analysis(job_id)

        job_store.update(
            job_id,
            face_status="COMPLETED",
            face_progress=100,
            face_current_step="?쇨뎬 遺꾩꽍 ?꾨즺",
            face_error=None,
            face_result=result,
            face_seconds=round(time.monotonic() - started_at, 2),
            face_sample_count=result.get("sample_count", 0),
        )
        _run_enrichment_if_ready(job_id)
        _run_narration_if_ready(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            face_status="FAILED",
            face_error=str(exc),
            face_current_step="?쇨뎬 遺꾩꽍 ?ㅽ뙣",
        )
        raise


@celery_app.task(name="tasks.process_transition_job")
def process_transition_job(job_id: str) -> None:
    started_at = time.monotonic()

    try:
        _ensure_backend_path()
        job_store.update(
            job_id,
            transition_status="PROCESSING",
            transition_error=None,
        )

        transition_runner = importlib.import_module("pipeline.scene_transition")
        result = transition_runner.run_scene_transition_analysis(job_id)

        job_store.update(
            job_id,
            transition_status="COMPLETED",
            transition_error=None,
            transition_result=result,
            transition_seconds=round(time.monotonic() - started_at, 2),
        )
        _run_narration_if_ready(job_id)
        _run_combine_if_ready(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            transition_status="FAILED",
            transition_error=str(exc),
        )
        raise


def _run_enrichment_if_ready(job_id: str) -> None:
    if not job_store.try_begin_enrichment(job_id):
        return

    try:
        segment_enricher = importlib.import_module("pipeline.segment_enricher")
        segment_enricher.finalize_segments_enriched(job_id)
    except Exception as exc:
        job_store.update(
            job_id,
            enrichment_status="FAILED",
            enrichment_error=str(exc),
        )
        return

    job_store.update(
        job_id,
        enrichment_status="COMPLETED",
        enrichment_error=None,
    )


def _run_narration_if_ready(job_id: str) -> None:
    if not job_store.try_begin_narration(job_id):
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
            current_step="?붾㈃?댁꽕 ?앹꽦 ?ㅽ뙣",
        )
        return

    narration_status = narrator.resolve_narration_status(narration_result)
    narration_error = None

    if narration_status == "FAILED":
        narration_error = (
            f"Gemini narration failed for all "
            f"{narration_result.get('narration_job_count', 0)} segments."
        )
    elif narration_status == "PARTIAL":
        narration_error = (
            f"Gemini narration failed for "
            f"{narration_result.get('failed_segment_count', 0)} of "
            f"{narration_result.get('narration_job_count', 0)} segments."
        )

    job_store.update(
        job_id,
        narration_status=narration_status,
        narration_result=narration_result,
        narration_error=narration_error,
        narration_seconds=round(time.monotonic() - narration_started_at, 2),
        current_step="화면해설 생성 완료",
    )

    _run_combine_if_ready(job_id)


def _run_combine_if_ready(job_id: str) -> None:
    if not job_store.try_begin_combine(job_id):
        return

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
            current_step="理쒖쥌 ?곸긽 ?⑹꽦 ?ㅽ뙣",
        )
        return

    job_store.update(
        job_id,
        combine_status="COMPLETED",
        combine_result={**tts_result, **synthesis_result},
        combine_seconds=round(time.monotonic() - combine_started_at, 2),
        current_step="泥섎━ ?꾨즺",
    )
