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


# ---------------------------------------------------------------------------
# Brand-gated size scoring — singles vs. multipacks
# ---------------------------------------------------------------------------

DR_PEPPER_INVENTORY = [
    {
        "sku_id": "BEV-DRPE-ORIG-20OZ-1CT",
        "brand": "Dr Pepper",
        "product_name": "Original",
        "size": "20oz 1ct",
        "quantity_on_hand": 8,
    },
    {
        "sku_id": "BEV-DRPE-ORIG-20OZ-24PK",
        "brand": "Dr Pepper",
        "product_name": "Original",
        "size": "20oz 24pk",
        "quantity_on_hand": 2,
    },
    {
        "sku_id": "BEV-DRPE-DIET-20OZ-1CT",
        "brand": "Dr Pepper",
        "product_name": "Diet",
        "size": "20oz 1ct",
        "quantity_on_hand": 5,
    },
    {
        "sku_id": "SNK-DORI-NACH-275Z-1CT",
        "brand": "Doritos",
        "product_name": "Nacho Cheese",
        "size": "2.75oz 1ct",
        "quantity_on_hand": 14,
    },
    {
        "sku_id": "BEV-SPRT-LEMN-20OZ-1CT",
        "brand": "Sprite",
        "product_name": "Lemon Lime",
        "size": "20oz 1ct",
        "quantity_on_hand": 6,
    },
]


def test_fuzzy_match_singles_beats_multipack_with_brand_gate():
    """The bug case: a 20oz Dr Pepper single must beat the 24pk row when
    req_brand and req_size indicate a single."""
    candidates = [
        {"candidate_name": "Dr Pepper Original 20oz", "confidence_score": 0.95},
        {"candidate_name": "Dr Pepper Original 20oz 1ct", "confidence_score": 0.90},
        {"candidate_name": "Dr Pepper Original", "confidence_score": 0.80},
    ]
    match = fuzzy_match_candidates(
        candidates,
        DR_PEPPER_INVENTORY,
        req_brand="Dr Pepper",
        req_size="20oz 1ct",
    )
    assert match is not None
    assert match["sku_id"] == "BEV-DRPE-ORIG-20OZ-1CT"


def test_fuzzy_match_hallucinated_brand_no_size_boost():
    """Regression guard: when req_brand is hallucinated (Doritos for a Sprite
    image), the brand gate must FAIL against non-Doritos rows so size weight
    does NOT push a wrong-brand row above the correct one."""
    candidates = [
        {"candidate_name": "Sprite Lemon Lime 20oz", "confidence_score": 0.55},
        {"candidate_name": "Sprite 20oz", "confidence_score": 0.50},
    ]
    match = fuzzy_match_candidates(
        candidates,
        DR_PEPPER_INVENTORY,
        req_brand="Doritos",
        req_size="20oz 1ct",
    )
    if match is not None:
        assert match["brand"] != "Doritos"


def test_fuzzy_match_brand_none_falls_back_to_token_sort():
    """When req_brand is None the gate fails closed and fuzzy equals the raw
    token_sort_ratio — no size weight applied at all."""
    candidates = [
        {"candidate_name": "Dr Pepper Original 20oz 24pk", "confidence_score": 0.90},
    ]
    match = fuzzy_match_candidates(
        candidates,
        DR_PEPPER_INVENTORY,
        req_brand=None,
        req_size=None,
    )
    assert match is not None
    # Pure token_sort on "Dr Pepper Original 20oz 24pk" picks the 24pk row.
    assert match["sku_id"] == "BEV-DRPE-ORIG-20OZ-24PK"


def test_fuzzy_match_brand_gate_admits_case_punctuation_variants():
    """token_set_ratio handles casing and punctuation drift ('dr. pepper' vs
    'Dr Pepper') — brand gate still passes, and size weight selects Diet 1ct."""
    candidates = [
        {"candidate_name": "Diet Dr Pepper 20oz", "confidence_score": 0.92},
    ]
    match = fuzzy_match_candidates(
        candidates,
        DR_PEPPER_INVENTORY,
        req_brand="dr. pepper",
        req_size="20oz 1ct",
    )
    assert match is not None
    assert match["sku_id"] == "BEV-DRPE-DIET-20OZ-1CT"
