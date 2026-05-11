# tests/test_detect_route.py
"""Tests for POST /detect endpoint."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

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

from fastapi.testclient import TestClient  # noqa: E402

from backend.detect import DetectedCrop  # noqa: E402
from backend.main import app  # noqa: E402

client = TestClient(app)


def _jpeg_bytes(w: int = 50, h: int = 50) -> bytes:
    from io import BytesIO

    from PIL import Image

    img = Image.new("RGB", (w, h), color=(100, 100, 100))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_detect_returns_crops_shape_when_yolo_succeeds():
    fake_crops = [
        DetectedCrop(crop_index=0, bbox=(10, 10, 80, 80), confidence=0.87, image_bytes=_jpeg_bytes()),
        DetectedCrop(crop_index=1, bbox=(90, 90, 150, 150), confidence=0.62, image_bytes=_jpeg_bytes()),
    ]
    with patch("backend.detect_route.detect_products", return_value=fake_crops):
        resp = client.post("/detect", files={"file": ("img.jpg", _jpeg_bytes(), "image/jpeg")})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["crops"]) == 2
    c = data["crops"][0]
    assert c["crop_index"] == 0
    assert c["bbox"] == [10, 10, 80, 80]
    assert c["confidence"] == pytest.approx(0.87)


def test_detect_returns_empty_crops_when_yolo_finds_nothing():
    with patch("backend.detect_route.detect_products", return_value=[]):
        resp = client.post("/detect", files={"file": ("img.jpg", _jpeg_bytes(), "image/jpeg")})
    assert resp.status_code == 200
    assert resp.json() == {"crops": []}


def test_detect_always_returns_200_even_when_yolo_returns_empty():
    """detect_products handles all exceptions internally — /detect must never 500."""
    with patch("backend.detect_route.detect_products", return_value=[]):
        resp = client.post("/detect", files={"file": ("img.jpg", _jpeg_bytes(), "image/jpeg")})
    assert resp.status_code == 200
