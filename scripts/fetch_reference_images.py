# scripts/fetch_reference_images.py
"""One-time script: download reference images for all brand×variant combos."""
from __future__ import annotations
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image
from io import BytesIO

TOBACCO: list[tuple[str, list[str]]] = [
    ("Marlboro", ["Red", "Gold", "Silver", "Black", "Menthol"]),
    ("Newport", ["Menthol", "Red", "Gold"]),
    ("Camel", ["Blue", "Filters", "Menthol", "Turkish Silver"]),
    ("Winston", ["Red", "Blue", "Gold", "White"]),
    ("Pall Mall", ["Red", "Blue", "Menthol", "Orange", "Black"]),
    ("Kool", ["Menthol", "Super Longs"]),
    ("American Spirit", ["Yellow", "Blue", "Orange", "Green"]),
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
SNACKS: list[tuple[str, list[str]]] = [
    ("Lays", ["Classic", "BBQ", "Sour Cream & Onion", "Salt & Vinegar", "Cheddar"]),
    ("Doritos", ["Nacho Cheese", "Cool Ranch", "Spicy Nacho", "Flamin Hot"]),
    ("Cheetos", ["Crunchy", "Puffs", "Flamin Hot", "Baked"]),
    ("Fritos", ["Original", "BBQ", "Honey BBQ"]),
    ("Pringles", ["Original", "Sour Cream & Onion", "BBQ", "Cheddar", "Pizza"]),
]

CATEGORY_MAP = [("tobacco", TOBACCO), ("beverage", BEVERAGES), ("snack", SNACKS)]

HEADERS = {"User-Agent": "inStockCV-reference-fetch/1.0 (jesus.rodriguez@databricks.com)"}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _combo_key(brand: str, variant: str) -> str:
    safe_brand = re.sub(r"[^A-Za-z0-9 ]", "", brand).replace(" ", "_")
    safe_variant = re.sub(r"[^A-Za-z0-9 ]", "", variant).replace(" ", "_")
    return f"{safe_brand}_{safe_variant}"


def _try_open_food_facts(brand: str, variant: str) -> str | None:
    query = f"{brand} {variant}"
    url = (
        "https://world.openfoodfacts.org/cgi/search.pl"
        f"?search_terms={requests.utils.quote(query)}"
        "&search_simple=1&action=process&json=1&page_size=5"
    )
    try:
        r = SESSION.get(url, timeout=10)
        r.raise_for_status()
        products = r.json().get("products", [])
        for p in products:
            img = p.get("image_front_url") or p.get("image_url")
            if img and img.startswith("http"):
                return img
    except Exception as e:
        print(f"    OFF error for {brand} {variant}: {e}")
    return None


def _try_wikimedia(brand: str, variant: str) -> str | None:
    query = f"{brand} {variant} product"
    url = (
        "https://en.wikipedia.org/w/api.php"
        "?action=query&generator=search&gsrnamespace=6"
        f"&gsrsearch={requests.utils.quote(query)}&gsrlimit=5"
        "&prop=imageinfo&iiprop=url&format=json"
    )
    try:
        r = SESSION.get(url, timeout=10)
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        for page in pages.values():
            infos = page.get("imageinfo", [])
            if infos and infos[0].get("url", "").startswith("http"):
                return infos[0]["url"]
    except Exception as e:
        print(f"    Wiki error for {brand} {variant}: {e}")
    return None


def _download_image(img_url: str, dest_path: Path) -> bool:
    try:
        r = SESSION.get(img_url, timeout=15)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        img.save(str(dest_path), format="JPEG", quality=85)
        return True
    except Exception as e:
        print(f"    Download failed: {e}")
        return False


def main() -> None:
    root = Path(__file__).resolve().parent.parent / "reference_images"
    manifest: dict[str, dict | list] = {
        "tobacco": {}, "beverage": {}, "snack": {}, "skipped": []
    }
    total = found = 0

    for category, catalog in CATEGORY_MAP:
        cat_dir = root / category
        cat_dir.mkdir(parents=True, exist_ok=True)
        for brand, variants in catalog:
            for variant in variants:
                total += 1
                key = _combo_key(brand, variant)
                dest = cat_dir / f"{key}.jpg"
                if dest.exists():
                    print(f"  [cached] {key}")
                    manifest[category][key] = str(dest.relative_to(root.parent))
                    found += 1
                    continue

                print(f"  Fetching {brand} {variant}...")
                img_url = _try_open_food_facts(brand, variant)
                source = "OFF"
                if not img_url:
                    time.sleep(0.3)
                    img_url = _try_wikimedia(brand, variant)
                    source = "Wiki"

                if img_url and _download_image(img_url, dest):
                    print(f"    saved via {source} -> {dest.name}")
                    manifest[category][key] = str(dest.relative_to(root.parent))
                    found += 1
                else:
                    print(f"    skipped")
                    manifest["skipped"].append(key)
                time.sleep(0.5)

    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nDone: {found}/{total} images downloaded, {len(manifest['skipped'])} skipped")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
