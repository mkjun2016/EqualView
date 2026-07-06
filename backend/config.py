import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

FRAME_INTERVAL_SECONDS = float(
    os.getenv(
        "FRAME_INTERVAL_SECONDS",
        os.getenv("ANNOTATED_FRAME_INTERVAL_SECONDS", "0.51"),
    )
)

FRAME_SIMILARITY_THRESHOLD = float(
    os.getenv("FRAME_SIMILARITY_THRESHOLD", "0.91")
)
