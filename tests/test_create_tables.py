"""Unit tests for setup.create_tables.

Validates DDL string contents and that create_tables() invokes Spark APIs
in the expected order. Does NOT hit a real Spark session.
"""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from setup.create_tables import (  # noqa: E402
    build_ddl_inventory,
    build_ddl_scan_log,
    create_tables,
)


def test_inventory_ddl_has_required_columns():
    ddl = build_ddl_inventory("main", "instockcv")
    required = [
        "sku_id",
        "brand",
        "category",
        "product_name",
        "size",
        "flavor",
        "quantity_on_hand",
    ]
    for col in required:
        assert col in ddl, f"Missing inventory column in DDL: {col}"
    assert "main.instockcv.inventory" in ddl
    # NOT NULL constraint on required columns
    assert "STRING NOT NULL" in ddl
    assert "INT NOT NULL" in ddl


def test_scan_log_ddl_has_required_columns():
    ddl = build_ddl_scan_log("main", "instockcv")
    required = [
        "scan_id",
        "scanned_at",
        "model_route",
        "image_volume_path",
        "model_brand",
        "model_product_name",
        "model_size",
        "matched_sku_id",
        "match_score",
        "quantity_on_hand",
    ]
    for col in required:
        assert col in ddl, f"Missing scan_log column in DDL: {col}"
    assert "main.instockcv.scan_log" in ddl
    assert "TIMESTAMP NOT NULL" in ddl


def test_create_tables_calls_spark_sql():
    mock_spark = MagicMock()
    mock_df = MagicMock()
    mock_spark.createDataFrame.return_value = mock_df
    mock_df.write.mode.return_value.saveAsTable = MagicMock()

    create_tables(mock_spark, "main", "instockcv", seed=42)

    # Collect SQL strings
    sql_calls = [str(c.args[0]) for c in mock_spark.sql.call_args_list]

    # DDL for both tables, schema creation, and volume creation must be issued
    assert any("CREATE SCHEMA" in s for s in sql_calls)
    assert any("inventory" in s for s in sql_calls)
    assert any("scan_log" in s for s in sql_calls)
    assert any("VOLUME" in s and "scan_images" in s for s in sql_calls)

    # Inventory data must be written via overwrite mode
    mock_df.write.mode.assert_called_with("overwrite")
    mock_df.write.mode.return_value.saveAsTable.assert_called_once()
    saved_to = mock_df.write.mode.return_value.saveAsTable.call_args.args[0]
    assert saved_to == "main.instockcv.inventory"
