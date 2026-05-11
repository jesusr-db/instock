"""POST /analyze — image upload → AI Gateway → structured JSON.

Receives a multipart upload (file + optional model_route override), encodes
the image as base64, sends a vision message to the configured AI Gateway
endpoint, and parses the model response into a strict JSON schema.

The endpoint also persists the raw image bytes to the configured UC volume
(or local fallback for dev) so the scan_log can reference it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import uuid
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from openai import OpenAI

from backend.config import get_databricks_token, get_settings

router = APIRouter()


class ModelResponseError(Exception):
    """Raised when the model response is not valid JSON."""


def build_vision_prompt() -> str:
    """The vision prompt sent with every image — enumerates every required JSON key."""
    return (
        "Identify the product in this image. "
        "Return ONLY valid JSON (no markdown, no extra text) with these exact keys: "
        '{"brand":"brand name","category":"tobacco|beverage|snack",'
        '"product_name":"full product name","size":"size description",'
        '"flavor":"flavor or null",'
        '"top_3_sku_candidates":['
        '{"candidate_name":"brand product_name size","confidence_score":0.95}'
        "]} "
        "Provide exactly 3 candidates ordered by confidence_score (highest first). "
        "category must be one of: tobacco, beverage, snack. "
        "IMPORTANT: Only identify a product if you can clearly read the brand name from the image. "
        "If the image is too small, blurry, or the label is not legible, return brand=null "
        "and an empty top_3_sku_candidates array. Do NOT guess a brand you cannot see. "
        "For the size field and every candidate_name, always specify pack count: "
        "add '1ct' or 'single' for individual units (one bottle, one can, one bag); "
        "add the count (e.g., '24pk', '6pk', '12pk') for multipacks or cases. "
        "If uncertain, default to '1ct'. "
        "Example: '20oz 1ct' for a single bottle, '20oz 24pk' for a case of 24."
    )


def parse_model_response(raw: str) -> dict:
    """Parse the model output, tolerating ```json fences and surrounding whitespace."""
    cleaned = re.sub(r"^\s*```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ModelResponseError(f"Non-JSON model response: {e}") from e


def _save_image(image_bytes: bytes, ext: str, scan_id: str) -> str | None:
    """Persist image to UC volume (or local fallback). Returns the path, or None on failure."""
    settings = get_settings()
    volume = settings.image_volume_path
    path = f"{volume}/{scan_id}.{ext}"
    try:
        os.makedirs(volume, exist_ok=True)
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    except OSError:
        # Non-fatal — the scan_log just records None for the volume path.
        return None


@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    model_route: str = Form(default=None),
    crop_x1: Optional[int] = Form(default=None),
    crop_y1: Optional[int] = Form(default=None),
    crop_x2: Optional[int] = Form(default=None),
    crop_y2: Optional[int] = Form(default=None),
):
    """Vision inference endpoint.

    Body: multipart/form-data with `file` (image), optional `model_route`,
    and optional `crop_x1/y1/x2/y2` pixel coords (original image space).

    Returns: scan_id, model_route, image_volume_path, brand, category,
             product_name, size, flavor, top_3_sku_candidates,
             detection_stage, detections (when yolo stage ran).
    """
    settings = get_settings()
    route = model_route or settings.model_route
    scan_id = str(uuid.uuid4())

    image_bytes = await file.read()
    filename = file.filename or "image.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"

    volume_path = _save_image(image_bytes, ext, scan_id)

    vlm_image_bytes = image_bytes
    detection_stage = "disabled"
    detections_meta: list[dict] | None = None

    user_crop_provided = all(v is not None for v in (crop_x1, crop_y1, crop_x2, crop_y2))

    if user_crop_provided:
        from io import BytesIO as _BytesIO

        from PIL import Image as _Image

        img = _Image.open(_BytesIO(image_bytes))
        w_img, h_img = img.size
        x1 = max(0, min(int(crop_x1), w_img))  # type: ignore[arg-type]
        y1 = max(0, min(int(crop_y1), h_img))  # type: ignore[arg-type]
        x2 = max(0, min(int(crop_x2), w_img))  # type: ignore[arg-type]
        y2 = max(0, min(int(crop_y2), h_img))  # type: ignore[arg-type]
        if x2 > x1 and y2 > y1:
            crop_img = img.crop((x1, y1, x2, y2))
            buf = _BytesIO()
            crop_img.save(buf, format="JPEG")
            vlm_image_bytes = buf.getvalue()
        detection_stage = "user-crop"

    elif settings.use_detection_stage:
        from backend.detect import detect_products

        crops = detect_products(image_bytes, settings)
        if crops:
            vlm_image_bytes = crops[0].image_bytes
            detection_stage = "yolo"
            detections_meta = [
                {"crop_index": c.crop_index, "bbox": list(c.bbox), "confidence": c.confidence}
                for c in crops
            ]
        else:
            detection_stage = "fallback"

    b64 = base64.b64encode(vlm_image_bytes).decode()
    mime = "image/jpeg" if vlm_image_bytes is not image_bytes else (
        "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    )

    client = OpenAI(
        api_key=get_databricks_token(settings),
        base_url=f"{settings.databricks_host}/serving-endpoints",
    )
    try:
        response = client.chat.completions.create(
            model=route,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_vision_prompt()},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=512,
        )
    except Exception as e:  # noqa: BLE001 — surface model errors as 502
        raise HTTPException(status_code=502, detail=f"AI Gateway error: {e}") from e

    raw = response.choices[0].message.content or ""
    try:
        parsed = parse_model_response(raw)
    except ModelResponseError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    result = {
        "scan_id": scan_id,
        "model_route": route,
        "image_volume_path": volume_path,
        "detection_stage": detection_stage,
        **parsed,
    }
    if detections_meta is not None:
        result["detections"] = detections_meta
    return result
