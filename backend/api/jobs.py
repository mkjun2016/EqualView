from pathlib import Path
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from celery_app import celery_app
from config import UPLOAD_DIR
from services.job_store import job_store
from utils.json_io import read_json
from utils.paths import JobPaths

router = APIRouter()

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/api/jobs")
async def create_job(file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    paths = JobPaths(job_id)

    extension = Path(file.filename).suffix if file.filename else ""
    if not extension:
        extension = ".mp4"

    input_path = paths.input_path(extension)
    paths.job_dir.mkdir(parents=True, exist_ok=True)

    contents = await file.read()
    with open(input_path, "wb") as f:
        f.write(contents)

    job_store.create(
        job_id,
        {
            "frame_status": "PENDING",
            "frame_progress": 0,
            "frame_current_step": "프레임 추출 대기 중",
            "frame_error": None,
        },
    )
    celery_app.send_task("tasks.process_video_job", args=[job_id])
    celery_app.send_task("tasks.process_frame_job", args=[job_id])

    return {"job_id": job_id, "status": "PENDING"}


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job_data = job_store.get(job_id)
    if job_data is None:
        raise HTTPException(status_code=404, detail="Job not found")

    return job_data


@router.get("/api/jobs/{job_id}/segments/enriched")
def get_job_segments_enriched(job_id: str):
    if not job_store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_store.get(job_id)
    if job_data is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data["status"] == "FAILED":
        raise HTTPException(
            status_code=409,
            detail=job_data.get("error") or "Job failed",
        )

    if job_data["status"] != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not completed yet (status: {job_data['status']})",
        )

    paths = JobPaths(job_id)
    if not paths.segments_enriched_json.exists():
        raise HTTPException(status_code=404, detail="Enriched segments file not found")

    return read_json(paths.segments_enriched_json)


@router.get("/api/jobs/{job_id}/frames/{filename}")
def get_frame(job_id: str, filename: str):
    if not job_store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    safe_name = Path(filename).name
    if safe_name != filename:
        raise HTTPException(status_code=400, detail="Invalid frame filename")

    paths = JobPaths(job_id)
    frame_path = paths.frames_dir / safe_name

    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found")

    return FileResponse(frame_path, media_type="image/jpeg")


@router.get("/api/jobs/{job_id}/segments")
def get_job_segments(job_id: str):
    if not job_store.exists(job_id):
        raise HTTPException(status_code=404, detail="Job not found")

    job_data = job_store.get(job_id)
    if job_data is None:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data["status"] == "FAILED":
        raise HTTPException(
            status_code=409,
            detail=job_data.get("error") or "Job failed",
        )

    if job_data["status"] != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"Job is not completed yet (status: {job_data['status']})",
        )

    paths = JobPaths(job_id)
    if not paths.segments_json.exists():
        raise HTTPException(status_code=404, detail="Segments file not found")

    return read_json(paths.segments_json)
