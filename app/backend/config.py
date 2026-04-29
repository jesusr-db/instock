"""Backend Settings — typed env var loader for inStockCV.

Single source of truth for all runtime config. Reads from environment
(or `.env` for local dev) via pydantic-settings.

The MODEL_ROUTE default is loaded from `setup/endpoint_name.txt` (written
by genai-architect during Phase 1). If that file is missing, falls back
to the placeholder 'instockcv-gateway' — env var override is required
in production.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_model_route() -> str:
    """Read MODEL_ROUTE default from setup/endpoint_name.txt."""
    # Project root is two levels up from this file (app/backend/config.py)
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "endpoint_name.txt",
        Path("setup/endpoint_name.txt"),  # cwd-relative fallback
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return "instockcv-gateway"  # placeholder; env var override expected


class Settings(BaseSettings):
    """All runtime config — load from env or `.env`."""

    databricks_host: str
    databricks_token: str
    model_route: str = _default_model_route()
    inventory_table: str
    scan_log_table: str
    image_volume_path: str
    sql_warehouse_http_path: str
    use_detection_stage: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Allow extra env vars without raising
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Cached factory — call this from FastAPI dependencies / handlers."""
    return Settings()  # type: ignore[call-arg]


# Convenience for ad-hoc CLI inspection
if __name__ == "__main__":
    s = get_settings()
    print(f"model_route        = {s.model_route}")
    print(f"inventory_table    = {s.inventory_table}")
    print(f"scan_log_table     = {s.scan_log_table}")
    print(f"image_volume_path  = {s.image_volume_path}")
