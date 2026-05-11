"""Stage 1 detection — calls YOLO serving endpoint, returns cropped product regions."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from io import BytesIO

from databricks.sdk import WorkspaceClient
from PIL import Image

from backend.config import Settings

log = logging.getLogger(__name__)


@dataclass
class DetectedCrop:
    crop_index: int
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2 (pixel coords)
    confidence: float
    image_bytes: bytes                 # cropped JPEG bytes


def detect_products(image_bytes: bytes, settings: Settings) -> list[DetectedCrop]:
    """Call YOLO endpoint, crop detections, return sorted by confidence desc.

    Returns [] on any failure — callers fall back to full-image VLM path.
    Uses a long HTTP timeout (300s) to survive cold-start when the endpoint
    has scaled to zero.
    """
    try:
        # Let the SDK resolve auth from its ambient environment (OAuth m2m in
        # Databricks Apps, CLI profile locally).  Passing an explicit token
        # alongside DATABRICKS_CLIENT_ID/SECRET causes "multiple auth methods"
        # ValueError inside the app.
        w = WorkspaceClient(host=settings.databricks_host, http_timeout_seconds=300)
        b64 = base64.b64encode(image_bytes).decode()
        response = w.serving_endpoints.query(
            name=settings.yolo_endpoint,
            dataframe_records=[{"image": b64}],
        )
        predictions = response.predictions or []
        if not predictions:
            log.info("YOLO: no predictions returned")
            return []

        # detections may be a list (from MLflow) or a JSON string
        raw = predictions[0]
        raw_detections: list[dict] = []
        if isinstance(raw, dict):
            val = raw.get("detections", [])
            if isinstance(val, list):
                raw_detections = val
            elif isinstance(val, str):
                import json as _json
                try:
                    raw_detections = _json.loads(val)
                except Exception:
                    import ast
                    raw_detections = ast.literal_eval(val)

        log.info("YOLO: %d raw detections before threshold filter", len(raw_detections))

        raw_detections.sort(key=lambda d: d["confidence"], reverse=True)
        raw_detections = [
            d for d in raw_detections
            if d["confidence"] >= settings.yolo_confidence_threshold
        ]
        log.info(
            "YOLO: %d detections above threshold %.2f",
            len(raw_detections), settings.yolo_confidence_threshold,
        )
        if not raw_detections:
            return []

        img = Image.open(BytesIO(image_bytes))
        crops: list[DetectedCrop] = []
        for i, det in enumerate(raw_detections):
            x1, y1, x2, y2 = (int(v) for v in det["bbox"])
            # Clamp to image bounds
            w_img, h_img = img.size
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w_img, x2), min(h_img, y2)
            if x2 <= x1 or y2 <= y1:
                continue
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
        log.info("YOLO: returning %d crops", len(crops))
        return crops

    except Exception as exc:
        log.warning("YOLO detect_products failed (%s: %s) — using fallback", type(exc).__name__, exc)
        return []
