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
    def voice_segments_json(self) -> Path:
        return self.job_dir / "voice_segments.json"

    @property
    def enriched_segments_json(self) -> Path:
        return self.job_dir / "enriched_segments.json"

    @property
    def transition_segments_json(self) -> Path:
        return self.job_dir / "transition_segments.json"

    # Compatibility aliases for callers outside the main pipeline.
    @property
    def segments_json(self) -> Path:
        return self.voice_segments_json

    @property
    def segments_enriched_json(self) -> Path:
        return self.enriched_segments_json

    @property
    def face_frames_json(self) -> Path:
        return self.job_dir / "face_frames.json"

    @property
    def audio_wav(self) -> Path:
        return self.job_dir / "audio.wav"

    @property
    def face_segments_json(self) -> Path:
        return self.job_dir / "face_segments.json"

    @property
    def transitions_json(self) -> Path:
        return self.transition_segments_json

    @property
    def annotated_frames_dir(self) -> Path:
        return self.job_dir / "annotated_frames"

    @property
    def narration_audio_dir(self) -> Path:
        return self.job_dir / "narration_audio"

    @property
    def transition_audio_dir(self) -> Path:
        return self.job_dir / "transition_audio"

    @property
    def timeline_offsets_json(self) -> Path:
        return self.job_dir / "timeline_offsets.json"

    @property
    def output_video(self) -> Path:
        return self.job_dir / "output.mp4"

    def input_path(self, extension: str) -> Path:
        ext = extension if extension.startswith(".") else f".{extension}"
        return self.job_dir / f"input{ext}"

    def find_input_video(self) -> Path:
        matches = sorted(self.job_dir.glob("input.*"))
        if not matches:
            raise FileNotFoundError(f"No input video found for job {self.job_id}")
        return matches[0]
