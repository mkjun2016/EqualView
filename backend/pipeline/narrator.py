# segments.json의 narration_safe(=대사 없는 3초 이상) 구간마다
# face_segments.json에서 해당 시간대의 annotated 프레임을 일부 골라
# Gemini에 보내고, 한국어 화면해설 문장을 받아 segments.json에 채워 넣는다.

from __future__ import annotations

import bisect
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from google import genai
from google.genai import types

from config import (
    FACE_RANGE_PADDING_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    NARRATION_FRAME_MAX_PX,
    NARRATION_FRAMES_PER_SEGMENT,
    NARRATION_JPEG_QUALITY,
    NARRATION_MAX_CONCURRENCY,
    NARRATION_MAX_RETRIES,
    NARRATION_REQUEST_STAGGER_SECONDS,
    NARRATION_RETRY_BASE_SECONDS,
    NARRATION_RETRY_MAX_SECONDS,
)

_RETRYABLE_GEMINI_MARKERS = (
    "503",
    "429",
    "UNAVAILABLE",
    "RESOURCE_EXHAUSTED",
    "HIGH DEMAND",
    "QUOTA",
)
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths

_client: genai.Client | None = None


@dataclass
class NarrationJob:
    segment: dict[str, Any]
    frame_paths: list[Path]
    prompt: str


def get_gemini_client() -> genai.Client:
    global _client

    if _client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=GEMINI_API_KEY)

    return _client


def _select_frames(
    sorted_samples: list[dict[str, Any]],
    start: float,
    end: float,
    count: int,
) -> list[dict[str, Any]]:
    """
    구간 [start, end] 안의 샘플 중 최대 count개를 시간상 고르게 분포되도록 고른다.
    sorted_samples는 timestamp 기준으로 정렬되어 있어야 한다.
    """
    if not sorted_samples or count <= 0:
        return []

    timestamps = [sample["timestamp"] for sample in sorted_samples]
    left = bisect.bisect_left(timestamps, start)
    right = bisect.bisect_right(timestamps, end)
    in_range = sorted_samples[left:right]

    if len(in_range) <= count:
        return in_range

    step = (len(in_range) - 1) / (count - 1)
    indices = sorted({round(i * step) for i in range(count)})

    return [in_range[i] for i in indices]


def _visible_person_ids(frames: list[dict[str, Any]]) -> list[str]:
    person_ids: set[str] = set()

    for frame in frames:
        person_ids.update(frame.get("visible_person_ids", []))

    return sorted(person_id for person_id in person_ids if person_id != "unknown")


def _dialogue_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in segments
        if segment.get("speech") and segment.get("text")
    ]


def _dialogue_context(
    dialogue_segments: list[dict[str, Any]],
    start: float,
    end: float,
) -> tuple[str, str]:
    """
    이 구간 이전까지 나온 대사 전체(prior)와, 이 구간 직후에 이어지는 대사(upcoming)를 반환한다.
    """
    prior = [segment for segment in dialogue_segments if segment["end"] <= start]
    upcoming = [segment for segment in dialogue_segments if segment["start"] >= end]

    prior_text = " ".join(segment["text"] for segment in prior)
    upcoming_text = upcoming[0]["text"] if upcoming else ""

    return prior_text, upcoming_text


def _build_prompt(
    start: float,
    end: float,
    person_ids: list[str],
    prior_dialogue: str,
    upcoming_dialogue: str,
) -> str:
    duration = round(end - start, 2)

    if person_ids:
        people_line = f"화면에 등장하는 인물 식별 라벨: {', '.join(person_ids)}."
    else:
        people_line = "화면에 식별된 인물이 없습니다."

    if prior_dialogue:
        prior_line = f"지금까지 영화에서 나온 대사 전체(시간 순):\n{prior_dialogue}"
    else:
        prior_line = "지금까지 나온 대사가 없습니다 (영화 시작 부분)."

    if upcoming_dialogue:
        upcoming_line = f"이 구간 직후 이어지는 대사: \"{upcoming_dialogue}\""
    else:
        upcoming_line = "이 구간 이후 더 이상 대사가 없습니다."

    return (
        "당신은 시각장애인을 위한 영화 화면해설 작가입니다. "
        f"아래 이미지들은 영화에서 대사가 없는 구간(길이 약 {duration}초)의 "
        "시간 순서대로 추출한 장면 사진입니다. "
        f"{people_line}\n\n"
        f"{prior_line}\n\n"
        f"{upcoming_line}\n\n"
        "위 대사 맥락을 참고해서 지금까지의 줄거리와 인물 관계에 맞고, "
        "곧 이어질 대사와도 자연스럽게 연결되는 화면해설을 작성하세요. "
        "이미지 속 인물의 동작, 표정, 배경, 분위기 변화를 바탕으로 "
        f"내레이터가 이 구간({duration}초) 안에 자연스럽게 읽을 수 있는 "
        "간결한 한국어 화면해설을 한 문단으로 작성하세요. "
        "person_001 같은 식별 라벨을 그대로 말하지 말고 "
        "'한 남자', '여성' 등 자연스러운 표현으로 바꿔서 설명하세요. "
        "대사 내용을 그대로 반복하지 말고, 화면에서 실제로 보이는 시각 정보만 설명하세요."
    )


def _read_frame_jpeg_bytes(path: Path) -> bytes:
    image = cv2.imread(str(path))

    if image is None:
        return path.read_bytes()

    height, width = image.shape[:2]
    longest = max(height, width)

    if longest > NARRATION_FRAME_MAX_PX:
        scale = NARRATION_FRAME_MAX_PX / longest
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        image = cv2.resize(
            image,
            (new_width, new_height),
            interpolation=cv2.INTER_AREA,
        )

    ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [cv2.IMWRITE_JPEG_QUALITY, NARRATION_JPEG_QUALITY],
    )

    if not ok:
        return path.read_bytes()

    return encoded.tobytes()


def _frame_part(path: Path) -> types.Part:
    return types.Part.from_bytes(
        data=_read_frame_jpeg_bytes(path),
        mime_type="image/jpeg",
    )


def _is_retryable_gemini_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return any(marker in message for marker in _RETRYABLE_GEMINI_MARKERS)


def _retry_delay_seconds(attempt: int) -> float:
    delay = NARRATION_RETRY_BASE_SECONDS * (2**attempt)
    delay += random.uniform(0, 1)
    return min(delay, NARRATION_RETRY_MAX_SECONDS)


def _frame_selection_range(
    segment: dict[str, Any],
    video_duration: float,
) -> tuple[float, float]:
    start = max(0.0, float(segment["start"]) - FACE_RANGE_PADDING_SECONDS)
    end = float(segment["end"]) + FACE_RANGE_PADDING_SECONDS

    if video_duration > 0:
        end = min(video_duration, end)

    return start, end


def _generate_narration(
    client: genai.Client,
    frame_paths: list[Path],
    prompt: str,
) -> str:
    contents: list[Any] = [prompt]

    for path in frame_paths:
        contents.append(_frame_part(path))

    last_exc: Exception | None = None

    for attempt in range(NARRATION_MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
            )
            return (response.text or "").strip()
        except Exception as exc:
            last_exc = exc
            if not _is_retryable_gemini_error(exc) or attempt >= NARRATION_MAX_RETRIES:
                raise

            time.sleep(_retry_delay_seconds(attempt))

    if last_exc is not None:
        raise last_exc

    raise RuntimeError("Gemini narration failed without an exception.")


def _prepare_narration_jobs(
    segments: list[dict[str, Any]],
    sorted_samples: list[dict[str, Any]],
    job_dir: Path,
    video_duration: float,
) -> list[NarrationJob]:
    dialogue_segments = _dialogue_segments(segments)
    jobs: list[NarrationJob] = []

    for segment in segments:
        if not segment.get("narration_safe"):
            continue

        frame_start, frame_end = _frame_selection_range(segment, video_duration)
        frames = _select_frames(
            sorted_samples,
            frame_start,
            frame_end,
            NARRATION_FRAMES_PER_SEGMENT,
        )

        segment["frames"] = [frame["path"] for frame in frames]

        if not frames:
            segment["narration"] = ""
            continue

        person_ids = _visible_person_ids(frames)
        prior_dialogue, upcoming_dialogue = _dialogue_context(
            dialogue_segments,
            segment["start"],
            segment["end"],
        )
        prompt = _build_prompt(
            segment["start"],
            segment["end"],
            person_ids,
            prior_dialogue,
            upcoming_dialogue,
        )
        frame_paths = [job_dir / frame["path"] for frame in frames]

        jobs.append(
            NarrationJob(
                segment=segment,
                frame_paths=frame_paths,
                prompt=prompt,
            )
        )

    return jobs


def _run_narration_job(
    client: genai.Client,
    job: NarrationJob,
    stagger_seconds: float = 0.0,
) -> tuple[NarrationJob, str | None, str | None]:
    if stagger_seconds > 0:
        time.sleep(stagger_seconds)

    try:
        narration = _generate_narration(client, job.frame_paths, job.prompt)
        return job, narration, None
    except Exception as exc:
        return job, None, str(exc)


def _execute_narration_jobs(
    client: genai.Client,
    jobs: list[NarrationJob],
) -> tuple[int, int]:
    if not jobs:
        return 0, 0

    worker_count = min(NARRATION_MAX_CONCURRENCY, len(jobs))
    narrated_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _run_narration_job,
                client,
                job,
                index * NARRATION_REQUEST_STAGGER_SECONDS,
            )
            for index, job in enumerate(jobs)
        ]

        for future in as_completed(futures):
            job, narration, error = future.result()

            if error is not None:
                job.segment["narration"] = ""
                job.segment["narration_error"] = error
                failed_count += 1
                continue

            job.segment["narration"] = narration
            job.segment.pop("narration_error", None)
            narrated_count += 1

    return narrated_count, failed_count


def run_narration(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    segments_data = read_json(paths.segments_json)
    face_data = read_json(paths.face_segments_json)

    samples = face_data.get("samples", [])
    segments = segments_data.get("segments", [])

    sorted_samples = sorted(samples, key=lambda sample: sample["timestamp"])
    video_duration = float(face_data.get("source", {}).get("duration") or 0.0)
    jobs = _prepare_narration_jobs(
        segments,
        sorted_samples,
        paths.job_dir,
        video_duration,
    )

    client = get_gemini_client()
    narrated_count, failed_count = _execute_narration_jobs(client, jobs)

    atomic_write_json(paths.segments_json, segments_data)

    return {
        "narration_job_count": len(jobs),
        "narrated_segment_count": narrated_count,
        "failed_segment_count": failed_count,
    }


def resolve_narration_status(result: dict[str, Any]) -> str:
    job_count = int(result.get("narration_job_count", 0))
    narrated_count = int(result.get("narrated_segment_count", 0))
    failed_count = int(result.get("failed_segment_count", 0))

    if job_count == 0:
        return "COMPLETED"

    if failed_count == 0:
        return "COMPLETED"

    if narrated_count == 0:
        return "FAILED"

    return "PARTIAL"
