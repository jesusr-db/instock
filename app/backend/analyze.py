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
        "If no product is visible, return brand=null and an empty top_3_sku_candidates array."
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
):
    """Vision inference endpoint.

    Body: multipart/form-data with `file` (image) and optional `model_route`.
    Returns: scan_id, model_route, image_volume_path, brand, category,
             product_name, size, flavor, top_3_sku_candidates.
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

    b64 = base64.b64encode(image_bytes).decode()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

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

    return {
        "scan_id": scan_id,
        "model_route": route,
        "image_volume_path": volume_path,
        **parsed,
    }
