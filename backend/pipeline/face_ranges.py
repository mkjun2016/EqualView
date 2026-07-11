from __future__ import annotations

from typing import Any


def build_non_speech_time_ranges(
    segments: list[dict[str, Any]],
    video_duration: float,
) -> list[dict[str, float]]:
    ranges: list[dict[str, float]] = []

    for segment in segments:
        if segment.get("type") != "non_speech":
            continue

        start = max(0.0, float(segment["start"]))
        end = min(float(video_duration), float(segment["end"]))

        if end <= start:
            continue

        ranges.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
            }
        )

    return merge_time_ranges(ranges)


def merge_time_ranges(
    ranges: list[dict[str, float]],
) -> list[dict[str, float]]:
    if not ranges:
        return []

    sorted_ranges = sorted(ranges, key=lambda item: item["start"])
    merged = [dict(sorted_ranges[0])]

    for current in sorted_ranges[1:]:
        previous = merged[-1]

        if current["start"] <= previous["end"] + 0.001:
            previous["end"] = round(max(previous["end"], current["end"]), 3)
            continue

        merged.append(dict(current))

    return merged


def build_sample_timestamps_in_ranges(
    time_ranges: list[dict[str, float]],
    interval: float,
) -> list[float]:
    if not time_ranges or interval <= 0:
        return []

    timestamps: list[float] = []

    for time_range in time_ranges:
        start = float(time_range["start"])
        end = float(time_range["end"])

        if end <= start:
            continue

        current = start
        while current < end - 0.001:
            timestamps.append(round(current, 3))
            current += interval

    return timestamps
