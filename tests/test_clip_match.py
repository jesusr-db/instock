"""Unit tests for app/backend/clip_match.py."""
import base64
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("INVENTORY_TABLE", "c.s.inv")
os.environ.setdefault("SCAN_LOG_TABLE", "c.s.scan_log")
os.environ.setdefault("IMAGE_VOLUME_PATH", "/tmp/vol")
os.environ.setdefault("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc")
os.environ.setdefault("CLIP_ENDPOINT", "instockcv-clip")
os.environ.setdefault("CLIP_VS_INDEX_NAME", "cat.sc.instockcv_clip_index")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from backend.config import Settings  # noqa: E402


def _settings(**kwargs) -> Settings:
    base = dict(
        databricks_host="https://host.databricks.com",
        databricks_token="tok",
        inventory_table="c.s.inv",
        scan_log_table="c.s.scan_log",
        image_volume_path="/tmp",
        sql_warehouse_http_path="/sql/1.0/warehouses/abc",
        clip_endpoint="instockcv-clip",
        clip_vs_index_name="cat.sc.instockcv_clip_index",
        sam_endpoint="",
    )
    base.update(kwargs)
    return Settings(**base)


def _tiny_jpeg_b64() -> str:
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()


def test_sam_refine_crop_returns_bytes_without_sam_endpoint():
    """When sam_endpoint is empty, returns the plain bbox crop as bytes."""
    from backend.clip_match import sam_refine_crop

    img_bytes = base64.b64decode(_tiny_jpeg_b64())
    s = _settings(sam_endpoint="")
    result = sam_refine_crop(img_bytes, (0, 0, 1, 1), s)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_sam_refine_crop_falls_back_on_endpoint_error():
    """Even when sam_endpoint is set, an HTTP error falls back to plain crop."""
    from backend.clip_match import sam_refine_crop

    img_bytes = base64.b64decode(_tiny_jpeg_b64())
    s = _settings(sam_endpoint="instockcv-sam")

    with patch("urllib.request.urlopen", side_effect=Exception("timeout")):
        result = sam_refine_crop(img_bytes, (0, 0, 1, 1), s)
    assert isinstance(result, bytes)


def test_clip_encode_image_returns_512d_vector():
    """clip_encode_image returns a list of 512 floats."""
    from backend.clip_match import clip_encode_image

    fake_embedding = [0.1] * 512
    mock_response = json.dumps({"predictions": [{"embedding": json.dumps(fake_embedding)}]})

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_ctx.read.return_value = mock_response.encode()
        mock_urlopen.return_value = mock_ctx

        result = clip_encode_image(base64.b64decode(_tiny_jpeg_b64()), _settings())

    assert isinstance(result, list)
    assert len(result) == 512
    assert all(isinstance(v, float) for v in result)


def test_clip_search_returns_top_3_candidates():
    """clip_search maps VS results to AnalyzeResult-compatible candidate dicts."""
    from backend.clip_match import clip_search

    fake_vs_results = [
        {"combo_key": "Coca-Cola_Original", "score": 0.92},
        {"combo_key": "Pepsi_Original", "score": 0.85},
        {"combo_key": "Coca-Cola_Zero_Sugar", "score": 0.78},
    ]

    with patch("backend.clip_match._query_vs_index", return_value=fake_vs_results):
        results = clip_search([0.0] * 512, _settings(), top_k=3)

    assert len(results) == 3
    assert results[0]["candidate_name"] == "Coca-Cola Original"
    assert results[0]["confidence_score"] == pytest.approx(0.92)
    assert "candidate_name" in results[0]
    assert "confidence_score" in results[0]


def test_clip_search_handles_empty_vs_result():
    """clip_search returns empty list when VS returns nothing."""
    from backend.clip_match import clip_search

    with patch("backend.clip_match._query_vs_index", return_value=[]):
        results = clip_search([0.0] * 512, _settings())

    assert results == []
