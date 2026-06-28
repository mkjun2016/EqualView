from pathlib import Path

from config import UPLOAD_DIR


class JobPaths:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.job_dir = UPLOAD_DIR / job_id

    @property
    def job_json(self) -> Path:
        return self.job_dir / "job.json"

    @property
    def segments_json(self) -> Path:
        return self.job_dir / "segments.json"

    @property
    def segments_enriched_json(self) -> Path:
        return self.job_dir / "segments_enriched.json"

    @property
    def face_frames_json(self) -> Path:
        return self.job_dir / "face_frames.json"

    @property
    def audio_wav(self) -> Path:
        return self.job_dir / "audio.wav"

    def input_path(self, extension: str) -> Path:
        ext = extension if extension.startswith(".") else f".{extension}"
        return self.job_dir / f"input{ext}"

    def find_input_video(self) -> Path:
        matches = sorted(self.job_dir.glob("input.*"))
        if not matches:
            raise FileNotFoundError(f"No input video found for job {self.job_id}")
        return matches[0]
