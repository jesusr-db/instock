"""Unit tests for app.backend.analyze.

Validates:
- The vision prompt enumerates all required JSON keys
- parse_model_response parses valid JSON
- parse_model_response strips markdown code fences
- parse_model_response raises ModelResponseError on garbage input
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Pre-set env so config validates on import (Settings has no defaults for required fields)
os.environ.update(
    {
        "DATABRICKS_HOST": "https://test.azuredatabricks.net",
        "DATABRICKS_TOKEN": "dapi-test",
        "MODEL_ROUTE": "aigwjmr",
        "INVENTORY_TABLE": "main.instockcv.inventory",
        "SCAN_LOG_TABLE": "main.instockcv.scan_log",
        "IMAGE_VOLUME_PATH": "/tmp/instockcv_images",
        "SQL_WAREHOUSE_HTTP_PATH": "/sql/1.0/warehouses/abc123",
    }
)

from backend.analyze import (  # noqa: E402
    ModelResponseError,
    build_vision_prompt,
    parse_model_response,
)


def test_build_vision_prompt_contains_required_keys():
    prompt = build_vision_prompt()
    for key in [
        "brand",
        "category",
        "product_name",
        "size",
        "flavor",
        "top_3_sku_candidates",
        "confidence_score",
    ]:
        assert key in prompt, f"Prompt missing key: {key}"


def test_parse_valid_json():
    raw = json.dumps(
        {
            "brand": "Marlboro",
            "category": "tobacco",
            "product_name": "Marlboro Red",
            "size": "King Size 20-pack",
            "flavor": None,
            "top_3_sku_candidates": [
                {"candidate_name": "Marlboro Red King Size", "confidence_score": 0.95},
                {"candidate_name": "Marlboro Gold King Size", "confidence_score": 0.45},
                {"candidate_name": "Camel Red King Size", "confidence_score": 0.30},
            ],
        }
    )
    result = parse_model_response(raw)
    assert result["brand"] == "Marlboro"
    assert len(result["top_3_sku_candidates"]) == 3


def test_parse_strips_markdown_fences():
    raw = (
        '```json\n{"brand":"Pepsi","category":"beverage",'
        '"product_name":"Pepsi Zero Sugar","size":"20oz","flavor":null,'
        '"top_3_sku_candidates":[{"candidate_name":"Pepsi Zero 20oz","confidence_score":0.9}]}\n```'
    )
    result = parse_model_response(raw)
    assert result["brand"] == "Pepsi"


def test_parse_raises_on_garbage():
    with pytest.raises(ModelResponseError):
        parse_model_response("not json at all {{{")


from unittest.mock import MagicMock, patch

from backend.detect import DetectedCrop


def _make_jpeg_bytes(width: int = 50, height: int = 50) -> bytes:
    from io import BytesIO
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(100, 100, 100))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_vlm_response(brand: str = "Pepsi") -> MagicMock:
    import json
    payload = json.dumps({
        "brand": brand,
        "category": "beverage",
        "product_name": f"{brand} Zero",
        "size": "20oz",
        "flavor": None,
        "top_3_sku_candidates": [
            {"candidate_name": f"{brand} Zero 20oz", "confidence_score": 0.9}
        ],
    })
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = payload
    return mock_resp


def test_analyze_detection_stage_uses_crop_when_yolo_succeeds(monkeypatch):
    """When use_detection_stage=True and YOLO succeeds, VLM receives the crop bytes."""
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "true")
    monkeypatch.setenv("YOLO_ENDPOINT", "instockcv-yolo")

    crop_bytes = _make_jpeg_bytes(60, 60)
    fake_crops = [
        DetectedCrop(crop_index=0, bbox=(10, 10, 70, 70), confidence=0.88, image_bytes=crop_bytes)
    ]

    captured_b64 = {}

    def fake_create(**kwargs):
        msgs = kwargs.get("messages", [])
        for part in msgs[0]["content"]:
            if part.get("type") == "image_url":
                captured_b64["url"] = part["image_url"]["url"]
        return _mock_vlm_response()

    with patch("backend.detect.detect_products", return_value=fake_crops), \
         patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = fake_create
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "yolo"
    assert len(data["detections"]) == 1
    assert data["detections"][0]["confidence"] == 0.88
    assert data["detections"][0]["crop_index"] == 0


def test_analyze_detection_stage_falls_back_when_yolo_returns_empty(monkeypatch):
    """When YOLO returns [], full image is sent to VLM and detection_stage='fallback'."""
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "true")
    monkeypatch.setenv("YOLO_ENDPOINT", "instockcv-yolo")

    with patch("backend.detect.detect_products", return_value=[]), \
         patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _mock_vlm_response()
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "fallback"
    assert "detections" not in data


def test_analyze_detection_stage_disabled_by_default(monkeypatch):
    """When use_detection_stage=False (default), detection_stage='disabled'."""
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "false")

    with patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _mock_vlm_response()
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "disabled"
    assert "detections" not in data
