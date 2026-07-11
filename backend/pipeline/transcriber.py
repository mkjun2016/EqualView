from pathlib import Path
from typing import Any


_model: Any | None = None


def get_whisper_model() -> Any:
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8",
        )
    return _model


def transcribe_audio(audio_path: Path):
    model = get_whisper_model()
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True,
    )

    words = []
    transcript_parts = []

    for segment in segments:
        text = segment.text.strip()

        if text:
            transcript_parts.append(text)

        if segment.words:
            for word in segment.words:
                clean_word = word.word.strip()

                if not clean_word:
                    continue

                words.append({
                    "word": clean_word,
                    "start": round(word.start, 2),
                    "end": round(word.end, 2),
                })

    return {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "transcript": " ".join(transcript_parts),
        "words": words,
    }


def _build_script_segment(start, end, speech, text="", sound_category=None):
    start = round(start, 2)
    end = round(end, 2)
    segment_duration = round(max(0, end - start), 2)

    segment = {
        "start": start,
        "end": end,
        "type": "speech" if speech else "non_speech",
        "sound_category": sound_category or ("human_speech" if speech else "silence_or_background"),
        "speech": speech,
        "narration_safe": (not speech) and segment_duration >= 3,
        "text": text if speech else "",
    }

    if (not speech) and segment_duration > 0.5:
        segment["frames"] = []

    return segment


def build_segments_from_words(words, duration, has_audio):
    duration = round(duration, 2)

    if not has_audio:
        return [
            _build_script_segment(
                start=0,
                end=duration,
                speech=False,
                sound_category="no_audio_track",
            )
        ]

    if not words:
        return [
            _build_script_segment(
                start=0,
                end=duration,
                speech=False,
                sound_category="audio_exists_but_no_detected_speech",
            )
        ]

    segments = []
    gap_threshold = 0.7

    current_words = [words[0]]
    current_start = words[0]["start"]
    current_end = words[0]["end"]

    if current_start > 0.2:
        segments.append(
            _build_script_segment(
                start=0,
                end=current_start,
                speech=False,
            )
        )

    for i in range(1, len(words)):
        prev = words[i - 1]
        curr = words[i]

        gap = curr["start"] - prev["end"]

        if gap >= gap_threshold:
            segments.append(
                _build_script_segment(
                    start=current_start,
                    end=current_end,
                    speech=True,
                    text=" ".join([w["word"] for w in current_words]),
                )
            )

            segments.append(
                _build_script_segment(
                    start=prev["end"],
                    end=curr["start"],
                    speech=False,
                )
            )

            current_words = [curr]
            current_start = curr["start"]
            current_end = curr["end"]
        else:
            current_words.append(curr)
            current_end = curr["end"]

    segments.append(
        _build_script_segment(
            start=current_start,
            end=current_end,
            speech=True,
            text=" ".join([w["word"] for w in current_words]),
        )
    )

    last_end = words[-1]["end"]

    if last_end < duration - 0.2:
        segments.append(
            _build_script_segment(
                start=last_end,
                end=duration,
                speech=False,
            )
        )

    return segments
