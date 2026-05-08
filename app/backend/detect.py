"""Stage 1 detection — calls YOLO serving endpoint, returns cropped product regions."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO

from databricks.sdk import WorkspaceClient
from databricks.sdk.config import Config
from PIL import Image

from backend.config import Settings, get_databricks_token


@dataclass
class DetectedCrop:
    crop_index: int
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2 (pixel coords)
    confidence: float
    image_bytes: bytes                 # cropped JPEG bytes


def detect_products(image_bytes: bytes, settings: Settings) -> list[DetectedCrop]:
    """Call YOLO endpoint, crop detections, return sorted by confidence desc.

    Returns [] on any failure — callers fall back to full-image VLM path.
    """
    try:
        token = get_databricks_token(settings)
        w = WorkspaceClient(config=Config(host=settings.databricks_host, token=token))
        b64 = base64.b64encode(image_bytes).decode()
        response = w.serving_endpoints.query(
            name=settings.yolo_endpoint,
            dataframe_records=[{"image": b64}],
        )
        predictions = response.predictions or []
        if not predictions:
            return []
        raw_detections: list[dict] = (
            predictions[0].get("detections", [])
            if isinstance(predictions[0], dict)
            else []
        )
        if not raw_detections:
            return []

        raw_detections.sort(key=lambda d: d["confidence"], reverse=True)

        # Filter below confidence threshold before cropping
        raw_detections = [d for d in raw_detections if d["confidence"] >= settings.yolo_confidence_threshold]
        if not raw_detections:
            return []

        img = Image.open(BytesIO(image_bytes))
        crops: list[DetectedCrop] = []
        for i, det in enumerate(raw_detections):
            x1, y1, x2, y2 = (int(v) for v in det["bbox"])
            crop_img = img.crop((x1, y1, x2, y2))
            buf = BytesIO()
            crop_img.save(buf, format="JPEG")
            crops.append(
                DetectedCrop(
                    crop_index=i,
                    bbox=(x1, y1, x2, y2),
                    confidence=float(det["confidence"]),
                    image_bytes=buf.getvalue(),
                )
            )
        return crops
    except Exception:
        return []
