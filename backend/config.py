import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CELERY_WORKER_CONCURRENCY = int(
    os.getenv("CELERY_WORKER_CONCURRENCY", "2")
)

FACE_MODEL_NAME = os.getenv("FACE_MODEL_NAME", "buffalo_l")
FACE_MODEL_ROOT = Path(
    os.getenv("FACE_MODEL_ROOT", str(BASE_DIR / "models"))
)

FACE_CTX_ID = int(os.getenv("FACE_CTX_ID", "-1"))
FACE_PROVIDERS = os.getenv("FACE_PROVIDERS", "auto")

FACE_DET_SIZE_VALUE = int(os.getenv("FACE_DET_SIZE", "640"))
FACE_DET_SIZE = (FACE_DET_SIZE_VALUE, FACE_DET_SIZE_VALUE)

FACE_DET_THRESHOLD = float(os.getenv("FACE_DET_THRESHOLD", "0.60"))

FACE_MATCH_THRESHOLD = float(
    os.getenv("FACE_MATCH_THRESHOLD", "0.42")
)

FACE_ID_MAX_PROTOTYPES = int(
    os.getenv("FACE_ID_MAX_PROTOTYPES", "5")
)

FACE_ID_PROTOTYPE_ADD_THRESHOLD = float(
    os.getenv("FACE_ID_PROTOTYPE_ADD_THRESHOLD", "0.72")
)

ANNOTATED_FRAME_INTERVAL_SECONDS = float(
    os.getenv("ANNOTATED_FRAME_INTERVAL_SECONDS", "0.51")
)

FACE_FRAME_SIMILARITY_THRESHOLD = float(
    os.getenv("FACE_FRAME_SIMILARITY_THRESHOLD", "0.91")
)

FACE_NEW_ID_MIN_CONFIDENCE = float(
    os.getenv("FACE_NEW_ID_MIN_CONFIDENCE", "0.55")
)

FACE_NEW_ID_MIN_AREA_RATIO = float(
    os.getenv("FACE_NEW_ID_MIN_AREA_RATIO", "0.003")
)

FACE_NEW_ID_EDGE_MARGIN_RATIO = float(
    os.getenv("FACE_NEW_ID_EDGE_MARGIN_RATIO", "0")
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

NARRATION_FRAMES_PER_SEGMENT = int(
    os.getenv("NARRATION_FRAMES_PER_SEGMENT", "3")
)

NARRATION_MAX_CONCURRENCY = int(
    os.getenv("NARRATION_MAX_CONCURRENCY", "3")
)

NARRATION_FRAME_MAX_PX = int(
    os.getenv("NARRATION_FRAME_MAX_PX", "512")
)

NARRATION_JPEG_QUALITY = int(
    os.getenv("NARRATION_JPEG_QUALITY", "80")
)

TTS_VOICE = os.getenv("TTS_VOICE", "ko-KR-SunHiNeural")
