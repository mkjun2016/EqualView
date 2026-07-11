from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_MODEL


NARRATION_ATEMPO = 1.1

_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment_id": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["keep", "replace", "skip"],
                    },
                    "replacement_text": {"type": "string"},
                },
                "required": ["segment_id", "action", "replacement_text"],
            },
        }
    },
    "required": ["decisions"],
}


def find_collisions(
    enriched: dict[str, Any],
    transitions: dict[str, Any],
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    transition_items = transitions.get("scenes", [])

    for segment in enriched.get("segments", []):
        audio_duration = float(segment.get("narration_audio_duration") or 0.0)
        if not segment.get("narration_audio") or audio_duration <= 0:
            continue

        narration_start = float(segment["start"])
        narration_end = narration_start + audio_duration / NARRATION_ATEMPO
        overlapping = [
            transition
            for transition in transition_items
            if narration_start
            <= float(transition["anchor_timestamp"])
            < narration_end
        ]
        if not overlapping:
            continue

        conflicts.append(
            {
                "segment_id": segment["segment_id"],
                "non_speech_window": {
                    "start": segment["start"],
                    "end": segment["end"],
                },
                "regular_narration": segment.get("narration", ""),
                "regular_tts_duration": audio_duration,
                "transitions": [
                    {
                        "anchor_timestamp": item["anchor_timestamp"],
                        "transition_segment_description": item[
                            "transition_segment_description"
                        ],
                        "location": item["location"],
                        "tts_duration": item.get("tts_duration"),
                    }
                    for item in overlapping
                ],
            }
        )

    return conflicts


def plan_collision_resolutions(
    enriched: dict[str, Any],
    transitions: dict[str, Any],
) -> dict[str, dict[str, str]]:
    conflicts = find_collisions(enriched, transitions)
    if not conflicts:
        return {}
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    enriched_timeline = [
        {
            "segment_id": segment.get("segment_id"),
            "start": segment.get("start"),
            "end": segment.get("end"),
            "audio_type": segment.get("audio_type"),
            "text": segment.get("text", ""),
            "narration": segment.get("narration", ""),
            "visible_person_ids": segment.get("visible_person_ids", []),
        }
        for segment in enriched.get("segments", [])
    ]
    transition_timeline = [
        {
            "anchor_timestamp": scene.get("anchor_timestamp"),
            "transition_segment_description": scene.get(
                "transition_segment_description", ""
            ),
            "location": scene.get("location", ""),
        }
        for scene in transitions.get("scenes", [])
    ]
    request_context = {
        "enriched_timeline": enriched_timeline,
        "transition_timeline": transition_timeline,
        "conflicts_requiring_decision": conflicts,
    }

    prompt = (
        "Resolve timing and semantic conflicts between regular Korean film "
        "audio descriptions and mandatory scene-transition descriptions. "
        "Transition narration has priority and its text must never be changed. "
        "For each conflicting regular narration choose: keep only when it adds "
        "essential non-duplicate visual information and fits before the anchor; "
        "replace with a shorter Korean sentence when essential complementary "
        "information can fit; or skip when it duplicates the transition or "
        "cannot fit safely. A replacement must preserve the main visible action "
        "or person, omit decorative detail, and contain only the final Korean "
        "sentence. Return JSON only.\n\n"
        + json.dumps(request_context, ensure_ascii=False, separators=(",", ":"))
    )
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=_DECISION_SCHEMA,
        ),
    )
    data = json.loads(response.text or '{"decisions": []}')
    return {
        str(item["segment_id"]): {
            "action": str(item["action"]),
            "replacement_text": str(item.get("replacement_text") or "").strip(),
        }
        for item in data.get("decisions", [])
    }
