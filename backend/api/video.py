from fastapi import APIRouter, UploadFile, File
from pathlib import Path
import uuid
import json

from utils.json_io import to_json_safe
from pipeline.audio_extractor import (
    extract_audio_from_video,
    get_media_duration,
    has_audio_stream,
    create_silent_wav
)

from pipeline.transcriber import transcribe_audio, build_segments_from_words

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/api/extract-audio")
async def extract_audio(video: UploadFile = File(...)):
    file_id = str(uuid.uuid4())

    video_extension = Path(video.filename).suffix
    if not video_extension:
        video_extension = ".mp4"

    video_filename = f"{file_id}{video_extension}"
    audio_filename = f"{file_id}.wav"
    json_filename = f"{file_id}.json"

    video_path = UPLOAD_DIR / video_filename
    audio_path = UPLOAD_DIR / audio_filename
    json_path = UPLOAD_DIR / json_filename

    contents = await video.read()

    with open(video_path, "wb") as f:
        f.write(contents)

    video_duration = get_media_duration(video_path)

    audio_exists = has_audio_stream(video_path)

    if audio_exists:
        extract_audio_from_video(video_path, audio_path)
        audio_type = "extracted_audio"
    else:
        create_silent_wav(audio_path, video_duration)
        audio_type = "silent_audio"

    if audio_exists:
        script_result = transcribe_audio(audio_path)
    else:
        script_result = {
            "language": "audio doesn't exist",
            "transcript": "audio doesn't exist",
            "words": "audio doesn't exist"
        }

    segments = build_segments_from_words(
        script_result["words"],
        video_duration,
        audio_exists
    )

    processing_steps = [
        {
            "key": "extracting_audio",
            "label": "Extracting Audio",
            "state": "completed"
        },
        {
            "key": "analyzing_scenes",
            "label": "Analyzing Scenes",
            "state": "completed",
            "mock": True
        },
        {
            "key": "generating_narration",
            "label": "Generating Narration",
            "state": "completed",
            "mock": True
        },
        {
            "key": "preparing_output",
            "label": "Preparing Output",
            "state": "completed",
            "mock": True
        }
    ]

    json_data = {
        "segments": segments
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(to_json_safe(json_data), f, ensure_ascii=False, indent=2)

    return {
        "message": "Video processing completed",
        "video_file": video_filename,
        "audio_file": audio_filename,
        "json_file": json_filename,
        "duration": round(video_duration, 2),
        "has_audio": audio_exists,
        "audio_type": audio_type,
        "processing_steps": processing_steps
    }
