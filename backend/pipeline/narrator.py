# segments.json의 narration_safe(=대사 없는 3초 이상) 구간마다
# face_segments.json에서 해당 시간대의 annotated 프레임을 일부 골라
# Gemini에 보내고, 한국어 화면해설 문장을 받아 segments.json에 채워 넣는다.

from __future__ import annotations

import bisect
import json
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
class NarrationFrame:
    role: str
    segment_id: str
    timestamp: float
    path: Path


@dataclass
class NarrationJob:
    segment: dict[str, Any]
    frame_paths: list[Path]
    prompt: str
    frames: list[NarrationFrame] | None = None


NARRATION_CONTEXT_FRAME_COUNT = 3


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
        if (
            segment.get("speech")
            or segment.get("audio_type") == "speech"
        )
        and segment.get("text")
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


def _build_prompt(
    person_ids: list[str],
    prior_dialogue: str,
    upcoming_dialogue: str,
) -> str:
    people_line = (
        f"Visible tracked people in the frames: {', '.join(person_ids)}."
        if person_ids
        else "No tracked person is visible in the supplied frames."
    )
    prior_line = (
        f"Dialogue before this silent interval:\n{prior_dialogue}"
        if prior_dialogue
        else "There is no dialogue before this interval."
    )
    upcoming_line = (
        f'Dialogue immediately after this interval: "{upcoming_dialogue}"'
        if upcoming_dialogue
        else "There is no dialogue after this interval."
    )

    return (
        "You are writing Korean audio description for visually impaired film "
        "viewers. The supplied images are chronological video frames grouped "
        "as previous_context, target_silent_segment, and next_context. A group "
        "may contain fewer than three frames or no frames; this is normal. Treat all "
        "available frames as samples from one continuous video sequence.\n\n"
        "Use previous_context and next_context only to understand the immediate "
        "continuity surrounding target_silent_segment. Determine actions primarily "
        "from the target frames. You may describe a simple continuous action only "
        "when multiple target frames clearly show its progression. A difference "
        "between sampled frames may be caused by a cut, camera movement, or "
        "occlusion; do not automatically turn that difference into an action. When "
        "the action is uncertain, describe the visible state in the target frames "
        "instead.\n\n"
        "Make only minimal, high-confidence inferences directly supported by the "
        "visible sequence. Choose the simplest explanation that accounts for the "
        "observed change. If an interpretation is not clearly and confidently "
        "supported by the visible sequence, do not infer or mention it. Describe "
        "only what is directly visible, such as a person's posture, clearly "
        "observable movement, or a stable visible change between target frames. "
        "Do not infer a specific "
        "event, place, relationship, motive, emotion, or unseen action from weak "
        "or decorative clues. For example, the "
        "presence of flowers does not justify describing the location as a "
        "wedding venue.\n\n"
        "Use spatial and cinematic composition as supporting evidence, not as proof "
        "of a person's exact physical position or movement. Mention direction, "
        "orientation, or a precise location such as an entrance, the end of a "
        "passage, or behind another person only when stable landmarks and multiple "
        "target frames clearly support it. A foreground view of someone's back or "
        "a change in camera angle does not mean that the person turned around. When "
        "the spatial relationship is unclear, use a coarse description or omit it.\n\n"
        "Describe the visible details of the scene, especially the background, "
        "surrounding environment, spatial layout, prominent objects, lighting, "
        "weather, colors, and overall visual atmosphere. Provide enough concrete "
        "detail to help the viewer understand and picture the setting, but do not "
        "invent unseen details or unsupported meanings.\n\n"
        "Do not narrate an event shown only in previous_context or next_context "
        "as though it occurred during target_silent_segment. Use those frames to "
        "understand continuity without moving an event into the wrong interval. "
        "Exactly one target segment is supplied in this request. Before writing "
        "its regular audio description, inspect the transition descriptions in "
        "the target segment's events and in its before_segment and after_segment "
        "transition context. Do not repeat or paraphrase visual information already "
        "covered by any of those transition descriptions. If no distinct supported "
        "detail remains, write a shorter description or return an empty narration. "
        "Never invent information merely to avoid overlap. "
        "The final narration must describe exactly one segment. \n\n"
        "When earlier segment requests and Korean audio descriptions are available "
        "in this chat, use them as continuity memory. For the first segment, where "
        "no earlier narration exists, rely only on the supplied frame groups, "
        "timeline, and dialogue context. "
        "Use earlier descriptions to keep references to people, clothing, locations, "
        "and objects consistent. Continue an earlier action only when the current "
        "target frames independently confirm that it is still happening. Avoid "
        "repeating details already described unless they are necessary to understand "
        "the current segment, but prefer an accurate brief repetition over an "
        "unsupported new action or position. Treat earlier narrations "
        "only as past context, never as proof that the same event occurs in the "
        "current target segment. The current frames are always the primary evidence; "
        "if earlier narration conflicts with them, follow the current frames.\n\n"
        f"{people_line}\n\n"
        f"{prior_line}\n\n"
        f"{upcoming_line}\n\n"
        "Write a natural Korean audio description focused on the most reliable "
        "visible information: clearly shown actions, people, expressions, "
        "background, environment, and visual atmosphere. If no action is clearly "
        "shown, a brief description of the visible posture, people, or setting is "
        "sufficient. Avoid dramatic motion adverbs unless the speed or force is "
        "unmistakably visible across the target frames. "
        "Connect naturally with nearby dialogue without repeating it. Never "
        "output tracking identifiers such as person_001; refer to people naturally "
        "by visible traits such as a man, a woman, or a person in specific clothing. "
        "Do not infer names, relationships, motives, or facts that are not visible. "
        "Output only the Korean narration text with no labels or explanation."
    )


def _prepare_narration_jobs(
    segments: list[dict[str, Any]],
    sorted_samples: list[dict[str, Any]],
    job_dir: Path,
    video_duration: float,
) -> list[NarrationJob]:
    dialogue_segments = _dialogue_segments(segments)
    jobs: list[NarrationJob] = []

    timestamps = [float(sample["timestamp"]) for sample in sorted_samples]

    for segment_index, segment in enumerate(segments):
        if not (
            segment.get("narration_safe")
            or segment.get("narration_candidate")
        ):
            continue

        start = float(segment["start"])
        end = float(segment["end"])
        left = bisect.bisect_left(timestamps, start)
        if segment_index == len(segments) - 1:
            right = bisect.bisect_right(timestamps, end)
        else:
            right = bisect.bisect_left(timestamps, end)

        target_candidates = sorted_samples[left:right]
        target_frames = _select_frames(
            target_candidates,
            start,
            end,
            NARRATION_FRAMES_PER_SEGMENT,
        )
        previous_frames = sorted_samples[
            max(0, left - NARRATION_CONTEXT_FRAME_COUNT):left
        ]
        next_frames = sorted_samples[
            right:right + NARRATION_CONTEXT_FRAME_COUNT
        ]

        if not target_frames:
            segment["narration_frame_paths"] = []
            segment["narration_frame_groups"] = {
                "previous_context": [],
                "target_silent_segment": [],
                "next_context": [],
            }
            segment["narration"] = ""
            continue

        grouped_samples = {
            "previous_context": previous_frames,
            "target_silent_segment": target_frames,
            "next_context": next_frames,
        }
        narration_frames: list[NarrationFrame] = []
        valid_samples: dict[str, list[dict[str, Any]]] = {
            role: [] for role in grouped_samples
        }

        for role, frames in grouped_samples.items():
            for frame in frames:
                frame_path = Path(frame["path"])
                if frame_path.parts and frame_path.parts[0] == "uploads":
                    frame_path = job_dir.parent.parent / frame_path
                else:
                    frame_path = job_dir / frame_path

                if not frame_path.exists():
                    continue

                valid_samples[role].append(frame)
                narration_frames.append(
                    NarrationFrame(
                        role=role,
                        segment_id=str(frame.get("_segment_id") or "unknown"),
                        timestamp=float(frame["timestamp"]),
                        path=frame_path,
                    )
                )

        if not valid_samples["target_silent_segment"]:
            segment["narration_frame_paths"] = []
            segment["narration_frame_groups"] = {
                role: [] for role in grouped_samples
            }
            segment["narration"] = ""
            continue

        segment["narration_frame_paths"] = [
            str(frame["path"])
            for role in grouped_samples
            for frame in valid_samples[role]
        ]
        segment["narration_frame_groups"] = {
            role: [str(frame["path"]) for frame in valid_samples[role]]
            for role in grouped_samples
        }

        person_ids = _visible_person_ids(
            valid_samples["target_silent_segment"]
        )
        prior_dialogue, upcoming_dialogue = _dialogue_context(
            dialogue_segments,
            segment["start"],
            segment["end"],
        )
        prompt = _build_prompt(
            person_ids,
            prior_dialogue,
            upcoming_dialogue,
        )

        jobs.append(
            NarrationJob(
                segment=segment,
                frame_paths=[frame.path for frame in narration_frames],
                prompt=prompt,
                frames=narration_frames,
            )
        )

    return jobs


def _split_contiguous_chunks(
    jobs: list[NarrationJob],
    count: int,
) -> list[list[NarrationJob]]:
    chunk_count = min(max(1, count), len(jobs))
    base_size, remainder = divmod(len(jobs), chunk_count)
    chunks: list[list[NarrationJob]] = []
    offset = 0

    for index in range(chunk_count):
        size = base_size + (1 if index < remainder else 0)
        chunks.append(jobs[offset : offset + size])
        offset += size

    return chunks


def _send_chat_narration(chat: Any, job: NarrationJob) -> str:
    message: list[Any] = [job.prompt]
    if job.frames is None:
        message.extend(_frame_part(path) for path in job.frame_paths)
    else:
        roles = (
            "previous_context",
            "target_silent_segment",
            "next_context",
        )
        counts = {
            role: sum(1 for frame in job.frames if frame.role == role)
            for role in roles
        }
        message.append(
            "FRAME_GROUP_SUMMARY\n"
            + "\n".join(f"{role}: {counts[role]} frames" for role in roles)
        )

        for role in roles:
            grouped_frames = [frame for frame in job.frames if frame.role == role]
            message.append(f"=== {role.upper()} ===")
            if not grouped_frames:
                message.append("No frames are available for this group.")
                continue

            for frame in grouped_frames:
                message.append(
                    "FRAME_METADATA\n"
                    f"role: {frame.role}\n"
                    f"segment_id: {frame.segment_id}\n"
                    f"timestamp: {frame.timestamp}"
                )
                message.append(_frame_part(frame.path))
    last_error: Exception | None = None

    for attempt in range(NARRATION_MAX_RETRIES + 1):
        try:
            response = chat.send_message(message)
            narration = (response.text or "").strip()
            return narration
        except Exception as exc:
            last_error = exc
            if (
                not _is_retryable_gemini_error(exc)
                or attempt >= NARRATION_MAX_RETRIES
            ):
                raise
            time.sleep(_retry_delay_seconds(attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError("Gemini chat narration failed without an exception")


def _run_chat_chunk(
    chunk_index: int,
    jobs: list[NarrationJob],
    timeline_context: str,
) -> tuple[int, int]:
    if chunk_index > 0:
        time.sleep(chunk_index * NARRATION_REQUEST_STAGGER_SECONDS)

    client = genai.Client(api_key=GEMINI_API_KEY)
    chat = client.chats.create(model=GEMINI_MODEL)
    context_message = (
        "You will create Korean film audio descriptions for one chronological "
        "section of this video. The shared context below contains one unified "
        "timeline. Each timeline segment contains dialogue, timing, tracked people, "
        "and any detected scene-change events with their reserved transition "
        "descriptions. An empty before_segment or after_segment array means that "
        "the corresponding adjacent segment has no transition description. Read "
        "the timeline once and retain its "
        "chronological and visual context throughout this chat. Each request contains "
        "exactly one target segment. Before writing its regular audio description, "
        "inspect all transition descriptions attached to the previous segment, the "
        "target segment, and the next segment. Do not repeat or paraphrase visual "
        "information already covered by any of those transition descriptions. "
        "If no distinct supported detail remains, write a shorter description or return "
        "an empty narration. Accuracy takes priority "
        "over novelty: never invent a new action, pose, direction, or position merely "
        "to make the regular narration different. When no distinct new action is "
        "clearly visible, use a stable target-frame detail or a brief static "
        "description, even if it overlaps slightly with earlier context. Previous "
        "and later timeline events are context "
        "only; never move their actions, outcomes, settings, or visual details into "
        "the current target interval. "
        "Do not generate narration yet. Reply only with CONTEXT_READY.\n\n"
        f"{timeline_context}"
    )
    chat.send_message(context_message)

    narrated_count = 0
    failed_count = 0
    for job in jobs:
        try:
            narration = _send_chat_narration(chat, job)
            job.segment["narration"] = narration
            job.segment.pop("narration_error", None)
            narrated_count += 1
        except Exception as exc:
            job.segment["narration"] = ""
            job.segment["narration_error"] = str(exc)
            failed_count += 1

    return narrated_count, failed_count


def _build_unified_timeline(
    segments: list[dict[str, Any]],
    scenes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    timeline = [
        {
            "segment_id": segment.get("segment_id"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "duration": segment.get("duration"),
            "audio_type": segment.get("audio_type"),
            "dialogue": segment.get("text", ""),
            "narration_safe": bool(segment.get("narration_safe")),
            "context": segment.get("context", {}),
            "visible_person_ids": segment.get("persons", {}).get(
                "visible_person_ids", []
            ),
            "events": [],
        }
        for segment in sorted(
            segments,
            key=lambda item: float(item.get("start") or 0.0),
        )
    ]
    if not timeline:
        return timeline

    starts = [float(segment.get("start") or 0.0) for segment in timeline]
    for scene in sorted(
        scenes,
        key=lambda item: float(item.get("anchor_timestamp") or 0.0),
    ):
        anchor = float(scene.get("anchor_timestamp") or 0.0)
        segment_index = bisect.bisect_right(starts, anchor) - 1

        if segment_index < 0:
            segment_index = 0
        elif anchor >= float(timeline[segment_index].get("end") or 0.0):
            next_index = segment_index + 1
            if next_index < len(timeline):
                segment_index = next_index

        timeline[segment_index]["events"].append(
            {
                "type": "scene_transition",
                "timestamp": anchor,
                "location": scene.get("location", ""),
                "description_hint": scene.get(
                    "transition_segment_description", ""
                ),
            }
        )

    for segment_index, segment in enumerate(timeline):
        if not segment["narration_safe"]:
            continue

        before_events = (
            timeline[segment_index - 1]["events"]
            if segment_index > 0
            else []
        )
        after_events = (
            timeline[segment_index + 1]["events"]
            if segment_index + 1 < len(timeline)
            else []
        )
        segment["transition_context"] = {
            "before_segment": [
                event["description_hint"]
                for event in before_events
                if event.get("description_hint")
            ],
            "after_segment": [
                event["description_hint"]
                for event in after_events
                if event.get("description_hint")
            ],
        }

    return timeline


def _merge_timeline_into_enriched_segments(
    segments: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
) -> None:
    timeline_by_segment_id = {
        item.get("segment_id"): item
        for item in timeline
        if item.get("segment_id")
    }

    for segment in segments:
        timeline_segment = timeline_by_segment_id.get(segment.get("segment_id"))
        if timeline_segment is None:
            segment["events"] = []
            segment.pop("transition_context", None)
            continue

        segment["events"] = timeline_segment.get("events", [])
        if "transition_context" in timeline_segment:
            segment["transition_context"] = timeline_segment[
                "transition_context"
            ]
        else:
            segment.pop("transition_context", None)


def _execute_narration_jobs(
    jobs: list[NarrationJob],
    segments_data: dict[str, Any],
    transition_data: dict[str, Any],
) -> tuple[int, int]:
    timeline = _build_unified_timeline(
        segments_data.get("segments", []),
        transition_data.get("scenes", []),
    )
    _merge_timeline_into_enriched_segments(
        segments_data.get("segments", []),
        timeline,
    )

    if not jobs:
        return 0, 0

    chunks = _split_contiguous_chunks(jobs, NARRATION_MAX_CONCURRENCY)
    request_context = {
        "timeline": timeline
    }
    timeline_context = json.dumps(
        request_context,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    narrated_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=len(chunks)) as executor:
        futures = [
            executor.submit(
                _run_chat_chunk,
                index,
                chunk,
                timeline_context,
            )
            for index, chunk in enumerate(chunks)
        ]

        for future in as_completed(futures):
            chunk_narrated, chunk_failed = future.result()
            narrated_count += chunk_narrated
            failed_count += chunk_failed

    return narrated_count, failed_count


def run_narration(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    segments_data = read_json(paths.enriched_segments_json)
    transition_data = read_json(paths.transition_segments_json)
    segments = segments_data.get("segments", [])

    samples_by_id: dict[str, dict[str, Any]] = {}
    for segment in segments:
        for frame in segment.get("frames", []):
            frame_id = frame.get("frame_id") or frame.get("path")
            if frame_id:
                samples_by_id[str(frame_id)] = {
                    **frame,
                    "_segment_id": segment.get("segment_id"),
                }
    samples = list(samples_by_id.values())

    sorted_samples = sorted(samples, key=lambda sample: sample["timestamp"])
    video_duration = float(
        segments_data.get("video", {}).get("duration") or 0.0
    )
    jobs = _prepare_narration_jobs(
        segments,
        sorted_samples,
        paths.job_dir,
        video_duration,
    )

    narrated_count, failed_count = _execute_narration_jobs(
        jobs,
        segments_data,
        transition_data,
    )

    atomic_write_json(paths.enriched_segments_json, segments_data)

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
