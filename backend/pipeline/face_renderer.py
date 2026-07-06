# face_tracker.py가 만든 person_001, 색상, 얼굴 좌표를 받음
# 원본 프레임에 색 테두리와 person_001 라벨을 그림
# 결과를 annotated_frames/frame_012000.jpg 같은 파일로 저장


from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


def draw_face_annotations(
    frame: np.ndarray,
    detections: list[dict[str, Any]],
) -> np.ndarray:
    """
    원본 프레임을 복사한 뒤,
    얼굴별 빨간색 테두리와 person_id 라벨을 그려 반환한다.
    """
    annotated = frame.copy()
    frame_height, frame_width = annotated.shape[:2]
    box_color = (0, 0, 255)
    label_color = (0, 0, 0)
    label_padding_x = 5
    label_gap = 2

    for detection in detections:
        bbox = detection["pixel_bbox"]
        person_id = detection["person_id"]

        x1 = int(bbox["x1"])
        y1 = int(bbox["y1"])
        x2 = int(bbox["x2"])
        y2 = int(bbox["y2"])

        cv2.rectangle(
            annotated,
            (x1, y1),
            (x2, y2),
            box_color,
            thickness=1,
        )

        label = person_id
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.65
        thickness = 2

        (label_width, label_height), baseline = cv2.getTextSize(
            label,
            font,
            font_scale,
            thickness,
        )

        label_box_width = label_width + (label_padding_x * 2)
        label_box_height = label_height + baseline + 8

        label_left = min(
            max(0, x1),
            max(0, frame_width - label_box_width),
        )

        label_top = y1 - label_box_height - label_gap

        if label_top < 0:
            label_top = y2 + label_gap

        label_top = min(
            max(0, label_top),
            max(0, frame_height - label_box_height),
        )
        label_right = min(frame_width, label_left + label_box_width)
        label_bottom = min(frame_height, label_top + label_box_height)

        cv2.rectangle(
            annotated,
            (label_left, label_top),
            (label_right, label_bottom),
            label_color,
            thickness=-1,
        )

        text_x = label_left + label_padding_x
        text_y = label_top + label_height + 4

        cv2.putText(
            annotated,
            label,
            (text_x, text_y),
            font,
            font_scale,
            (255, 255, 255),
            thickness,
            lineType=cv2.LINE_AA,
        )

    return annotated


def save_annotated_frame(
    frame: np.ndarray,
    output_path: Path,
) -> None:
    """
    후처리된 프레임을 JPEG 파일로 저장한다.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    success, encoded_image = cv2.imencode(
    ".jpg",
    frame,
    [cv2.IMWRITE_JPEG_QUALITY, 95],
    )

    if not success:
        raise RuntimeError(
            f"Failed to encode annotated frame: {output_path}"
        )

    encoded_image.tofile(str(output_path))
