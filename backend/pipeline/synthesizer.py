from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.ffmpeg_paths import get_ffmpeg_binary, probe_media_info, subprocess_run
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


NARRATION_ATEMPO = 1.1
REGULAR_NARRATION_OFFSET_SECONDS = 0.2
TRANSITION_SILENCE_SECONDS = 0.7


def _narrated_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in segments
        if segment.get("narration_audio")
        and float(segment.get("narration_audio_duration") or 0) > 0
    ]


def _source_duration(paths: JobPaths) -> float:
    """Use the shortest base stream so video and source audio stay aligned."""
    video_duration = float(probe_media_info(paths.find_input_video()).duration)
    audio_duration = float(probe_media_info(paths.audio_wav).duration)
    positive_durations = [
        duration for duration in (video_duration, audio_duration) if duration > 0
    ]
    if not positive_durations:
        raise RuntimeError("Could not determine source duration for synthesis.")
    return min(positive_durations)


def _valid_transitions(
    transition_data: dict[str, Any],
    source_duration: float,
) -> list[dict[str, Any]]:
    transitions = [
        item
        for item in transition_data.get("scenes", [])
        if item.get("tts_audio") and float(item.get("tts_duration") or 0) > 0
    ]

    latest_frame_anchor = max(0.0, source_duration - 0.04)
    valid: list[dict[str, Any]] = []
    for source_order, transition in enumerate(transitions):
        insertion_timestamp = float(
            transition.get("insertion_timestamp", transition["anchor_timestamp"])
        )
        valid.append(
            {
                **transition,
                "insertion_timestamp": min(
                    latest_frame_anchor,
                    max(0.0, insertion_timestamp),
                ),
                "_source_order": source_order,
                "_original_item": transition,
            }
        )
    return valid


def _build_insertion_events(
    segments: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    source_duration: float,
) -> list[dict[str, Any]]:
    latest_frame_anchor = max(0.0, source_duration - 0.04)
    events: list[dict[str, Any]] = []

    for source_order, segment in enumerate(segments):
        anchor = min(
            latest_frame_anchor,
            max(
                0.0,
                float(segment["start"]) + REGULAR_NARRATION_OFFSET_SECONDS,
            ),
        )
        spoken_duration = (
            float(segment["narration_audio_duration"]) / NARRATION_ATEMPO
        )
        events.append(
            {
                "kind": "regular",
                "source_timestamp": anchor,
                "priority": 1,
                "source_order": source_order,
                "spoken_duration": spoken_duration,
                "leading_silence": 0.0,
                "trailing_silence": 0.0,
                "inserted_duration": spoken_duration,
                "audio_path": segment["narration_audio"],
                "source_item": segment,
            }
        )

    for transition in transitions:
        anchor = float(transition["insertion_timestamp"])
        spoken_duration = float(transition["tts_duration"]) / NARRATION_ATEMPO
        inserted_duration = (
            spoken_duration + (TRANSITION_SILENCE_SECONDS * 2)
        )
        events.append(
            {
                "kind": "transition",
                "source_timestamp": anchor,
                "priority": 0,
                "source_order": int(transition["_source_order"]),
                "spoken_duration": spoken_duration,
                "leading_silence": TRANSITION_SILENCE_SECONDS,
                "trailing_silence": TRANSITION_SILENCE_SECONDS,
                "inserted_duration": inserted_duration,
                "audio_path": transition["tts_audio"],
                "source_item": transition["_original_item"],
            }
        )

    return sorted(
        events,
        key=lambda event: (
            event["source_timestamp"],
            event["priority"],
            event["source_order"],
        ),
    )


def _count_source_audio_chunks(
    events: list[dict[str, Any]],
    source_duration: float,
) -> int:
    count = 0
    previous_anchor = 0.0
    for event in events:
        anchor = float(event["source_timestamp"])
        if anchor > previous_anchor + 0.001:
            count += 1
        previous_anchor = anchor
    if previous_anchor < source_duration - 0.001:
        count += 1
    return count


def _write_empty_timeline(
    paths: JobPaths,
    source_duration: float,
) -> dict[str, Any]:
    timeline = {
        "source_duration": round(source_duration, 3),
        "output_duration": round(source_duration, 3),
        "total_inserted_duration": 0.0,
        "insertions": [],
    }
    atomic_write_json(paths.timeline_offsets_json, timeline)
    return timeline


def _append_source_audio_filters(
    filters: list[str],
    source_audio_chunks: int,
) -> None:
    base_audio = (
        "[1:a]asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo"
    )
    if source_audio_chunks == 1:
        filters.append(f"{base_audio}[sourcea0]")
        return

    split_outputs = "".join(
        f"[sourcea{index}]" for index in range(source_audio_chunks)
    )
    filters.append(
        f"{base_audio},asplit={source_audio_chunks}{split_outputs}"
    )


def _append_inserted_audio_filter(
    filters: list[str],
    event: dict[str, Any],
    input_index: int,
    output_label: str,
) -> None:
    inserted_duration = float(event["inserted_duration"])
    leading_silence = float(event["leading_silence"])
    delay_filter = (
        f"adelay={round(leading_silence * 1000)}:all=1,"
        if leading_silence > 0
        else ""
    )
    filters.append(
        f"[{input_index}:a]atempo={NARRATION_ATEMPO:.3f},"
        "asetpts=PTS-STARTPTS,"
        f"{delay_filter}apad,atrim=duration={inserted_duration:.3f},"
        "asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo"
        f"[{output_label}]"
    )


def _record_insertion(
    event: dict[str, Any],
    output_anchor: float,
    cumulative_offset: float,
) -> dict[str, Any]:
    source_item = event["source_item"]
    kind = str(event["kind"])
    insertion = {
        "kind": kind,
        "source_insertion_timestamp": round(
            float(event["source_timestamp"]),
            3,
        ),
        "output_insertion_timestamp": round(output_anchor, 3),
        "leading_silence": float(event["leading_silence"]),
        "spoken_duration": round(float(event["spoken_duration"]), 3),
        "trailing_silence": float(event["trailing_silence"]),
        "inserted_duration": round(float(event["inserted_duration"]), 3),
        "cumulative_offset_after": round(cumulative_offset, 3),
    }

    if kind == "transition":
        insertion.update(
            {
                "detected_anchor_timestamp": round(
                    float(source_item["anchor_timestamp"]),
                    3,
                ),
                "insertion_rule": source_item.get("insertion_rule"),
                "transition_segment_description": source_item[
                    "transition_segment_description"
                ],
                "location": source_item["location"],
            }
        )
    else:
        insertion.update(
            {
                "segment_id": source_item.get("segment_id"),
                "segment_start": source_item.get("start"),
                "segment_end": source_item.get("end"),
                "segment_start_offset_seconds": (
                    REGULAR_NARRATION_OFFSET_SECONDS
                ),
                "narration": source_item.get("narration", ""),
            }
        )

    source_item["output_insertion_timestamp"] = insertion[
        "output_insertion_timestamp"
    ]
    source_item["inserted_duration"] = insertion["inserted_duration"]
    source_item["cumulative_offset_after"] = insertion[
        "cumulative_offset_after"
    ]
    return insertion


def _synthesize(
    paths: JobPaths,
    segments: list[dict[str, Any]],
    transition_data: dict[str, Any],
) -> dict[str, Any]:
    """Insert regular and transition narration as serialized video stalls."""
    video_path = paths.find_input_video()
    source_duration = _source_duration(paths)
    transitions = _valid_transitions(transition_data, source_duration)
    events = _build_insertion_events(
        segments,
        transitions,
        source_duration,
    )

    command = [
        get_ffmpeg_binary(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(paths.audio_wav),
    ]
    for input_index, event in enumerate(events, start=2):
        event["input_index"] = input_index
        command += ["-i", str(paths.job_dir / event["audio_path"])]

    if not events:
        filters = [
            "[0:v]setpts=PTS-STARTPTS[vout]",
            "[1:a]asetpts=PTS-STARTPTS,aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]",
        ]
        command += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(paths.output_video),
        ]
        result = subprocess_run(command)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        return _write_empty_timeline(paths, source_duration)

    source_audio_chunks = _count_source_audio_chunks(events, source_duration)
    if source_audio_chunks <= 0:
        raise RuntimeError("Single-pass synthesis produced no source audio chunks.")

    filters: list[str] = []
    _append_source_audio_filters(filters, source_audio_chunks)

    concat_labels: list[str] = []
    previous_anchor = 0.0
    cumulative_offset = 0.0
    insertions: list[dict[str, Any]] = []
    pair_count = 0
    source_audio_index = 0

    for event in events:
        anchor = float(event["source_timestamp"])
        inserted_duration = round(float(event["inserted_duration"]), 3)

        if anchor > previous_anchor + 0.001:
            video_label = f"v{pair_count}"
            audio_label = f"a{pair_count}"
            filters.append(
                f"[0:v]trim=start={previous_anchor:.3f}:end={anchor:.3f},"
                f"setpts=PTS-STARTPTS[{video_label}]"
            )
            filters.append(
                f"[sourcea{source_audio_index}]"
                f"atrim=start={previous_anchor:.3f}:end={anchor:.3f},"
                f"asetpts=PTS-STARTPTS[{audio_label}]"
            )
            concat_labels.extend([f"[{video_label}]", f"[{audio_label}]"])
            pair_count += 1
            source_audio_index += 1

        freeze_video_label = f"v{pair_count}"
        freeze_audio_label = f"a{pair_count}"
        frame_end = min(source_duration, anchor + 0.05)
        filters.append(
            f"[0:v]trim=start={anchor:.3f}:end={frame_end:.3f},"
            "setpts=PTS-STARTPTS,tpad=stop_mode=clone:"
            f"stop_duration={inserted_duration:.3f},"
            f"trim=duration={inserted_duration:.3f},setpts=PTS-STARTPTS"
            f"[{freeze_video_label}]"
        )
        _append_inserted_audio_filter(
            filters,
            event,
            int(event["input_index"]),
            freeze_audio_label,
        )
        concat_labels.extend(
            [f"[{freeze_video_label}]", f"[{freeze_audio_label}]"]
        )
        pair_count += 1

        output_anchor = anchor + cumulative_offset
        cumulative_offset += inserted_duration
        insertions.append(
            _record_insertion(
                event,
                output_anchor,
                cumulative_offset,
            )
        )
        previous_anchor = anchor

    if previous_anchor < source_duration - 0.001:
        video_label = f"v{pair_count}"
        audio_label = f"a{pair_count}"
        filters.append(
            f"[0:v]trim=start={previous_anchor:.3f}:end={source_duration:.3f},"
            f"setpts=PTS-STARTPTS[{video_label}]"
        )
        filters.append(
            f"[sourcea{source_audio_index}]"
            f"atrim=start={previous_anchor:.3f}:end={source_duration:.3f},"
            f"asetpts=PTS-STARTPTS[{audio_label}]"
        )
        concat_labels.extend([f"[{video_label}]", f"[{audio_label}]"])
        pair_count += 1

    filters.append(
        "".join(concat_labels)
        + f"concat=n={pair_count}:v=1:a=1[vout][aout]"
    )
    command += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(paths.output_video),
    ]
    result = subprocess_run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    timeline = {
        "source_duration": round(source_duration, 3),
        "output_duration": round(source_duration + cumulative_offset, 3),
        "total_inserted_duration": round(cumulative_offset, 3),
        "insertions": insertions,
    }
    atomic_write_json(paths.timeline_offsets_json, timeline)
    atomic_write_json(paths.transition_segments_json, transition_data)
    return timeline


def run_synthesis(job_id: str) -> dict[str, Any]:
    paths = JobPaths(job_id)
    enriched = read_json(paths.enriched_segments_json)
    transitions = read_json(paths.transition_segments_json)
    narrated_segments = _narrated_segments(enriched.get("segments", []))

    timeline = _synthesize(
        paths,
        narrated_segments,
        transitions,
    )
    atomic_write_json(paths.enriched_segments_json, enriched)

    return {
        "narrated_segment_count": sum(
            1
            for insertion in timeline["insertions"]
            if insertion["kind"] == "regular"
        ),
        "transition_insertion_count": sum(
            1
            for insertion in timeline["insertions"]
            if insertion["kind"] == "transition"
        ),
        "total_inserted_duration": timeline["total_inserted_duration"],
        "output_duration": timeline["output_duration"],
    }
