from __future__ import annotations

import json
import time
from typing import Any

from google import genai
from google.genai import types

from config import (
    GEMINI_API_KEY,
    TRANSITION_FILE_POLL_SECONDS,
    TRANSITION_FILE_TIMEOUT_SECONDS,
    TRANSITION_GEMINI_MODEL,
)
from utils.ffmpeg_paths import MediaProbeInfo, probe_media_info
from utils.json_io import atomic_write_json
from utils.paths import JobPaths


_TRANSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "anchor_timestamp": {"type": "number"},
                    "transition_segment_description": {"type": "string"},
                    "location": {"type": "string"},
                },
                "required": [
                    "anchor_timestamp",
                    "transition_segment_description",
                    "location",
                ],
            },
        }
    },
    "required": ["scenes"],
}


_PROMPT = """
You are analyzing an entire chronological video. Divide it into a small number
of meaningful sections based primarily on changes in physical location or
environment, such as a restaurant, hallway, street, office, forest, house,
or vehicle. Since the provided video may be science fiction, the setting could be 
an unknown planet or an unfamiliar location that is difficult to identify, like some sort of planet. 

Create a new scene when one or more of the following occurs:
- The physical location clearly changes.
- Characters move into a visually distinct connected space, such as leaving an
  office and entering a corridor.
- The time of day changes significantly.
- There is a clear temporal jump, even when the location is similar.
- The background structure or overall situation changes enough to indicate a
  genuinely new environment.

Do not create a new scene only because of:
- A camera angle change, close-up, wide shot, or reverse shot.
- A cut between characters in the same conversation and same location.
- Small camera movement, temporary occlusion, or minor lighting variation.
- A character entering or leaving while the location remains unchanged.
- A change in action within the same physical environment.

Prefer stable, broad location sections over detailed shot-by-shot divisions.
Pay attention to short scenes: report a short scene when it genuinely uses a
different physical environment.

For `transition_segment_description`, write a concise, 
movie-like description that introduces the opening of the new segment.

Begin with the visible people. Describe:
- how many people are present,
- their noticeable appearance or clothing,
- where they are positioned,
- and what they are doing.

Then describe the surrounding environment. Include, when visibly relevant:
- the spatial layout,
- prominent objects,
- lighting,
- weather,
- atmosphere,
- and other visible on-screen details.

Be visually specific rather than generic. 
If the mood or atmosphere of the scene can be reasonably inferred from what is shown, include it as well.
When visually supported, state which previous setting the video leaves and which new setting it enters.
Do not invent details or make random guesses when the scene is unclear. 
Do not identify characters by name or infer motives, emotions, relationships, occupations, or events that are not clearly shown.

Write both transition_segment_description and location in Korean. The
transition_segment_description must always be a natural Korean narration that
can be read aloud directly without translation or rewriting.

For each detected scene return its anchor_timestamp at the estimated first
visible moment of that scene, a short location label, and one visual
description. Return valid JSON only and exactly follow the provided schema.
""".strip()


def _format_duration(duration: float) -> str:
    total_milliseconds = max(0, round(duration * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds = remainder / 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"


def _build_video_context_prompt(media_info: MediaProbeInfo) -> str:
    metadata = media_info.metadata
    duration = float(media_info.duration)
    fps = metadata.get("fps")
    width = metadata.get("width")
    height = metadata.get("height")

    return f"""
Authoritative source-video metadata measured from the uploaded input:
- Exact playback duration: {duration:.3f} seconds
- Duration in HH:MM:SS.mmm: {_format_duration(duration)}
- Resolution: {width or "unknown"}x{height or "unknown"}
- Frame rate: {fps if fps is not None else "unknown"} fps
- Audio stream present: {"yes" if media_info.has_audio else "no"}

Timestamp rules:
- Interpret anchor_timestamp only as elapsed seconds from the very first frame.
- Return it as a JSON number in seconds, not as MM:SS, HH:MM:SS, a frame
  number, or a percentage.
- Every anchor_timestamp must be within the inclusive range
  0.000 through {duration:.3f}.
- The uploaded file ends at {duration:.3f} seconds. There is no visual content
  after that time; never extrapolate, wrap, or invent a timestamp beyond it.
- Keep scenes in chronological order. When a boundary is uncertain, give the
  closest estimate that is still within the stated range.
""".strip()


def _wait_until_active(client: genai.Client, uploaded_file: Any) -> Any:
    deadline = time.monotonic() + TRANSITION_FILE_TIMEOUT_SECONDS
    current = uploaded_file

    while True:
        state = getattr(current, "state", None)
        state_name = str(getattr(state, "name", state) or "").upper()

        if state_name == "ACTIVE":
            return current
        if state_name == "FAILED":
            raise RuntimeError("Gemini video file processing failed")
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for Gemini video processing")

        time.sleep(TRANSITION_FILE_POLL_SECONDS)
        current = client.files.get(name=current.name)


def _normalize_scenes(data: dict[str, Any]) -> list[dict[str, Any]]:
    scenes: list[dict[str, Any]] = []
    for item in data.get("scenes", []):
        anchor = max(
            0.0,
            float(item.get("anchor_timestamp", item.get("start_timestamp", 0))),
        )
        location = str(item["location"]).strip()
        description = str(
            item.get(
                "transition_segment_description",
                item.get("description", ""),
            )
        ).strip()
        if not location or not description:
            continue
        scenes.append(
            {
                "anchor_timestamp": round(anchor, 3),
                "transition_segment_description": description,
                "location": location,
            }
        )
    return sorted(scenes, key=lambda item: item["anchor_timestamp"])


def run_scene_transition_analysis(job_id: str) -> dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    paths = JobPaths(job_id)
    video_path = paths.find_input_video()
    media_info = probe_media_info(video_path)
    video_context_prompt = _build_video_context_prompt(media_info)
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded_file = None

    try:
        uploaded_file = client.files.upload(file=str(video_path))
        uploaded_file = _wait_until_active(client, uploaded_file)

        response = client.models.generate_content(
            model=TRANSITION_GEMINI_MODEL,
            contents=[uploaded_file, _PROMPT, video_context_prompt],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "Write all scene-analysis results in Korean. Keep every "
                    "JSON key exactly as specified in English, but write the "
                    "values of location and transition_segment_description "
                    "in Korean only. Do not use English sentences in those "
                    "values. Each transition_segment_description must be a "
                    "natural Korean audio-description sentence that can be "
                    "read directly by TTS."
                ),
                response_mime_type="application/json",
                response_schema=_TRANSITION_SCHEMA,
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW,
            ),
        )
        response_data = json.loads(response.text or '{"scenes": []}')
        output = {
            "scenes": _normalize_scenes(response_data),
        }
        atomic_write_json(paths.transition_segments_json, output)
        return {
            "model": TRANSITION_GEMINI_MODEL,
            "request_count": 1,
            "scene_count": len(output["scenes"]),
            "transition_segments_json": paths.transition_segments_json.name,
        }
    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass
