from pipeline.face_ranges import (
    build_narration_safe_time_ranges,
    build_sample_timestamps_in_ranges,
    merge_time_ranges,
)


def test_build_narration_safe_time_ranges_applies_padding():
    segments = [
        {"start": 5.0, "end": 10.0, "narration_safe": False},
        {"start": 12.0, "end": 18.0, "narration_safe": True},
        {"start": 20.0, "end": 26.0, "narration_safe": True},
    ]

    ranges = build_narration_safe_time_ranges(
        segments,
        video_duration=30.0,
        padding_seconds=0.5,
    )

    assert ranges == [
        {"start": 11.5, "end": 18.5},
        {"start": 19.5, "end": 26.5},
    ]


def test_build_narration_safe_time_ranges_clamps_to_video_duration():
    segments = [{"start": 28.0, "end": 32.0, "narration_safe": True}]

    ranges = build_narration_safe_time_ranges(
        segments,
        video_duration=30.0,
        padding_seconds=0.4,
    )

    assert ranges == [{"start": 27.6, "end": 30.0}]


def test_merge_time_ranges_merges_overlapping_ranges():
    merged = merge_time_ranges(
        [
            {"start": 1.0, "end": 3.0},
            {"start": 2.5, "end": 5.0},
            {"start": 7.0, "end": 8.0},
        ]
    )

    assert merged == [
        {"start": 1.0, "end": 5.0},
        {"start": 7.0, "end": 8.0},
    ]


def test_build_sample_timestamps_in_ranges_samples_each_window():
    timestamps = build_sample_timestamps_in_ranges(
        [
            {"start": 1.0, "end": 2.5},
            {"start": 5.0, "end": 6.0},
        ],
        interval=1.0,
    )

    assert timestamps == [1.0, 2.0, 5.0, 6.0]
