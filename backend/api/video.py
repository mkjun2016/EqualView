from fastapi import APIRouter, UploadFile, File
from pathlib import Path
import uuid
import json
import asyncio

from pipeline.audio_extractor import extract_audio_from_video, get_media_duration

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

    # 1. Real step: extract audio
    extract_audio_from_video(video_path, audio_path)

    duration = get_media_duration(audio_path)

    # 2. Mock steps
    await asyncio.sleep(0.5)  # analyzing scenes mock
    await asyncio.sleep(0.5)  # generating narration mock
    await asyncio.sleep(0.5)  # preparing output mock

    timeline_data = {
        "id": file_id,
        "original_video": video_filename,
        "extracted_audio": audio_filename,
        "audio_format": {
            "type": "wav",
            "sample_rate": 16000,
            "channels": 1
        },
        "duration": round(duration, 2),
        "timeline": [
            {
                "start": 0,
                "end": round(duration, 2),
                "type": "audio",
                "text": ""
            }
        ],
        "processing_steps": [
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
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(timeline_data, f, ensure_ascii=False, indent=2)

    return {
        "message": "Video processing completed",
        "video_file": video_filename,
        "audio_file": audio_filename,
        "json_file": json_filename,
        "duration": round(duration, 2),
        "timeline": timeline_data["timeline"],
        "processing_steps": timeline_data["processing_steps"]
    }