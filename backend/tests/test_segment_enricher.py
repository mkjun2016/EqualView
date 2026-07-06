from pathlib import Path

import pytest

from pipeline.segment_enricher import build_segments_enriched, save_segments_enriched
from utils.json_io import read_json

JOB_ID = "abc123"

MOCK_RAW_SEGMENTS = [
    {
        "start": 0.0,
        "end": 2.0,
        "type": "non_speech",
        "text": "",
    },
    {
        "start": 2.0,
        "end": 5.0,
        "type": "speech",
        "text": "Do you have cappuccino for Joey?",
    },
    {
        "start": 5.0,
        "end": 9.5,
        "type": "non_speech",
        "text": "",
    },
    {
        "start": 9.5,
        "end": 12.0,
        "type": "speech",
        "text": "Sure, one moment.",
    },
]

VIDEO_METADATA = {
    "duration": 12.0,
    "fps": 24.0,
    "width": 1920,
    "height": 1080,
}


@pytest.fixture
def enriched():
    return build_segments_enriched(
        job_id=JOB_ID,
        raw_segments=MOCK_RAW_SEGMENTS,
        video_path=Path("input.mp4"),
        video_metadata=VIDEO_METADATA,
        language="ko",
    )


def test_build_segments_enriched_basic(enriched):
    segments = enriched["segments"]
    assert len(segments) == 4

    assert segments[0]["segment_id"] == "seg_0001"
    assert segments[1]["segment_id"] == "seg_0002"
    assert segments[2]["segment_id"] == "seg_0003"
    assert segments[3]["segment_id"] == "seg_0004"

    assert segments[0]["duration"] == 2.0
    assert segments[1]["duration"] == 3.0
    assert segments[2]["duration"] == 4.5

    assert segments[0]["narration_candidate"] is False
    assert segments[2]["narration_candidate"] is True

    for segment in segments:
        assert segment["frames"] == []
        assert "faces" not in segment
        assert "persons" not in segment
        assert "visible_person_in_segment" not in segment
        assert segment["scene_analysis"] is None
        assert segment["generated_narration"] is None
        assert segment["tts"] is None


def test_speech_context_for_seg_0003(enriched):
    context = enriched["segments"][2]["context"]
    assert context == {
        "previous_speech": "Do you have cappuccino for Joey?",
        "next_speech": "Sure, one moment.",
        "previous_segment_id": "seg_0002",
        "next_segment_id": "seg_0004",
    }


def test_speech_context_edges(enriched):
    first = enriched["segments"][0]["context"]
    last = enriched["segments"][-1]["context"]

    assert first["previous_speech"] is None
    assert first["previous_segment_id"] is None
    assert first["next_speech"] == "Do you have cappuccino for Joey?"
    assert first["next_segment_id"] == "seg_0002"

    assert last["previous_speech"] == "Do you have cappuccino for Joey?"
    assert last["previous_segment_id"] == "seg_0002"
    assert last["next_speech"] is None
    assert last["next_segment_id"] is None


def test_summary_counts(enriched):
    summary = enriched["summary"]
    assert summary["total_segments"] == 4
    assert summary["speech_segments"] == 2
    assert summary["non_speech_segments"] == 2
    assert summary["narration_candidate_count"] == 1


def test_save_segments_enriched(upload_dir, enriched):
    enriched["video"]["filename"] = "test.mp4"

    saved_path = save_segments_enriched(JOB_ID, enriched)
    assert saved_path.exists()

    parsed = read_json(saved_path)
    assert parsed["job_id"] == JOB_ID
    for key in ("video", "settings", "summary", "segments"):
        assert key in parsed

    raw_text = saved_path.read_text(encoding="utf-8")
    assert raw_text.startswith('{\n  "job_id"')
    assert "\\u" not in raw_text
