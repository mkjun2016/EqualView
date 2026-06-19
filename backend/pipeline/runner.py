from services.job_store import JobStore
from pipeline.audio_extractor import (
    create_silent_wav,
    extract_audio_from_video,
    get_media_duration,
    has_audio_stream,
)
from pipeline.transcriber import build_segments_from_words, transcribe_audio
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


def run_analysis(job_id: str, store: JobStore) -> dict:
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
    else:
        words = "audio doesn't exist"

    store.update(
        job_id,
        progress=80,
        current_step="침묵 구간 분석 중",
    )

    segments = build_segments_from_words(words, video_duration, audio_exists)

    atomic_write_json(segments_path, {"segments": segments})

    store.update(
        job_id,
        status="COMPLETED",
        progress=100,
        current_step="분석 완료",
        error=None,
    )

    return {
        "duration": round(video_duration, 2),
        "has_audio": audio_exists,
        "segment_count": len(segments),
    }
