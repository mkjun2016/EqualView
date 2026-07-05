import time

from services.job_store import JobStore
from pipeline.audio_extractor import (
    create_silent_wav,
    extract_audio_from_video,
    get_media_duration,
    has_audio_stream,
)
from pipeline.segment_enricher import (
    build_segments_enriched,
    save_segments_enriched,
    try_merge_face_segments_for_job,
)
from pipeline.transcriber import build_segments_from_words, transcribe_audio
from pipeline.face_ranges import build_narration_safe_time_ranges
from config import FACE_RANGE_PADDING_SECONDS
from utils.ffmpeg_paths import get_video_metadata
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


def run_analysis(job_id: str, store: JobStore) -> dict:
    started_at = time.monotonic()

    paths = JobPaths(job_id)
    video_path = paths.find_input_video()
    audio_path = paths.audio_wav
    segments_path = paths.segments_json

    store.update(
        job_id,
        status="PROCESSING",
        progress=10,
        current_step="영상 분석 작업 시작",
    )

    video_duration = get_media_duration(video_path)
    audio_exists = has_audio_stream(video_path)

    store.update(
        job_id,
        progress=30,
        current_step="오디오 추출 중",
    )

    if audio_exists:
        extract_audio_from_video(video_path, audio_path)
    else:
        create_silent_wav(audio_path, video_duration)

    store.update(
        job_id,
        progress=60,
        current_step="Whisper 전사 중",
    )

    if audio_exists:
        script_result = transcribe_audio(audio_path)
        words = script_result["words"]
        language = script_result.get("language")
    else:
        words = "audio doesn't exist"
        language = None

    store.update(
        job_id,
        progress=80,
        current_step="침묵 구간 분석 중",
    )

    segments = build_segments_from_words(words, video_duration, audio_exists)

    atomic_write_json(segments_path, {"segments": segments})

    video_metadata = get_video_metadata(video_path)
    enriched = build_segments_enriched(
        job_id=job_id,
        raw_segments=segments,
        video_path=video_path,
        video_metadata=video_metadata,
        language=language,
    )
    save_segments_enriched(job_id, enriched)
    try_merge_face_segments_for_job(job_id)

    face_time_ranges = build_narration_safe_time_ranges(
        segments,
        video_duration,
        FACE_RANGE_PADDING_SECONDS,
    )

    store.update(
        job_id,
        status="COMPLETED",
        progress=100,
        current_step="분석 완료",
        error=None,
        dialogue_seconds=round(time.monotonic() - started_at, 2),
        face_analyzed_ranges=face_time_ranges,
    )

    return {
        "duration": round(video_duration, 2),
        "has_audio": audio_exists,
        "segment_count": len(segments),
        "narration_candidate_count": enriched["summary"]["narration_candidate_count"],
        "face_time_ranges": face_time_ranges,
    }
