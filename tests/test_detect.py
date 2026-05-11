"""Unit tests for app.backend.detect."""
import os
import sys
from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image

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

from backend.config import get_settings  # noqa: E402
from backend.detect import DetectedCrop, detect_products  # noqa: E402


def _make_test_image(width: int = 100, height: int = 100) -> bytes:
    """Return minimal JPEG bytes for a solid-color test image."""
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_query_response(detections: list[dict]):
    """Build a mock SDK QueryEndpointResponse with the given detections."""
    response = MagicMock()
    response.predictions = [{"detections": detections}]
    return response


def test_detect_products_returns_sorted_by_confidence():
    settings = get_settings()
    image_bytes = _make_test_image(200, 200)

    raw = [
        {"bbox": [10, 10, 50, 50], "confidence": 0.6, "class": "product"},
        {"bbox": [60, 60, 120, 120], "confidence": 0.9, "class": "product"},
        {"bbox": [130, 10, 180, 60], "confidence": 0.75, "class": "product"},
    ]

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response(raw)
        crops = detect_products(image_bytes, settings)

    assert len(crops) == 3
    assert crops[0].confidence == 0.9
    assert crops[1].confidence == 0.75
    assert crops[2].confidence == 0.6
    assert crops[0].crop_index == 0
    assert crops[1].crop_index == 1
    assert crops[2].crop_index == 2


def test_detect_products_returns_cropped_jpeg_bytes():
    settings = get_settings()
    image_bytes = _make_test_image(200, 200)

    raw = [{"bbox": [10, 10, 80, 80], "confidence": 0.85, "class": "product"}]

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response(raw)
        crops = detect_products(image_bytes, settings)

    assert len(crops) == 1
    crop = crops[0]
    assert isinstance(crop.image_bytes, bytes)
    # Verify it's a valid image
    decoded = Image.open(BytesIO(crop.image_bytes))
    assert decoded.size == (70, 70)  # bbox is 10→80 = 70px wide and tall
    assert crop.bbox == (10, 10, 80, 80)


def test_detect_products_returns_empty_on_no_detections():
    settings = get_settings()
    image_bytes = _make_test_image()

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response([])
        crops = detect_products(image_bytes, settings)

    assert crops == []


def test_detect_products_returns_empty_on_endpoint_error():
    settings = get_settings()
    image_bytes = _make_test_image()

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.side_effect = Exception("endpoint unavailable")
        crops = detect_products(image_bytes, settings)

    assert crops == []


def test_detected_crop_dataclass_fields():
    crop = DetectedCrop(
        crop_index=0,
        bbox=(10, 20, 100, 200),
        confidence=0.88,
        image_bytes=b"fake",
    )
    assert crop.crop_index == 0
    assert crop.bbox == (10, 20, 100, 200)
    assert crop.confidence == 0.88
    assert crop.image_bytes == b"fake"


def test_detect_products_filters_below_threshold():
    settings = get_settings()
    image_bytes = _make_test_image(200, 200)

    raw = [
        {"bbox": [10, 10, 50, 50], "confidence": 0.15, "class": "product"},
        {"bbox": [60, 60, 120, 120], "confidence": 0.05, "class": "product"},
    ]

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response(raw)
        crops = detect_products(image_bytes, settings)

    # Default threshold is 0.3; both detections are below it
    assert crops == []
