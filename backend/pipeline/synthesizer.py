from __future__ import annotations

from pathlib import Path
from typing import Any

from utils.ffmpeg_paths import get_ffmpeg_binary, probe_media_info, subprocess_run
from utils.json_io import atomic_write_json, read_json
from utils.paths import JobPaths


NARRATION_ATEMPO = 1.1
TRANSITION_SILENCE_SECONDS = 0.5


def _narrated_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in segments
        if segment.get("narration_candidate") and segment.get("narration_audio")
    ]


def _source_duration(paths: JobPaths) -> float:
    """Match the legacy first pass, which ends at the shortest base input."""
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
    transitions = sorted(
        (
            item
            for item in transition_data.get("scenes", [])
            if item.get("tts_audio") and float(item.get("tts_duration") or 0) > 0
        ),
        key=lambda item: float(
            item.get("insertion_timestamp", item["anchor_timestamp"])
        ),
    )

    valid: list[dict[str, Any]] = []
    last_anchor = -1.0
    latest_frame_anchor = max(0.0, source_duration - 0.04)
    for transition in transitions:
        insertion_timestamp = float(
            transition.get("insertion_timestamp", transition["anchor_timestamp"])
        )
        anchor = min(latest_frame_anchor, max(0.0, insertion_timestamp))
        if anchor < last_anchor - 0.001:
            continue
        valid.append({**transition, "insertion_timestamp": anchor})
        last_anchor = anchor

    return valid


def _regular_audio_mix_filters(
    segments: list[dict[str, Any]],
) -> list[str]:
    filters = [
        "[1:a]asetpts=PTS-STARTPTS,aresample=48000,"
        "aformat=sample_fmts=fltp:channel_layouts=stereo[abase]"
    ]
    mix_labels = ["abase"]

    for index, segment in enumerate(segments):
        input_index = index + 2
        narration_start = float(
            segment.get("narration_start_timestamp", segment["start"])
        )
        delay_ms = round(narration_start * 1000)
        label = f"regular{index}"
        filters.append(
            f"[{input_index}:a]atempo={NARRATION_ATEMPO:.3f},"
            "asetpts=PTS-STARTPTS,"
            f"adelay={delay_ms}:all=1,aresample=48000,"
            "aformat=sample_fmts=fltp:channel_layouts=stereo"
            f"[{label}]"
        )
        mix_labels.append(label)

    if len(mix_labels) == 1:
        filters.append("[abase]anull[amixed]")
        return filters

    mix_inputs = "".join(f"[{label}]" for label in mix_labels)
    filters.append(
        f"{mix_inputs}amix=inputs={len(mix_labels)}:duration=first:"
        "dropout_transition=0:normalize=0[amixed]"
    )
    return filters


def _count_source_audio_chunks(
    transitions: list[dict[str, Any]],
    source_duration: float,
) -> int:
    count = 0
    previous_anchor = 0.0
    for transition in transitions:
        anchor = float(transition["insertion_timestamp"])
        if anchor > previous_anchor + 0.001:
            count += 1
        previous_anchor = anchor
    if previous_anchor < source_duration - 0.001:
        count += 1
    return count


def _write_empty_transition_timeline(
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


def _synthesize(
    paths: JobPaths,
    segments: list[dict[str, Any]],
    transition_data: dict[str, Any],
) -> dict[str, Any]:
    """Mix regular narration and insert transition freezes in one encode."""
    video_path = paths.find_input_video()
    source_duration = _source_duration(paths)
    transitions = _valid_transitions(transition_data, source_duration)

    command = [
        get_ffmpeg_binary(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(paths.audio_wav),
    ]
    for segment in segments:
        command += ["-i", str(paths.job_dir / segment["narration_audio"])]
    for transition in transitions:
        command += ["-i", str(paths.job_dir / transition["tts_audio"])]

    filters = _regular_audio_mix_filters(segments)
    if not transitions:
        filters.append("[0:v]setpts=PTS-STARTPTS[vout]")
        command += [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[amixed]",
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
        return _write_empty_transition_timeline(paths, source_duration)

    source_audio_chunks = _count_source_audio_chunks(
        transitions,
        source_duration,
    )
    if source_audio_chunks <= 0:
        raise RuntimeError("Single-pass synthesis produced no source audio chunks.")
    if source_audio_chunks == 1:
        filters.append("[amixed]anull[sourcea0]")
    else:
        split_outputs = "".join(
            f"[sourcea{index}]" for index in range(source_audio_chunks)
        )
        filters.append(f"[amixed]asplit={source_audio_chunks}{split_outputs}")

    concat_labels: list[str] = []
    previous_anchor = 0.0
    cumulative_offset = 0.0
    insertions: list[dict[str, Any]] = []
    pair_count = 0
    source_audio_index = 0
    transition_input_offset = 2 + len(segments)

    for index, transition in enumerate(transitions):
        anchor = float(transition["insertion_timestamp"])
        spoken_duration = float(transition["tts_duration"]) / NARRATION_ATEMPO
        freeze_duration = round(
            spoken_duration + (TRANSITION_SILENCE_SECONDS * 2), 3
        )

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
            f"stop_duration={freeze_duration:.3f},"
            f"trim=duration={freeze_duration:.3f},setpts=PTS-STARTPTS"
            f"[{freeze_video_label}]"
        )
        transition_input_index = transition_input_offset + index
        filters.append(
            f"[{transition_input_index}:a]atempo={NARRATION_ATEMPO:.3f},"
            f"adelay={round(TRANSITION_SILENCE_SECONDS * 1000)}:all=1,apad,"
            f"atrim=duration={freeze_duration:.3f},asetpts=PTS-STARTPTS,"
            "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
            f"[{freeze_audio_label}]"
        )
        concat_labels.extend(
            [f"[{freeze_video_label}]", f"[{freeze_audio_label}]"]
        )
        pair_count += 1

        output_anchor = anchor + cumulative_offset
        cumulative_offset += freeze_duration
        insertion = {
            "detected_anchor_timestamp": round(
                float(transition["anchor_timestamp"]), 3
            ),
            "source_insertion_timestamp": round(anchor, 3),
            "output_insertion_timestamp": round(output_anchor, 3),
            "leading_silence": TRANSITION_SILENCE_SECONDS,
            "spoken_duration": round(spoken_duration, 3),
            "trailing_silence": TRANSITION_SILENCE_SECONDS,
            "inserted_duration": freeze_duration,
            "cumulative_offset_after": round(cumulative_offset, 3),
            "transition_segment_description": transition[
                "transition_segment_description"
            ],
            "location": transition["location"],
        }
        insertions.append(insertion)
        transition["output_insertion_timestamp"] = insertion[
            "output_insertion_timestamp"
        ]
        transition["inserted_duration"] = freeze_duration
        transition["cumulative_offset_after"] = insertion[
            "cumulative_offset_after"
        ]
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

    return {
        "narrated_segment_count": len(narrated_segments),
        "transition_insertion_count": len(timeline["insertions"]),
        "total_inserted_duration": timeline["total_inserted_duration"],
        "output_duration": timeline["output_duration"],
    }

