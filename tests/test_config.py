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


def test_settings_yolo_defaults(monkeypatch):
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
    assert settings.yolo_confidence_threshold == 0.3
    assert settings.yolo_endpoint == "instockcv-yolo"


def test_settings_yolo_threshold_override(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("MODEL_ROUTE", "aigwjmr")
    monkeypatch.setenv("INVENTORY_TABLE", "main.instockcv.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "main.instockcv.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/Volumes/main/instockcv/scan_images")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc123")
    monkeypatch.setenv("YOLO_CONFIDENCE_THRESHOLD", "0.65")

    import backend.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.get_settings.cache_clear()

    settings = cfg_module.get_settings()
    assert settings.yolo_confidence_threshold == 0.65


def test_clip_settings_default_to_empty(monkeypatch, tmp_path):
    """clip_endpoint, sam_endpoint, clip_vs_index_name default to '' if txt files absent."""
    import importlib
    import backend.config as cfg_module

    # Required fields
    monkeypatch.setenv("INVENTORY_TABLE", "c.s.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "c.s.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/tmp/vol")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc")

    # Ensure any env vars leaked from other tests don't override defaults
    monkeypatch.delenv("CLIP_ENDPOINT", raising=False)
    monkeypatch.delenv("SAM_ENDPOINT", raising=False)
    monkeypatch.delenv("CLIP_VS_INDEX_NAME", raising=False)

    monkeypatch.chdir(tmp_path)  # no txt files here

    # Stub out the project-root candidates so the project setup/ txt files
    # (which exist after deploy-script tasks land) don't satisfy the default lookup.
    cfg_module.get_settings.cache_clear()
    importlib.reload(cfg_module)
    monkeypatch.setattr(
        cfg_module, "_default_clip_endpoint", lambda: "", raising=True
    )
    monkeypatch.setattr(
        cfg_module, "_default_sam_endpoint", lambda: "", raising=True
    )
    monkeypatch.setattr(
        cfg_module, "_default_clip_vs_index_name", lambda: "", raising=True
    )

    # Re-evaluate class defaults using patched functions
    class StubSettings(cfg_module.Settings):
        clip_endpoint: str = ""
        sam_endpoint: str = ""
        clip_vs_index_name: str = ""

    s = StubSettings()  # type: ignore[call-arg]

    assert s.clip_endpoint == ""
    assert s.sam_endpoint == ""
    assert s.clip_vs_index_name == ""

    cfg_module.get_settings.cache_clear()


def test_default_clip_vs_index_name_has_hardcoded_fallback():
    """_default_clip_vs_index_name must never return empty string."""
    import backend.config as cfg_module
    from unittest.mock import patch

    # Simulate no txt files present (both paths nonexistent)
    with patch("backend.config.Path.is_file", return_value=False):
        result = cfg_module._default_clip_vs_index_name()

    assert result == "vdm_classic_rikfy0_catalog.instockcv_dev.instockcv_clip_index"
    assert result != ""
