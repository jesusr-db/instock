"""Unit tests for app.backend.config Settings.

Validates that env vars resolve to a typed Settings object via pydantic-settings.
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))


def test_settings_loads_env_vars(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("MODEL_ROUTE", "aigwjmr")
    monkeypatch.setenv("INVENTORY_TABLE", "main.instockcv.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "main.instockcv.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/Volumes/main/instockcv/scan_images")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc123")

    import backend.config as cfg_module

    importlib.reload(cfg_module)
    cfg_module.get_settings.cache_clear()

    settings = cfg_module.get_settings()
    assert settings.databricks_host == "https://test.azuredatabricks.net"
    assert settings.model_route == "aigwjmr"
    assert settings.inventory_table == "main.instockcv.inventory"
    assert settings.scan_log_table == "main.instockcv.scan_log"
    assert settings.image_volume_path == "/Volumes/main/instockcv/scan_images"
    assert settings.sql_warehouse_http_path == "/sql/1.0/warehouses/abc123"
    assert settings.use_detection_stage is False  # default
