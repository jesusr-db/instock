# app/backend/detect_route.py
"""POST /detect — stateless YOLO bbox query. No VLM, no scan record."""
from __future__ import annotations

from fastapi import APIRouter, File, UploadFile

from backend.config import get_settings
from backend.detect import detect_products

router = APIRouter()


@router.post("/detect")
async def detect(file: UploadFile = File(...)) -> dict:
    """Run YOLO on the uploaded image. Returns bbox list, never errors on zero detections."""
    settings = get_settings()
    image_bytes = await file.read()
    crops = detect_products(image_bytes, settings)
    return {
        "crops": [
            {
                "crop_index": c.crop_index,
                "bbox": list(c.bbox),
                "confidence": c.confidence,
            }
            for c in crops
        ]
    }
