"""Unit tests for app.backend.lookup.

Validates fuzzy-matching behavior, threshold semantics, and confidence
label mapping. Does NOT hit a real SQL warehouse.
"""
import os
import sys

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

from backend.lookup import (  # noqa: E402
    ConfidenceLabel,
    fuzzy_match_candidates,
    score_to_label,
)


INVENTORY = [
    {
        "sku_id": "TOB-MARL-RED-KING",
        "brand": "Marlboro",
        "product_name": "Marlboro Red",
        "size": "King Size 20-pack",
        "quantity_on_hand": 15,
    },
    {
        "sku_id": "BEV-PEPS-ZERO-20OZ",
        "brand": "Pepsi",
        "product_name": "Pepsi Zero Sugar",
        "size": "20oz",
        "quantity_on_hand": 3,
    },
    {
        "sku_id": "SNK-LAYS-CLAS-1OZ",
        "brand": "Lays",
        "product_name": "Lays Classic",
        "size": "1oz",
        "quantity_on_hand": 0,
    },
]


def test_matches_exact_brand_product():
    candidates = [
        {"candidate_name": "Marlboro Red King Size 20-pack", "confidence_score": 0.95}
    ]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert result is not None
    assert result["sku_id"] == "TOB-MARL-RED-KING"


def test_matches_partial_name():
    candidates = [{"candidate_name": "Pepsi Zero 20oz", "confidence_score": 0.88}]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert result is not None
    assert result["sku_id"] == "BEV-PEPS-ZERO-20OZ"


def test_returns_none_when_below_threshold():
    candidates = [
        {"candidate_name": "Xyz Unknown Widget Brand", "confidence_score": 0.10}
    ]
    result = fuzzy_match_candidates(candidates, INVENTORY, min_score=0.99)
    assert result is None


def test_result_includes_match_score():
    candidates = [{"candidate_name": "Marlboro Red King", "confidence_score": 0.90}]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert result is not None
    assert "match_score" in result
    assert 0.0 <= result["match_score"] <= 1.0


def test_score_to_label_high():
    assert score_to_label(0.90) == ConfidenceLabel.HIGH


def test_score_to_label_medium():
    assert score_to_label(0.75) == ConfidenceLabel.MEDIUM


def test_score_to_label_low():
    assert score_to_label(0.50) == ConfidenceLabel.LOW
