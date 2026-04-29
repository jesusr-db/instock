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
