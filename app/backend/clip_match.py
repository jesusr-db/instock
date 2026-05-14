"""CLIP + Vector Search inference module for inStockCV.

Three public functions:
  sam_refine_crop   — EfficientViT-SAM mask refinement (non-fatal, falls back to plain crop)
  clip_encode_image — CLIP ViT-B/32 image embedding via serving endpoint
  clip_search       — VS Direct Access Index nearest-neighbor -> SKU candidates

clip_search return shape: [{"candidate_name": str, "confidence_score": float}]
Same as VLM top_3_sku_candidates — lookup.py requires zero changes.
"""
from __future__ import annotations

import base64
import json
import urllib.request
from io import BytesIO
from typing import TYPE_CHECKING

from databricks.sdk import WorkspaceClient

if TYPE_CHECKING:
    from backend.config import Settings


def sam_refine_crop(
    image_bytes: bytes,
    bbox: tuple[int, int, int, int],
    settings: "Settings",
) -> bytes:
    """Apply SAM box-prompted segmentation mask, return masked JPEG crop.

    Falls back to plain PIL bbox crop if sam_endpoint is empty or call fails.
    """
    from PIL import Image as PILImage

    if not settings.sam_endpoint:
        return _plain_crop(image_bytes, bbox)

    try:
        b64 = base64.b64encode(image_bytes).decode()
        payload = json.dumps({
            "dataframe_records": [{"image": b64, "bbox": json.dumps(list(bbox))}]
        }).encode()
        req = urllib.request.Request(
            f"{settings.databricks_host}/serving-endpoints/{settings.sam_endpoint}/invocations",
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.databricks_token or ''}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            result = json.loads(resp.read())
        mask_b64 = result["predictions"][0]["mask"]
        mask_bytes = base64.b64decode(mask_b64)

        orig = PILImage.open(BytesIO(image_bytes)).convert("RGB")
        mask = PILImage.open(BytesIO(mask_bytes)).convert("L")
        import numpy as np
        orig_np = np.array(orig)
        mask_np = np.array(mask)
        orig_np[mask_np == 0] = 0
        masked = PILImage.fromarray(orig_np)
        buf = BytesIO()
        masked.save(buf, format="JPEG")
        return buf.getvalue()
    except Exception:
        return _plain_crop(image_bytes, bbox)


def _plain_crop(image_bytes: bytes, bbox: tuple[int, int, int, int]) -> bytes:
    from PIL import Image as PILImage
    img = PILImage.open(BytesIO(image_bytes)).convert("RGB")
    x1, y1, x2, y2 = bbox
    w, h = img.size
    x1 = max(0, min(x1, w))
    y1 = max(0, min(y1, h))
    x2 = max(0, min(x2, w))
    y2 = max(0, min(y2, h))
    crop = img.crop((x1, y1, x2, y2)) if x2 > x1 and y2 > y1 else img
    buf = BytesIO()
    crop.save(buf, format="JPEG")
    return buf.getvalue()


def clip_encode_image(image_bytes: bytes, settings: "Settings") -> list[float]:
    """Encode image bytes to a 512-d CLIP embedding via the serving endpoint."""
    b64 = base64.b64encode(image_bytes).decode()
    payload = json.dumps({"dataframe_records": [{"image": b64}]}).encode()
    req = urllib.request.Request(
        f"{settings.databricks_host}/serving-endpoints/{settings.clip_endpoint}/invocations",
        data=payload,
        headers={
            "Authorization": f"Bearer {settings.databricks_token or ''}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    embedding_str = result["predictions"][0]["embedding"]
    return json.loads(embedding_str)


def _query_vs_index(embedding: list[float], settings: "Settings", top_k: int) -> list[dict]:
    """Query VS Direct Access Index via SDK; return list of {combo_key, score} dicts."""
    w = WorkspaceClient()
    response = w.vector_search_indexes.query_index(
        index_name=settings.clip_vs_index_name,
        columns=["combo_key"],
        query_vector=embedding,
        num_results=top_k,
    )
    rows = (response.result.data_array if response.result else None) or []
    return [{"combo_key": row[0], "score": row[-1]} for row in rows]


def clip_search(
    embedding: list[float],
    settings: "Settings",
    top_k: int = 3,
) -> list[dict]:
    """Query VS index with embedding; return top-k SKU candidates.

    Returns [{"candidate_name": str, "confidence_score": float}]
    — same shape as VLM top_3_sku_candidates.
    """
    hits = _query_vs_index(embedding, settings, top_k)
    candidates = []
    for hit in hits:
        combo_key = hit["combo_key"]
        brand, _, variant = combo_key.partition("_")
        brand = brand.replace("_", " ")
        variant = variant.replace("_", " ")
        candidates.append({
            "candidate_name": f"{brand} {variant}",
            "confidence_score": float(hit["score"]),
        })
    return candidates
