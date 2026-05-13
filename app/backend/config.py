"""Backend Settings — typed env var loader for inStockCV.

Single source of truth for all runtime config. Reads from environment
(or `.env` for local dev) via pydantic-settings.

The MODEL_ROUTE default is loaded from `setup/endpoint_name.txt` (written
by genai-architect during Phase 1). If that file is missing, falls back
to the placeholder 'instockcv-gateway' — env var override is required
in production.

DATABRICKS_TOKEN handling:
- Local dev: read from env / .env
- Databricks Apps: not set as env var — the platform exposes
  DATABRICKS_CLIENT_ID + DATABRICKS_CLIENT_SECRET (OAuth m2m) which the
  databricks-sdk picks up. `get_databricks_token()` mints a fresh token
  on demand via WorkspaceClient.config.authenticate().
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

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


def _default_yolo_endpoint() -> str:
    """Read YOLO_ENDPOINT default from setup/yolo_endpoint_name.txt."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "yolo_endpoint_name.txt",
        Path("setup/yolo_endpoint_name.txt"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return "instockcv-yolo"


def _default_clip_endpoint() -> str:
    """Read CLIP_ENDPOINT default from setup/clip_endpoint_name.txt."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "clip_endpoint_name.txt",
        Path("setup/clip_endpoint_name.txt"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return ""


def _default_sam_endpoint() -> str:
    """Read SAM_ENDPOINT default from setup/sam_endpoint_name.txt."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "sam_endpoint_name.txt",
        Path("setup/sam_endpoint_name.txt"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return ""


def _default_clip_vs_index_name() -> str:
    """Read CLIP_VS_INDEX_NAME default from setup/clip_index_name.txt."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "clip_index_name.txt",
        Path("setup/clip_index_name.txt"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return ""


def _default_databricks_host() -> str:
    """Resolve DATABRICKS_HOST, ensuring it has https:// prefix.

    In Databricks Apps the env var is just the hostname (no scheme); the
    OpenAI base_url and other URLs need https://.
    """
    host = os.environ.get("DATABRICKS_HOST", "")
    if host and not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


class Settings(BaseSettings):
    """All runtime config — load from env or `.env`.

    `databricks_token` is optional: when running inside Databricks Apps the
    platform provides OAuth m2m credentials instead, and `get_databricks_token()`
    mints a token on demand via the SDK.
    """

    databricks_host: str = ""  # resolved by _resolve_host_with_scheme below
    databricks_token: Optional[str] = None
    model_route: str = _default_model_route()
    inventory_table: str
    scan_log_table: str
    image_volume_path: str
    sql_warehouse_http_path: str
    use_detection_stage: bool = False
    # Default resolved at import time from setup/yolo_endpoint_name.txt;
    # override with YOLO_ENDPOINT env var in production.
    yolo_endpoint: str = _default_yolo_endpoint()
    yolo_confidence_threshold: float = 0.3
    clip_endpoint: str = _default_clip_endpoint()
    sam_endpoint: str = _default_sam_endpoint()
    clip_vs_index_name: str = _default_clip_vs_index_name()

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Allow extra env vars without raising
        extra="ignore",
    )

    def model_post_init(self, _ctx) -> None:
        # Ensure host always has https:// scheme
        if self.databricks_host and not self.databricks_host.startswith(
            ("http://", "https://")
        ):
            object.__setattr__(self, "databricks_host", f"https://{self.databricks_host}")
        elif not self.databricks_host:
            # Pick up DATABRICKS_HOST late if Settings was built without it
            object.__setattr__(self, "databricks_host", _default_databricks_host())


def get_databricks_token(settings: "Settings") -> str:
    """Return a Bearer token for Databricks API calls.

    Prefers the explicit `DATABRICKS_TOKEN` env var; falls back to minting
    one via the SDK's unified auth (works for OAuth m2m in Databricks Apps).
    """
    if settings.databricks_token:
        return settings.databricks_token
    # Lazy import — SDK is heavy and not needed in tests that use a token env var
    from databricks.sdk import WorkspaceClient

    headers = WorkspaceClient().config.authenticate()
    auth = headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :]
    raise RuntimeError(
        "Could not obtain a Databricks token: set DATABRICKS_TOKEN or run in an "
        "environment where the databricks-sdk can authenticate (Databricks Apps "
        "auto-provisions OAuth m2m credentials)."
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
