"""Tests for the CLIP inference_mode branch in /analyze."""
import base64
import json
import os
import sys
from io import BytesIO
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("INVENTORY_TABLE", "c.s.inv")
os.environ.setdefault("SCAN_LOG_TABLE", "c.s.scan_log")
os.environ.setdefault("IMAGE_VOLUME_PATH", "/tmp/vol")
os.environ.setdefault("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc")
os.environ.setdefault("CLIP_ENDPOINT", "instockcv-clip")
os.environ.setdefault("CLIP_VS_INDEX_NAME", "cat.sc.instockcv_clip_index")
os.environ.setdefault("DATABRICKS_TOKEN", "tok")
os.environ.setdefault("DATABRICKS_HOST", "https://host.db.com")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from fastapi.testclient import TestClient  # noqa: E402
from backend.main import app as fastapi_app  # noqa: E402
from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()
client = TestClient(fastapi_app)


def _tiny_jpeg() -> bytes:
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (10, 10), color=(200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def clear_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_analyze_clip_mode_returns_clip_model_route():
    """inference_mode=clip returns model_route='clip' in the response."""
    fake_candidates = [
        {"candidate_name": "Dr Pepper Original", "confidence_score": 0.91},
        {"candidate_name": "Pepsi Original", "confidence_score": 0.72},
        {"candidate_name": "Coca-Cola Original", "confidence_score": 0.65},
    ]

    with patch("backend.clip_match.sam_refine_crop", return_value=_tiny_jpeg()), \
         patch("backend.clip_match.clip_encode_image", return_value=[0.1] * 512), \
         patch("backend.clip_match.clip_search", return_value=fake_candidates):

        resp = client.post(
            "/analyze",
            data={"inference_mode": "clip"},
            files={"file": ("test.jpg", _tiny_jpeg(), "image/jpeg")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["model_route"] == "clip"
    assert len(body["top_3_sku_candidates"]) == 3
    assert body["top_3_sku_candidates"][0]["candidate_name"] == "Dr Pepper Original"


def test_analyze_vlm_mode_unchanged():
    """inference_mode=vlm (default) still calls OpenAI, not clip_match."""
    fake_vlm_response = json.dumps({
        "brand": "Dr Pepper",
        "category": "beverage",
        "product_name": "Dr Pepper Original",
        "size": "20oz 1ct",
        "flavor": None,
        "top_3_sku_candidates": [
            {"candidate_name": "Dr Pepper Original 20oz 1ct", "confidence_score": 0.95}
        ],
    })
    mock_choice = MagicMock()
    mock_choice.message.content = fake_vlm_response
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    with patch("backend.analyze.OpenAI") as mock_openai_cls:
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_completion
        mock_openai_cls.return_value = mock_client

        resp = client.post(
            "/analyze",
            data={"inference_mode": "vlm"},
            files={"file": ("test.jpg", _tiny_jpeg(), "image/jpeg")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["model_route"] != "clip"
    assert body["brand"] == "Dr Pepper"
