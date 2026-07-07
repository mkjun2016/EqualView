import time
from dataclasses import dataclass
from pathlib import Path

from services.job_store import JobStore
from pipeline.audio_extractor import (
    create_silent_wav,
    extract_audio_from_video,
)
from pipeline.segment_enricher import (
    build_segments_enriched,
    save_segments_enriched,
    try_merge_face_segments_for_job,
)
from pipeline.transcriber import build_segments_from_words, transcribe_audio
from utils.ffmpeg_paths import MediaProbeInfo, probe_media_info
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


@dataclass(frozen=True)
class AnalysisContext:
    video_path: Path
    media_info: MediaProbeInfo

    @classmethod
    def from_video(cls, video_path: Path):
        return cls(
            video_path=video_path,
            media_info=probe_media_info(video_path),
        )

    @property
    def duration(self) -> float:
        return self.media_info.duration

    @property
    def has_audio(self) -> bool:
        return self.media_info.has_audio

    @property
    def video_metadata(self):
        return self.media_info.metadata


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

    context = AnalysisContext.from_video(video_path)

    store.update(
        job_id,
        progress=30,
        current_step="오디오 추출 중",
    )

    if context.has_audio:
        extract_audio_from_video(video_path, audio_path)
    else:
        create_silent_wav(audio_path, context.duration)

    store.update(
        job_id,
        progress=60,
        current_step="Whisper 전사 중",
    )

    if context.has_audio:
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

    segments = build_segments_from_words(
        words,
        context.duration,
        context.has_audio,
    )

    atomic_write_json(segments_path, {"segments": segments})

    enriched = build_segments_enriched(
        job_id=job_id,
        raw_segments=segments,
        video_path=video_path,
        video_metadata=context.video_metadata,
        language=language,
    )
    save_segments_enriched(job_id, enriched)
    try_merge_face_segments_for_job(job_id)

    store.update(
        job_id,
        status="COMPLETED",
        progress=100,
        current_step="분석 완료",
        error=None,
        dialogue_seconds=round(time.monotonic() - started_at, 2),
    )

    return {
        "duration": round(context.duration, 2),
        "has_audio": context.has_audio,
        "segment_count": len(segments),
        "narration_candidate_count": enriched["summary"]["narration_candidate_count"],
    }
