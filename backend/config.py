import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
