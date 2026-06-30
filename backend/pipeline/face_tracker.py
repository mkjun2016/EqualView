# InsightFace로 현재 프레임의 얼굴들을 찾는다.  
# 각 얼굴을 이전 프레임의 인물과 비교해서 person_001, person_002와 색상을 계속 유지한다.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import colorsys

# numpy: 얼굴 특징 벡터 계산
import numpy as np
# onnxruntime: InsightFace 모델을 CPU, CUDA, DirectML 등에서 실행
import onnxruntime as ort
# FaceAnalysis: 얼굴 검출과 얼굴 특징 추출
from insightface.app import FaceAnalysis

# 얼굴 처리와 관련된 설정값을 config.py에서 불러옵니다.
from config import (
    FACE_CTX_ID,
    FACE_DET_SIZE,
    FACE_DET_THRESHOLD,
    FACE_ID_MAX_PROTOTYPES,
    FACE_ID_PROTOTYPE_ADD_THRESHOLD,
    FACE_MATCH_THRESHOLD,
    FACE_NEW_ID_EDGE_MARGIN_RATIO,
    FACE_NEW_ID_MIN_AREA_RATIO,
    FACE_NEW_ID_MIN_CONFIDENCE,
    FACE_MODEL_NAME,
    FACE_MODEL_ROOT,
    FACE_PROVIDERS,
)

# 전역변수 모델 재사용
_face_analyzer: FaceAnalysis | None = None


PROVIDER_ALIASES = {
    "cpu": "CPUExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "gpu": "CUDAExecutionProvider",
    "directml": "DmlExecutionProvider",
    "dml": "DmlExecutionProvider",
}

# GPU 실행에 실패하거나 일부 연산이 GPU에서 지원되지 않을 때 CPU로 대신 실행하기 위한 fallback
def _resolve_face_providers() -> list[str]:
    available = set(ort.get_available_providers())
    requested = [
        provider.strip().lower()
        for provider in FACE_PROVIDERS.split(",")
        if provider.strip()
    ]

    if not requested or requested == ["auto"]:
        preferred = [
            "CUDAExecutionProvider",
            "DmlExecutionProvider",
            "CPUExecutionProvider",
        ]
    else:
        preferred = [
            PROVIDER_ALIASES.get(provider, provider)
            for provider in requested
        ]

    providers = [
        provider
        for provider in preferred
        if provider in available
    ]

    if "CPUExecutionProvider" not in providers:
        providers.append("CPUExecutionProvider")

    return providers


def _resolve_face_ctx_id(providers: list[str]) -> int:
    if FACE_CTX_ID >= 0:
        return FACE_CTX_ID

    if any(provider != "CPUExecutionProvider" for provider in providers):
        return 0

    return -1


# 각 person_id에 순서대로 할당할 테두리 색상
GOLDEN_RATIO_CONJUGATE = 0.618033988749895


def assign_person_color(index: int) -> str:
    hue = (index * GOLDEN_RATIO_CONJUGATE) % 1.0
    saturation = 0.82 if index % 2 == 0 else 0.95
    value = 0.95 if (index // 2) % 2 == 0 else 0.78

    red, green, blue = colorsys.hsv_to_rgb(hue, saturation, value)

    return (
        f"#{round(red * 255):02X}"
        f"{round(green * 255):02X}"
        f"{round(blue * 255):02X}"
    )

# 중요한 점은 Celery worker가 여러 개라면 각 worker 프로세스가 자기 모델을 하나씩 로드한다는 것입니다.
def get_face_analyzer() -> FaceAnalysis:
    """
    InsightFace 모델을 워커 프로세스마다 한 번만 불러온다.
    """
    global _face_analyzer

    if _face_analyzer is None:
        FACE_MODEL_ROOT.mkdir(parents=True, exist_ok=True)

        providers = _resolve_face_providers()
        ctx_id = _resolve_face_ctx_id(providers)

        _face_analyzer = FaceAnalysis(
            name=FACE_MODEL_NAME,
            root=str(FACE_MODEL_ROOT),
            providers=providers,
        )

        _face_analyzer.prepare(
            ctx_id=ctx_id,
            det_size=FACE_DET_SIZE,
        )

    return _face_analyzer


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    """
    얼굴 특징 벡터의 길이를 1로 맞춘다.
    이후 두 벡터의 내적은 cosine similarity가 된다.
    """
    vector = np.asarray(embedding, dtype=np.float32)
    norm = np.linalg.norm(vector)

    if norm == 0:
        return vector

    return vector / norm


@dataclass
class PersonIdentity:
    person_id: str
    color: str
    embedding: np.ndarray
    first_seen: float
    last_seen: float
    detection_count: int = 0
    prototypes: list[np.ndarray] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.prototypes:
            self.prototypes.append(self.embedding)

    def update(self, embedding: np.ndarray, timestamp: float) -> None:
        """
        새 얼굴 특징을 기존 특징과 평균 내어,
        조명·각도 변화에도 person_id가 유지되게 한다.
        """
        # 기존 80프로 반영, 새 특징 20프로 반영 
        updated = self.embedding * 0.8 + embedding * 0.2
        self.embedding = normalize_embedding(updated)

        prototype_scores = [
            float(np.dot(embedding, prototype))
            for prototype in self.prototypes
        ]

        if (
            max(prototype_scores, default=0.0)
            < FACE_ID_PROTOTYPE_ADD_THRESHOLD
        ):
            if len(self.prototypes) < FACE_ID_MAX_PROTOTYPES:
                self.prototypes.append(embedding)
            else:
                weakest_index = int(np.argmin(prototype_scores))
                self.prototypes[weakest_index] = embedding

        self.last_seen = timestamp
        self.detection_count += 1

    def similarity_to(self, embedding: np.ndarray) -> float:
        scores = [float(np.dot(embedding, self.embedding))]
        scores.extend(
            float(np.dot(embedding, prototype))
            for prototype in self.prototypes
        )

        return max(scores)


class FaceTracker:
    """
    프레임마다 검출된 얼굴을 기존 person_id와 연결한다.
    """

    def __init__(self) -> None:
        self.identities: list[PersonIdentity] = []

    def detect(self, frame: np.ndarray) -> list[Any]:
        analyzer = get_face_analyzer()
        faces = analyzer.get(frame)

        return [
            face
            for face in faces
            if float(face.det_score) >= FACE_DET_THRESHOLD
        ]

    def assign_faces(
        self,
        faces: list[Any],
        timestamp: float,
        frame_width: int,
        frame_height: int,
    ) -> list[dict[str, Any]]:
        """
        이번 프레임의 얼굴마다 person_id, 색상, 정규화 bbox를 반환한다.
        """
        assigned_person_ids: set[str] = set()
        results: list[dict[str, Any]] = []

        for face in faces:
            embedding = normalize_embedding(face.embedding)

            identity = self._find_best_identity(
                embedding=embedding,
                assigned_person_ids=assigned_person_ids,
            )

            x1, y1, x2, y2 = [float(value) for value in face.bbox]

            x1 = max(0.0, min(x1, float(frame_width)))
            y1 = max(0.0, min(y1, float(frame_height)))
            x2 = max(0.0, min(x2, float(frame_width)))
            y2 = max(0.0, min(y2, float(frame_height)))

            if identity is None:
                if self._can_create_identity(
                    face=face,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    frame_width=frame_width,
                    frame_height=frame_height,
                ):
                    identity = self._create_identity(
                        embedding=embedding,
                        timestamp=timestamp,
                    )
                else:
                    results.append(
                        self._build_detection_result(
                            person_id="unknown",
                            color="#000000",
                            confidence=face.det_score,
                            x1=x1,
                            y1=y1,
                            x2=x2,
                            y2=y2,
                            frame_width=frame_width,
                            frame_height=frame_height,
                        )
                    )
                    continue
            else:
                identity.update(
                    embedding=embedding,
                    timestamp=timestamp,
                )

            assigned_person_ids.add(identity.person_id)

            results.append(
                self._build_detection_result(
                    person_id=identity.person_id,
                    color=identity.color,
                    confidence=face.det_score,
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                    frame_width=frame_width,
                    frame_height=frame_height,
                )
            )

        return results

    def _can_create_identity(
        self,
        face: Any,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        confidence = float(face.det_score)
        area_ratio = ((x2 - x1) * (y2 - y1)) / (
            frame_width * frame_height
        )
        touches_edge = False

        if FACE_NEW_ID_EDGE_MARGIN_RATIO > 0:
            edge_margin_x = frame_width * FACE_NEW_ID_EDGE_MARGIN_RATIO
            edge_margin_y = frame_height * FACE_NEW_ID_EDGE_MARGIN_RATIO
            touches_edge = (
                x1 <= edge_margin_x
                or y1 <= edge_margin_y
                or x2 >= frame_width - edge_margin_x
                or y2 >= frame_height - edge_margin_y
            )

        return (
            confidence >= FACE_NEW_ID_MIN_CONFIDENCE
            and area_ratio >= FACE_NEW_ID_MIN_AREA_RATIO
            and not touches_edge
        )

    def _build_detection_result(
        self,
        person_id: str,
        color: str,
        confidence: float,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        frame_width: int,
        frame_height: int,
    ) -> dict[str, Any]:
        return {
            "person_id": person_id,
            "color": color,
            "confidence": round(float(confidence), 4),
            "bbox": {
                "x": round(x1 / frame_width, 6),
                "y": round(y1 / frame_height, 6),
                "w": round((x2 - x1) / frame_width, 6),
                "h": round((y2 - y1) / frame_height, 6),
            },
            "pixel_bbox": {
                "x1": round(x1),
                "y1": round(y1),
                "x2": round(x2),
                "y2": round(y2),
            },
        }

    def _find_best_identity(
        self,
        embedding: np.ndarray,
        assigned_person_ids: set[str],
    ) -> PersonIdentity | None:
        candidates = [
            identity
            for identity in self.identities
            if identity.person_id not in assigned_person_ids
        ]

        if not candidates:
            return None

        scores = [
            identity.similarity_to(embedding)
            for identity in candidates
        ]

        best_index = int(np.argmax(scores))
        best_score = scores[best_index]

        if best_score < FACE_MATCH_THRESHOLD:
            return None

        return candidates[best_index]

    def _create_identity(
        self,
        embedding: np.ndarray,
        timestamp: float,
    ) -> PersonIdentity:
        number = len(self.identities) + 1

        identity = PersonIdentity(
            person_id=f"person_{number:03d}",
            color=assign_person_color(number - 1),
            embedding=embedding,
            first_seen=timestamp,
            last_seen=timestamp,
            detection_count=1,
        )

        self.identities.append(identity)
        return identity

    def get_identities(self) -> list[dict[str, Any]]:
        """
        face_segments.json의 identities 배열에 넣을 요약 정보.
        """
        return [
            {
                "person_id": identity.person_id,
                "color": identity.color,
                "first_seen": round(identity.first_seen, 3),
                "last_seen": round(identity.last_seen, 3),
                "detection_count": identity.detection_count,
                "prototype_count": len(identity.prototypes),
            }
            for identity in self.identities
        ]
