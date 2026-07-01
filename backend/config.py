import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "uploads")))

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# model name
FACE_MODEL_NAME = os.getenv("FACE_MODEL_NAME", "buffalo_l")
FACE_MODEL_ROOT = Path(
    os.getenv("FACE_MODEL_ROOT", str(BASE_DIR / "models"))
)

# -1은 CPU, 0은 첫 번째 NVIDIA GPU를 의미한다. 토글하면됨
FACE_CTX_ID = int(os.getenv("FACE_CTX_ID", "-1"))
FACE_PROVIDERS = os.getenv("FACE_PROVIDERS", "auto")

# 얼굴 검출 시 입력 프레임 크기
FACE_DET_SIZE_VALUE = int(os.getenv("FACE_DET_SIZE", "640"))
FACE_DET_SIZE = (FACE_DET_SIZE_VALUE, FACE_DET_SIZE_VALUE)

# 얼굴로 인정할 최소 검출 신뢰도
FACE_DET_THRESHOLD = float(os.getenv("FACE_DET_THRESHOLD", "0.60"))

# 두 얼굴 임베딩이 같은 인물이라고 판단하는 기준값
FACE_MATCH_THRESHOLD = float(
    os.getenv("FACE_MATCH_THRESHOLD", "0.42")
)

FACE_ID_MAX_PROTOTYPES = int(
    os.getenv("FACE_ID_MAX_PROTOTYPES", "5")
)

FACE_ID_PROTOTYPE_ADD_THRESHOLD = float(
    os.getenv("FACE_ID_PROTOTYPE_ADD_THRESHOLD", "0.72")
)

# non_speech 구간에서 annotated 프레임을 저장할 간격
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

# Gemini 화면해설 생성
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# narration_safe 구간 하나당 Gemini에 보낼 프레임 수
NARRATION_FRAMES_PER_SEGMENT = int(
    os.getenv("NARRATION_FRAMES_PER_SEGMENT", "5")
)

# 화면해설 음성 합성 (무료, API 키 불필요)
TTS_VOICE = os.getenv("TTS_VOICE", "ko-KR-SunHiNeural")
