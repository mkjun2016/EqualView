from pathlib import Path
from faster_whisper import WhisperModel


model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)


def transcribe_audio(audio_path: Path):
    segments, info = model.transcribe(
        str(audio_path),
        beam_size=5,
        word_timestamps=True,
        vad_filter=True
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
                    "end": round(word.end, 2)
                })

    return {
        "language": info.language,
        "language_probability": round(info.language_probability, 3),
        "transcript": " ".join(transcript_parts),
        "words": words
    }


def build_segments_from_words(words, duration, has_audio):
    duration = round(duration, 2)

    if not has_audio:
        return [
            {
                "start": 0,
                "end": duration,
                "type": "non_speech",
                "sound_category": "no_audio_track",
                "text": ""
            }
        ]

    if not words:
        return [
            {
                "start": 0,
                "end": duration,
                "type": "non_speech",
                "sound_category": "audio_exists_but_no_detected_speech",
                "text": ""
            }
        ]

    segments = []
    # 대사와 대사 사이가 0.7초 이상이면 대사가 끊겼다고 보고 non_speech 구간 생성
    gap_threshold = 0.7

    cursor = 0
    current_words = [words[0]]
    current_start = words[0]["start"]
    current_end = words[0]["end"]

    if current_start > 0.2:
        segments.append({
            "start": 0,
            "end": round(current_start, 2),
            "type": "non_speech",
            "sound_category": "silence_or_background",
            "text": ""
        })

    for i in range(1, len(words)):
        prev = words[i - 1]
        curr = words[i]

        gap = curr["start"] - prev["end"]

        if gap >= gap_threshold:
            segments.append({
                "start": round(current_start, 2),
                "end": round(current_end, 2),
                "type": "speech",
                "sound_category": "human_speech",
                "text": " ".join([w["word"] for w in current_words]),
                "words": current_words
            })

            segments.append({
                "start": round(prev["end"], 2),
                "end": round(curr["start"], 2),
                "type": "non_speech",
                "sound_category": "silence_or_background",
                "text": ""
            })

            current_words = [curr]
            current_start = curr["start"]
            current_end = curr["end"]

        else:
            current_words.append(curr)
            current_end = curr["end"]

    segments.append({
        "start": round(current_start, 2),
        "end": round(current_end, 2),
        "type": "speech",
        "sound_category": "human_speech",
        "text": " ".join([w["word"] for w in current_words]),
        "words": current_words
    })

    last_end = words[-1]["end"]

    if last_end < duration - 0.2:
        segments.append({
            "start": round(last_end, 2),
            "end": duration,
            "type": "non_speech",
            "sound_category": "silence_or_background",
            "text": ""
        })

    return segments