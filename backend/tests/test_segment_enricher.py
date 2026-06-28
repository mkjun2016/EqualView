import json
from pathlib import Path

import pytest

from pipeline.segment_enricher import (
    build_segments_enriched,
    merge_face_frames_into_segments,
    save_segments_enriched,
)
from utils.json_io import read_json
from utils.paths import JobPaths

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
    assert len(segments) == 4, "expected 4 enriched segments from mock input"

    assert segments[0]["segment_id"] == "seg_0001"
    assert segments[1]["segment_id"] == "seg_0002"
    assert segments[2]["segment_id"] == "seg_0003"
    assert segments[3]["segment_id"] == "seg_0004"

    assert segments[0]["duration"] == 2.0, "duration should be round(end - start, 2)"
    assert segments[1]["duration"] == 3.0
    assert segments[2]["duration"] == 4.5

    assert segments[0]["narration_candidate"] is False, "2s non_speech is under 3s threshold"
    assert segments[2]["narration_candidate"] is True, "4.5s non_speech should be candidate"

    assert segments[1]["candidate_reason"] == "speech_segment"
    assert segments[0]["candidate_reason"] == "duration_under_3s"
    assert segments[2]["candidate_reason"] == "non_speech_duration_over_3s"

    for segment in segments:
        assert segment["scene_analysis"] is None
        assert segment["generated_narration"] is None
        assert segment["tts"] is None
        assert segment["persons"]["face_status"] == "pending"


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
    enriched["video"]["filename"] = "테스트.mp4"

    saved_path = save_segments_enriched(JOB_ID, enriched)
    assert saved_path.exists(), "segments_enriched.json should be written to job directory"

    parsed = read_json(saved_path)
    assert parsed["job_id"] == JOB_ID
    for key in ("video", "settings", "summary", "segments"):
        assert key in parsed, f"missing top-level key: {key}"

    raw_text = saved_path.read_text(encoding="utf-8")
    assert raw_text.startswith('{\n  "job_id"'), "JSON should use indent=2 formatting"
    assert "테스트.mp4" in raw_text, "ensure_ascii=False should preserve non-ASCII text"
    assert "\\u" not in raw_text, "ensure_ascii=False should not escape Korean characters"


MOCK_FACE_FRAMES = {
    "job_id": JOB_ID,
    "frame_interval": 0.5,
    "persons": [
        {
            "person_id": "person_001",
            "representative_face_path": f"uploads/{JOB_ID}/faces/person_001.jpg",
        }
    ],
    "frames": [
        {
            "frame_id": "frame_000010",
            "timestamp": 5.5,
            "raw_path": f"uploads/{JOB_ID}/frames/frame_000010.jpg",
            "annotated_path": f"uploads/{JOB_ID}/frames_annotated/frame_000010.jpg",
            "faces": [
                {
                    "person_id": "person_001",
                    "bbox": [420, 120, 560, 310],
                    "confidence": 0.94,
                    "label_color": "red",
                }
            ],
        },
        {
            "frame_id": "frame_000011",
            "timestamp": 6.0,
            "raw_path": f"uploads/{JOB_ID}/frames/frame_000011.jpg",
            "annotated_path": f"uploads/{JOB_ID}/frames_annotated/frame_000011.jpg",
            "faces": [],
        },
        {
            "frame_id": "frame_000012",
            "timestamp": 7.0,
            "raw_path": f"uploads/{JOB_ID}/frames/frame_000012.jpg",
            "annotated_path": f"uploads/{JOB_ID}/frames_annotated/frame_000012.jpg",
            "faces": [
                {
                    "person_id": "person_001",
                    "bbox": [430, 125, 570, 315],
                    "confidence": 0.91,
                    "label_color": "red",
                }
            ],
        },
    ],
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_merge_face_frames_into_segments(upload_dir, enriched):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    enriched_path = paths.segments_enriched_json
    face_path = paths.face_frames_json
    _write_json(enriched_path, enriched)
    _write_json(face_path, MOCK_FACE_FRAMES)

    merged = merge_face_frames_into_segments(
        enriched_path,
        face_path,
        max_frames_per_segment=5,
        save=False,
    )

    candidate = merged["segments"][2]
    non_candidate = merged["segments"][0]

    assert candidate["segment_id"] == "seg_0003"
    assert non_candidate["frames"] == [], "non-candidate segments should not receive frames"

    assert len(candidate["frames"]) == 3, "all in-range frames should be attached when under max"
    assert len(candidate["frames"]) <= 5, "frame count must respect max_frames_per_segment"

    for frame in candidate["frames"]:
        assert candidate["start"] <= frame["timestamp"] <= candidate["end"]
        assert frame["selected"] is True

    assert candidate["persons"]["visible_person_ids"] == ["person_001"]
    assert candidate["persons"]["main_person_id"] == "person_001"
    assert candidate["persons"]["face_status"] == "completed"


def test_merge_face_frames_respects_max_frames_per_segment(upload_dir, enriched):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    many_frames = {
        **MOCK_FACE_FRAMES,
        "frames": [
            {
                "frame_id": f"frame_{index:06d}",
                "timestamp": 5.0 + index * 0.2,
                "raw_path": f"uploads/{JOB_ID}/frames/frame_{index:06d}.jpg",
                "annotated_path": f"uploads/{JOB_ID}/frames_annotated/frame_{index:06d}.jpg",
                "faces": [{"person_id": "person_001", "bbox": [1, 2, 3, 4], "confidence": 0.9, "label_color": "red"}],
            }
            for index in range(10)
        ],
    }

    enriched_path = paths.segments_enriched_json
    face_path = paths.face_frames_json
    _write_json(enriched_path, enriched)
    _write_json(face_path, many_frames)

    merged = merge_face_frames_into_segments(
        enriched_path,
        face_path,
        max_frames_per_segment=3,
        save=False,
    )

    candidate = merged["segments"][2]
    assert len(candidate["frames"]) == 3, "merge should cap frames at max_frames_per_segment"


def test_merge_face_frames_missing_when_no_matching_frames(upload_dir, enriched):
    paths = JobPaths(JOB_ID)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    out_of_range_frames = {
        **MOCK_FACE_FRAMES,
        "frames": [
            {
                "frame_id": "frame_far",
                "timestamp": 20.0,
                "raw_path": f"uploads/{JOB_ID}/frames/frame_far.jpg",
                "annotated_path": f"uploads/{JOB_ID}/frames_annotated/frame_far.jpg",
                "faces": [{"person_id": "person_001", "bbox": [1, 2, 3, 4], "confidence": 0.9, "label_color": "red"}],
            }
        ],
    }

    enriched_path = paths.segments_enriched_json
    face_path = paths.face_frames_json
    _write_json(enriched_path, enriched)
    _write_json(face_path, out_of_range_frames)

    merged = merge_face_frames_into_segments(
        enriched_path,
        face_path,
        max_frames_per_segment=5,
        save=False,
    )

    candidate = merged["segments"][2]
    assert candidate["frames"] == []
    assert candidate["persons"]["face_status"] == "missing"
