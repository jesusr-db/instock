"""POST /lookup — fuzzy match against the inventory Delta table.

Receives the parsed model output from /analyze, fetches the live inventory
from the SQL warehouse, fuzzy-matches the top candidates against actual
SKUs, and writes a scan_log row asynchronously via BackgroundTasks.

Combined score = fuzzy_ratio * model_confidence. Threshold 0.50.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import databricks.sql as dbsql
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from backend.config import Settings, get_databricks_token, get_settings

router = APIRouter()


class ConfidenceLabel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


def score_to_label(score: float) -> ConfidenceLabel:
    """Bucket a [0, 1] match score into a confidence label."""
    if score >= 0.85:
        return ConfidenceLabel.HIGH
    if score >= 0.65:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW


def fuzzy_match_candidates(
    candidates: list[dict],
    inventory: list[dict],
    min_score: float = 0.50,
    req_brand: str | None = None,
    req_size: str | None = None,
) -> Optional[dict]:
    """Return the best inventory row matching any candidate, or None.

    Scoring:
      - base = token_sort_ratio(candidate_name, "<brand> <product> <size>") / 100
      - When req_brand passes the brand gate (token_set_ratio >= 0.70) AND
        req_size is provided, fuzzy = 0.60 * base + 0.40 * size_score.
        This distinguishes singles from multipacks within the correct brand.
      - Otherwise fuzzy = base (unchanged behavior). This prevents size weight
        from amplifying cross-brand hallucinations.
      - combined = fuzzy * candidate.confidence_score.
    """
    BRAND_GATE = 0.70
    FULL_WEIGHT = 0.60
    SIZE_WEIGHT = 0.40

    best_combined = 0.0
    best_row: Optional[dict] = None
    brand_gate_cache: dict[str, bool] = {}

    def _brand_passes(row_brand: str) -> bool:
        if not req_brand or not row_brand:
            return False
        if row_brand not in brand_gate_cache:
            ok = fuzz.token_set_ratio(req_brand, row_brand) / 100.0 >= BRAND_GATE
            brand_gate_cache[row_brand] = ok
        return brand_gate_cache[row_brand]

    for candidate in candidates:
        cname = candidate.get("candidate_name", "") or ""
        conf = float(candidate.get("confidence_score", 1.0))
        for row in inventory:
            row_brand = row.get("brand") or ""
            row_size = row.get("size") or ""
            row_str = f"{row_brand} {row.get('product_name', '')} {row_size}"
            base = fuzz.token_sort_ratio(cname, row_str) / 100.0
            if req_size and _brand_passes(row_brand):
                size_score = fuzz.token_set_ratio(req_size, row_size) / 100.0
                fuzzy = FULL_WEIGHT * base + SIZE_WEIGHT * size_score
            else:
                fuzzy = base
            combined = fuzzy * conf
            if combined > best_combined:
                best_combined = combined
                best_row = {**row, "match_score": round(fuzzy, 4)}
    if best_row is None or best_row["match_score"] < min_score:
        return None
    return best_row


def _fetch_inventory(settings: Settings) -> list[dict]:
    """Pull the inventory table via the SQL warehouse."""
    host = settings.databricks_host.replace("https://", "").replace("http://", "")
    with dbsql.connect(
        server_hostname=host,
        http_path=settings.sql_warehouse_http_path,
        access_token=get_databricks_token(settings),
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sku_id, brand, product_name, size, quantity_on_hand "
                f"FROM {settings.inventory_table}"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _write_scan_log(settings: Settings, row: dict) -> None:
    """Append a scan_log row. Failures are non-fatal (logged, then swallowed)."""
    host = settings.databricks_host.replace("https://", "").replace("http://", "")
    try:
        with dbsql.connect(
            server_hostname=host,
            http_path=settings.sql_warehouse_http_path,
            access_token=get_databricks_token(settings),
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {settings.scan_log_table} "
                    "(scan_id, scanned_at, model_route, image_volume_path, "
                    "model_brand, model_product_name, model_size, "
                    "matched_sku_id, match_score, quantity_on_hand) "
                    "VALUES (%(scan_id)s, %(scanned_at)s, %(model_route)s, "
                    "%(image_volume_path)s, %(model_brand)s, "
                    "%(model_product_name)s, %(model_size)s, "
                    "%(matched_sku_id)s, %(match_score)s, %(quantity_on_hand)s)",
                    row,
                )
    except Exception:  # noqa: BLE001 — non-fatal in POC
        pass


class LookupRequest(BaseModel):
    """JSON body for /lookup — mirrors the /analyze response shape."""

    scan_id: str
    model_route: str
    image_volume_path: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    product_name: Optional[str] = None
    size: Optional[str] = None
    flavor: Optional[str] = None
    top_3_sku_candidates: list[dict] = Field(default_factory=list)


@router.post("/lookup")
async def lookup(req: LookupRequest, background_tasks: BackgroundTasks):
    """Match the analyze output against inventory; return SKU + quantity + confidence."""
    settings = get_settings()
    try:
        inventory = _fetch_inventory(settings)
    except Exception as e:  # noqa: BLE001 — surface DB errors as 502
        raise HTTPException(status_code=502, detail=f"Database error: {e}") from e

    match = fuzzy_match_candidates(
        req.top_3_sku_candidates,
        inventory,
        req_brand=req.brand,
        req_size=req.size,
    )

    matched = match is not None
    result = {
        "scan_id": req.scan_id,
        "matched": matched,
        "sku_id": match["sku_id"] if matched else None,
        "product_name": match["product_name"] if matched else req.product_name,
        "brand": match["brand"] if matched else req.brand,
        "size": match["size"] if matched else req.size,
        "quantity_on_hand": match["quantity_on_hand"] if matched else None,
        "match_score": match["match_score"] if matched else 0.0,
        "confidence_label": (
            score_to_label(match["match_score"]).value
            if matched
            else ConfidenceLabel.LOW.value
        ),
    }

    background_tasks.add_task(
        _write_scan_log,
        settings,
        {
            "scan_id": req.scan_id,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "model_route": req.model_route,
            "image_volume_path": req.image_volume_path,
            "model_brand": req.brand,
            "model_product_name": req.product_name,
            "model_size": req.size,
            "matched_sku_id": result["sku_id"],
            "match_score": result["match_score"],
            "quantity_on_hand": result["quantity_on_hand"],
        },
    )
    return result
