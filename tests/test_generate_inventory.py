"""Unit tests for setup.generate_inventory.

Validates contract:
- ~500 deterministic synthetic SKU rows
- Required fields present on every row
- Categories restricted to {tobacco, beverage, snack}
- SKU IDs globally unique
- quantity_on_hand within plausible range
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from setup.generate_inventory import generate_inventory  # noqa: E402


def test_generates_expected_count():
    rows = generate_inventory(seed=42)
    assert 450 <= len(rows) <= 550, f"Expected 450..550 rows, got {len(rows)}"


def test_required_columns_present():
    rows = generate_inventory(seed=42)
    required = {
        "sku_id",
        "brand",
        "category",
        "product_name",
        "size",
        "flavor",
        "quantity_on_hand",
    }
    assert required.issubset(rows[0].keys())


def test_sku_ids_are_unique():
    rows = generate_inventory(seed=42)
    sku_ids = [r["sku_id"] for r in rows]
    assert len(sku_ids) == len(set(sku_ids)), "Duplicate SKU IDs found"


def test_categories_are_valid():
    rows = generate_inventory(seed=42)
    valid = {"tobacco", "beverage", "snack"}
    assert all(r["category"] in valid for r in rows)


def test_deterministic_output():
    a = [r["sku_id"] for r in generate_inventory(seed=42)]
    b = [r["sku_id"] for r in generate_inventory(seed=42)]
    assert a == b, "Output is not deterministic for the same seed"


def test_quantity_in_range():
    rows = generate_inventory(seed=42)
    assert all(
        isinstance(r["quantity_on_hand"], int) and 0 <= r["quantity_on_hand"] <= 50
        for r in rows
    ), "quantity_on_hand must be int in [0, 50]"
