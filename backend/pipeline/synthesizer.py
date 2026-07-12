from __future__ import annotations

import shutil
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


def _mix_regular_narrations(
    paths: JobPaths,
    segments: list[dict[str, Any]],
) -> None:
    video_path = paths.find_input_video()
    if not segments:
        _mux_passthrough(video_path, paths.audio_wav, paths.base_narrated_video)
        return

    inputs = [video_path, paths.audio_wav]
    filter_parts: list[str] = [
        "[0:v]setpts=PTS-STARTPTS[vbase]",
        "[1:a]asetpts=PTS-STARTPTS[abase]",
    ]
    mix_labels = ["abase"]

    for index, segment in enumerate(segments):
        narration_path = paths.job_dir / segment["narration_audio"]
        inputs.append(narration_path)
        input_index = index + 2
        narration_start = float(
            segment.get("narration_start_timestamp", segment["start"])
        )
        available_duration = max(
            0.1,
            float(segment["end"]) - narration_start,
        )
        delay_ms = round(narration_start * 1000)
        label = f"a{index}"
        filter_parts.append(
            f"[{input_index}:a]atempo={NARRATION_ATEMPO:.3f},"
            f"atrim=duration={available_duration:.3f},asetpts=PTS-STARTPTS,"
            f"adelay={delay_ms}:all=1[{label}]"
        )
        mix_labels.append(label)

    mix_inputs = "".join(f"[{label}]" for label in mix_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(mix_labels)}:duration=first:"
        "dropout_transition=0:normalize=0[aout]"
    )

    command = [get_ffmpeg_binary(), "-y"]
    for input_path in inputs:
        command += ["-i", str(input_path)]
    command += [
        "-filter_complex",
        ";".join(filter_parts),
        "-map",
        "[vbase]",
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
        str(paths.base_narrated_video),
    ]
    result = subprocess_run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def _insert_transition_freezes(
    paths: JobPaths,
    transition_data: dict[str, Any],
) -> dict[str, Any]:
    source_duration = float(probe_media_info(paths.base_narrated_video).duration)
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
    if not transitions:
        shutil.copyfile(paths.base_narrated_video, paths.output_video)
        output = {
            "source_duration": round(source_duration, 3),
            "output_duration": round(source_duration, 3),
            "total_inserted_duration": 0.0,
            "insertions": [],
        }
        atomic_write_json(paths.timeline_offsets_json, output)
        return output

    valid: list[dict[str, Any]] = []
    last_anchor = -1.0
    for transition in transitions:
        # FFmpeg needs a real source frame after the trim start. Keep an
        # end-of-video anchor just inside the final frame instead of producing
        # a zero-length freeze stream.
        latest_frame_anchor = max(0.0, source_duration - 0.04)
        insertion_timestamp = float(
            transition.get("insertion_timestamp", transition["anchor_timestamp"])
        )
        anchor = min(
            latest_frame_anchor,
            max(0.0, insertion_timestamp),
        )
        # Multiple transitions may collide with the same narration and thus
        # share its start time. Keep them in order so each is inserted before
        # that narration instead of silently dropping later transitions.
        if anchor < last_anchor - 0.001:
            continue
        valid.append({**transition, "insertion_timestamp": anchor})
        last_anchor = anchor

    command = [get_ffmpeg_binary(), "-y", "-i", str(paths.base_narrated_video)]
    for transition in valid:
        command += ["-i", str(paths.job_dir / transition["tts_audio"])]

    filters: list[str] = []
    concat_labels: list[str] = []
    previous_anchor = 0.0
    cumulative_offset = 0.0
    insertions: list[dict[str, Any]] = []
    pair_count = 0

    for index, transition in enumerate(valid):
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
                f"[0:a]atrim=start={previous_anchor:.3f}:end={anchor:.3f},"
                "asetpts=PTS-STARTPTS,aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[{audio_label}]"
            )
            concat_labels.extend([f"[{video_label}]", f"[{audio_label}]"])
            pair_count += 1

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
        filters.append(
            f"[{index + 1}:a]atempo={NARRATION_ATEMPO:.3f},"
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
            f"[0:a]atrim=start={previous_anchor:.3f}:end={source_duration:.3f},"
            "asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[{audio_label}]"
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

    _mix_regular_narrations(paths, narrated_segments)
    timeline = _insert_transition_freezes(paths, transitions)
    return {
        "narrated_segment_count": len(narrated_segments),
        "transition_insertion_count": len(timeline["insertions"]),
        "total_inserted_duration": timeline["total_inserted_duration"],
        "output_duration": timeline["output_duration"],
    }


def _mux_passthrough(video_path: Path, audio_path: Path, output_path: Path) -> None:
    command = [
        get_ffmpeg_binary(),
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(audio_path),
        "-filter_complex",
        "[0:v]setpts=PTS-STARTPTS[vout];"
        "[1:a]asetpts=PTS-STARTPTS[aout]",
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
        str(output_path),
    ]
    result = subprocess_run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
