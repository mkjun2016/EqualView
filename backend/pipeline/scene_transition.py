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
environment, such as a restaurant, hallway, street, office, bathroom, house,
or vehicle.

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

For transition_segment_description, introduce the opening of the new segment
like a concise description of a movie scene. In no more than two sentences,
describe the visible people first: how many are present, their noticeable
appearance or clothing, where they are positioned, and what they are doing.
Then describe the surrounding environment, including its spatial layout,
prominent objects, lighting, weather, or atmosphere when visibly relevant.
Be visually specific rather than generic, but describe only evidence visible
on screen. Do not identify characters by name or infer motives, emotions,
relationships, occupations, or events that are not clearly shown.

Do not add a scene-change phrase to the first scene description at the start of


the video. Every transition_segment_description after the first scene must begin
with the exact Korean phrase "장면이 바뀌고" and continue as one natural Korean
audio-description sentence. When visually supported, state which previous setting the video leaves
and which new setting it enters. 

Write both transition_segment_description and location in Korean. The
transition_segment_description must always be a natural Korean narration that
can be read aloud directly without translation or rewriting.

For each detected scene return its estimated start and end timestamps, a short
location label, one concise visual description, the reason it differs from the
previous scene, confidence from 0.0 to 1.0, and whether its start boundary needs
more precise frame analysis. Return valid JSON only.
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
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded_file = None

    try:
        uploaded_file = client.files.upload(file=str(video_path))
        uploaded_file = _wait_until_active(client, uploaded_file)

        response = client.models.generate_content(
            model=TRANSITION_GEMINI_MODEL,
            contents=[uploaded_file, _PROMPT],
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
