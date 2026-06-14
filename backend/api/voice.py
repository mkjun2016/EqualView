


# 유저의 녹화된 음성(command)를
# backend/uploads/ 폴더에 음성파일로 저장. (폴더가 존재하지 않을 시 만듬.)


###############################################
from fastapi import APIRouter, UploadFile, File
from pathlib import Path
import uuid

router = APIRouter()

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@router.post("/api/voice-command")
async def receive_voice_command(audio: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    file_extension = Path(audio.filename).suffix

    if not file_extension:
        file_extension = ".webm"

    saved_filename = f"{file_id}{file_extension}"
    saved_path = UPLOAD_DIR / saved_filename

    contents = await audio.read()

    with open(saved_path, "wb") as f:
        f.write(contents)

    return {
        "message": "Audio received successfully",
        "filename": saved_filename,
        "content_type": audio.content_type,
        "size": len(contents)
    }