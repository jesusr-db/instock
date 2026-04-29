"""Synthetic retail inventory generator for inStockCV.

Pure function (stdlib only). Returns ~500 deterministic SKU rows across
three categories: tobacco, beverage, snack. Used by setup/create_tables.py
to populate the `inventory` Delta table.

Contract:
- 450 <= len(rows) <= 550
- Each row has: sku_id, brand, category, product_name, size, flavor (nullable), quantity_on_hand
- All sku_ids globally unique
- Same seed produces identical output
"""
from __future__ import annotations

import random
from typing import Optional

# Brand catalogs: (brand_name, [variants])
TOBACCO: list[tuple[str, list[str]]] = [
    ("Marlboro", ["Red", "Gold", "Silver", "Black", "Menthol"]),
    ("Newport", ["Menthol", "Red", "Gold"]),
    ("Camel", ["Blue", "Filters", "Menthol", "Turkish Silver"]),
    ("Winston", ["Red", "Blue", "Gold", "White"]),
    ("Pall Mall", ["Red", "Blue", "Menthol", "Orange", "Black"]),
    ("Kool", ["Menthol", "Super Longs"]),
    ("American Spirit", ["Yellow", "Blue", "Orange", "Green"]),
]
TOBACCO_SIZES = [
    "King Size 20-pack",
    "King Size 25-pack",
    "100s 20-pack",
    "Soft Pack 20-pack",
]

BEVERAGES: list[tuple[str, list[str]]] = [
    ("Coca-Cola", ["Original", "Zero Sugar", "Cherry", "Vanilla", "Starlight"]),
    ("Pepsi", ["Original", "Zero Sugar", "Wild Cherry", "Mango"]),
    ("Red Bull", ["Original", "Sugar Free", "Blue Edition", "Red Edition"]),
    ("Monster", ["Original", "Ultra White", "Mango Loco", "Zero Ultra"]),
    ("Gatorade", ["Lemon Lime", "Fruit Punch", "Orange", "Cool Blue"]),
    ("Powerade", ["Mountain Berry Blast", "Fruit Punch", "Orange", "Grape"]),
    ("Sprite", ["Original", "Zero Sugar", "Cranberry"]),
    ("Dr Pepper", ["Original", "Zero Sugar", "Cherry"]),
]
BEVERAGE_SIZES = ["12oz", "20oz", "16oz", "2L", "1L", "8.4oz", "24oz"]

SNACKS: list[tuple[str, list[str]]] = [
    ("Lays", ["Classic", "BBQ", "Sour Cream & Onion", "Salt & Vinegar", "Cheddar"]),
    ("Doritos", ["Nacho Cheese", "Cool Ranch", "Spicy Nacho", "Flamin Hot"]),
    ("Cheetos", ["Crunchy", "Puffs", "Flamin Hot", "Baked"]),
    ("Fritos", ["Original", "BBQ", "Honey BBQ"]),
    ("Pringles", ["Original", "Sour Cream & Onion", "BBQ", "Cheddar", "Pizza"]),
]
SNACK_SIZES = ["1oz", "1.5oz", "2.75oz", "8oz", "13.5oz"]

# Variants whose name implies a flavor (used to populate the nullable `flavor` field)
_FLAVOR_KEYWORDS = {
    "menthol",
    "cherry",
    "vanilla",
    "mango",
    "berry",
    "lemon",
    "orange",
    "grape",
    "punch",
    "lime",
    "peach",
    "tropical",
    "cranberry",
    "starlight",
}

_CATEGORY_CODE = {"tobacco": "TOB", "beverage": "BEV", "snack": "SNK"}

# Pack counts add realistic SKU variation (single, 6-pack, 12-pack carton, etc.)
TOBACCO_PACK_COUNTS = ["1ct", "10ct"]   # single pack, full carton
BEVERAGE_PACK_COUNTS = ["1ct", "6pk", "12pk", "24pk"]
SNACK_PACK_COUNTS = ["1ct", "6pk", "12pk"]


def _sku(category: str, brand: str, variant: str, size: str, pack: str) -> str:
    """Deterministic SKU id from product attributes."""
    return (
        f"{_CATEGORY_CODE[category]}-"
        f"{brand.replace(' ', '').replace('-', '')[:4].upper()}-"
        f"{variant.replace(' ', '').replace('&', '')[:4].upper()}-"
        f"{size.replace(' ', '').replace('.', '').replace('-', '')[:5].upper()}-"
        f"{pack.upper()}"
    )


def _flavor_for(variant: str) -> Optional[str]:
    """Return the variant name as the flavor if it matches a known flavor keyword."""
    lowered = variant.lower()
    if any(kw in lowered for kw in _FLAVOR_KEYWORDS):
        return variant
    return None


def _fill(
    rng: random.Random,
    category: str,
    products: list[tuple[str, list[str]]],
    sizes: list[str],
    pack_counts: list[str],
    target: int,
    rows: list[dict],
    seen: set[str],
) -> None:
    attempts = 0
    cap = target * 30
    while sum(1 for r in rows if r["category"] == category) < target and attempts < cap:
        attempts += 1
        brand, variants = rng.choice(products)
        variant = rng.choice(variants)
        size = rng.choice(sizes)
        pack = rng.choice(pack_counts)
        sku = _sku(category, brand, variant, size, pack)
        if sku in seen:
            continue
        seen.add(sku)
        # When pack > 1, append pack count to the size (more realistic display)
        display_size = size if pack == "1ct" else f"{size} ({pack})"
        rows.append(
            {
                "sku_id": sku,
                "brand": brand,
                "category": category,
                "product_name": f"{brand} {variant}",
                "size": display_size,
                "flavor": _flavor_for(variant),
                "quantity_on_hand": rng.randint(0, 50),
            }
        )


def generate_inventory(seed: int = 42) -> list[dict]:
    """Generate ~500 synthetic retail inventory rows.

    Args:
        seed: RNG seed for deterministic output.

    Returns:
        List of dicts, each with keys: sku_id, brand, category, product_name,
        size, flavor (Optional[str]), quantity_on_hand (int).
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    seen: set[str] = set()

    # Targets sum to 500; combinatorial space (with pack counts) is ~1300, well above target.
    _fill(rng, "tobacco", TOBACCO, TOBACCO_SIZES, TOBACCO_PACK_COUNTS, 200, rows, seen)
    _fill(rng, "beverage", BEVERAGES, BEVERAGE_SIZES, BEVERAGE_PACK_COUNTS, 200, rows, seen)
    _fill(rng, "snack", SNACKS, SNACK_SIZES, SNACK_PACK_COUNTS, 100, rows, seen)
    return rows


if __name__ == "__main__":
    inv = generate_inventory()
    print(f"Generated {len(inv)} inventory rows")
    print(f"First row: {inv[0]}")
