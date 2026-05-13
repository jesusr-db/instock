"""Tear down all inStockCV non-DAB artifacts (reverse dependency order).

Run as a Spark Python task in destroy_job. Safe to re-run — every step is
non-fatal so a partial teardown doesn't block subsequent steps.

Deletion order:
  1. Vector Search index (instockcv_clip_index)
  2. Model serving endpoints (instockcv-sam, instockcv-clip, instockcv-yolo)
  3. UC registered models (all versions, then the model registration)
  4. DROP SCHEMA CASCADE (removes inventory, scan_log, sku_clip_embeddings, scan_images volume)

Usage:
    python teardown.py --catalog vdm_classic_rikfy0_catalog --schema instockcv_dev
"""
from __future__ import annotations

import argparse
import sys


SERVING_ENDPOINTS = ["instockcv-sam", "instockcv-clip", "instockcv-yolo"]

UC_MODELS = ["sam_shelf_segmenter", "clip_image_encoder", "yolo_shelf_detector"]

VS_INDEX_NAME = "instockcv_clip_index"


def _delete_vs_index(catalog: str, schema: str) -> None:
    full_index = f"{catalog}.{schema}.{VS_INDEX_NAME}"
    try:
        from databricks.vector_search.client import VectorSearchClient
        vs = VectorSearchClient(disable_notice=True)
        vs.delete_index(index_name=full_index)
        print(f"Deleted VS index: {full_index}")
    except Exception as e:
        print(f"WARNING: Could not delete VS index '{full_index}': {e}")


def _delete_serving_endpoints() -> None:
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
    except Exception as e:
        print(f"WARNING: Could not init WorkspaceClient: {e}")
        return

    for name in SERVING_ENDPOINTS:
        try:
            w.serving_endpoints.delete(name=name)
            print(f"Deleted serving endpoint: {name}")
        except Exception as e:
            print(f"WARNING: Could not delete endpoint '{name}': {e}")


def _delete_uc_models(catalog: str, schema: str) -> None:
    try:
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
    except Exception as e:
        print(f"WARNING: Could not init WorkspaceClient: {e}")
        return

    for model_name in UC_MODELS:
        full_name = f"{catalog}.{schema}.{model_name}"
        try:
            versions = list(w.model_versions.list(full_name))
            for v in versions:
                try:
                    w.model_versions.delete(full_name, v.version)
                    print(f"Deleted model version: {full_name} v{v.version}")
                except Exception as e:
                    print(f"WARNING: Could not delete {full_name} v{v.version}: {e}")
            w.registered_models.delete(full_name)
            print(f"Deleted registered model: {full_name}")
        except Exception as e:
            print(f"WARNING: Could not delete model '{full_name}': {e}")


def _drop_schema(catalog: str, schema: str) -> None:
    ddl = f"DROP SCHEMA IF EXISTS {catalog}.{schema} CASCADE"
    # Prefer Spark (always available in a Spark Python task)
    try:
        from pyspark.sql import SparkSession
        spark = SparkSession.builder.getOrCreate()
        spark.sql(ddl)
        print(f"Dropped schema: {catalog}.{schema} (CASCADE)")
        return
    except ImportError:
        pass
    # Fallback: SDK statement execution (requires a running SQL warehouse)
    try:
        from databricks.sdk import WorkspaceClient
        from databricks.sdk.service.sql import StatementState
        w = WorkspaceClient()
        warehouses = list(w.warehouses.list())
        if not warehouses:
            print("WARNING: No SQL warehouse available — cannot drop schema via SDK")
            return
        wh_id = warehouses[0].id
        resp = w.statement_execution.execute_statement(
            statement=ddl,
            warehouse_id=wh_id,
            wait_timeout="120s",
        )
        if resp.status.state == StatementState.SUCCEEDED:
            print(f"Dropped schema: {catalog}.{schema} (CASCADE)")
        else:
            print(f"WARNING: DROP SCHEMA returned state={resp.status.state}: {resp.status.error}")
    except Exception as e:
        print(f"WARNING: Could not drop schema '{catalog}.{schema}': {e}")


def teardown(catalog: str, schema: str) -> None:
    print(f"=== inStockCV teardown: {catalog}.{schema} ===")
    _delete_vs_index(catalog, schema)
    _delete_serving_endpoints()
    _delete_uc_models(catalog, schema)
    _drop_schema(catalog, schema)
    print("=== teardown complete ===")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    teardown(args.catalog, args.schema)


if __name__ == "__main__":
    main()
