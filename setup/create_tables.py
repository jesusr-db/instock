"""Create Delta tables and UC volume for inStockCV, then load synthetic data.

Run as a Spark Python task in the setup_job. The job's run-as identity
must have privileges to CREATE SCHEMA / CREATE TABLE / CREATE VOLUME in
the target catalog.

Self-contained: this script imports `generate_inventory` from a sibling
module *if available* (CLI / unit-test path), otherwise it loads the
file by absolute path (Databricks job path), so it works regardless of
how it is launched.

Usage:
    python create_tables.py --catalog main --schema instockcv [--seed 42]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from typing import Callable


def _load_generate_inventory() -> Callable[[int], list[dict]]:
    """Resolve `generate_inventory` across CLI, pytest, and Databricks job contexts.

    Strategy (in order):
    1. Plain import — works when run as `python -m setup.create_tables` or via pytest.
    2. Locate sibling generate_inventory.py via `__file__` and load by path.
    3. Locate sibling generate_inventory.py from the Databricks bundle root.
    """
    # Strategy 1: plain import
    try:
        from setup.generate_inventory import generate_inventory  # type: ignore
        return generate_inventory
    except ImportError:
        pass

    # Strategy 2 & 3: load by file path
    candidate_paths: list[str] = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidate_paths.append(os.path.join(here, "generate_inventory.py"))
    except NameError:
        pass

    # Databricks job context: bundle uploaded to /Workspace/.../files/setup/
    candidate_paths.extend(
        [
            os.path.join(os.getcwd(), "setup", "generate_inventory.py"),
            os.path.join(os.getcwd(), "generate_inventory.py"),
        ]
    )

    for path in candidate_paths:
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location("generate_inventory", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules["generate_inventory"] = module
        spec.loader.exec_module(module)
        return module.generate_inventory

    raise ImportError(
        "Could not locate generate_inventory.py in any of: " + ", ".join(candidate_paths)
    )


def build_ddl_inventory(catalog: str, schema: str) -> str:
    """Return the CREATE TABLE DDL for the inventory table."""
    return f"""
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.inventory (
    sku_id           STRING NOT NULL,
    brand            STRING NOT NULL,
    category         STRING NOT NULL,
    product_name     STRING NOT NULL,
    size             STRING NOT NULL,
    flavor           STRING,
    quantity_on_hand INT NOT NULL
) USING DELTA
"""


def build_ddl_scan_log(catalog: str, schema: str) -> str:
    """Return the CREATE TABLE DDL for the scan_log table."""
    return f"""
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.scan_log (
    scan_id            STRING NOT NULL,
    scanned_at         TIMESTAMP NOT NULL,
    model_route        STRING,
    image_volume_path  STRING,
    model_brand        STRING,
    model_product_name STRING,
    model_size         STRING,
    matched_sku_id     STRING,
    match_score        FLOAT,
    quantity_on_hand   INT
) USING DELTA
"""


def build_ddl_sku_clip_embeddings(catalog: str, schema: str) -> str:
    """Return CREATE TABLE DDL for the CLIP embedding reference table."""
    return f"""
CREATE TABLE IF NOT EXISTS {catalog}.{schema}.sku_clip_embeddings (
    combo_key  STRING NOT NULL,
    brand      STRING NOT NULL,
    variant    STRING NOT NULL,
    category   STRING NOT NULL,
    embedding  ARRAY<FLOAT> NOT NULL
) USING DELTA
"""


def _upload_reference_images(catalog: str, schema: str) -> None:
    """Copy reference_images/ from bundle workspace to UC volume. Non-fatal."""
    import shutil

    candidate_roots = []
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        candidate_roots.append(os.path.join(here, "..", "reference_images"))
    except NameError:
        pass
    candidate_roots.extend([
        os.path.join(os.getcwd(), "reference_images"),
        os.path.join(os.getcwd(), "..", "reference_images"),
    ])

    source_root = None
    for r in candidate_roots:
        if os.path.isdir(r):
            source_root = os.path.abspath(r)
            break

    if source_root is None:
        print("WARNING: reference_images/ directory not found — skipping image upload")
        return

    dest_root = f"/Volumes/{catalog}/{schema}/scan_images/reference"
    try:
        os.makedirs(dest_root, exist_ok=True)
    except OSError as e:
        print(f"WARNING: Cannot create {dest_root}: {e} — skipping image upload")
        return

    count = 0
    for dirpath, _, filenames in os.walk(source_root):
        for fname in filenames:
            if not fname.endswith((".jpg", ".jpeg", ".png")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fname), source_root)
            dest = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if not os.path.exists(dest):
                shutil.copy2(os.path.join(dirpath, fname), dest)
                count += 1
    print(f"Uploaded {count} reference images to {dest_root}")


def create_tables(spark, catalog: str, schema: str, seed: int = 42) -> None:
    """Provision Unity Catalog schema + tables + volume, then load synthetic inventory.

    Args:
        spark: A SparkSession (real or mocked).
        catalog: UC catalog name.
        schema: UC schema name.
        seed: Inventory generator RNG seed.
    """
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    spark.sql(build_ddl_inventory(catalog, schema))
    spark.sql(build_ddl_scan_log(catalog, schema))
    spark.sql(build_ddl_sku_clip_embeddings(catalog, schema))
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.scan_images")

    generate_inventory = _load_generate_inventory()
    rows = generate_inventory(seed=seed)

    # Build a DataFrame with an explicit schema matching the table DDL.
    # Without this, Spark infers `quantity_on_hand` as LongType which clashes
    # with the table's INT (= IntegerType) column on overwrite/merge.
    try:
        from pyspark.sql.types import (
            IntegerType,
            StringType,
            StructField,
            StructType,
        )
    except ImportError:
        # Test path — pyspark not installed; fall back to inferred schema.
        df = spark.createDataFrame(rows)
    else:
        explicit_schema = StructType(
            [
                StructField("sku_id", StringType(), nullable=False),
                StructField("brand", StringType(), nullable=False),
                StructField("category", StringType(), nullable=False),
                StructField("product_name", StringType(), nullable=False),
                StructField("size", StringType(), nullable=False),
                StructField("flavor", StringType(), nullable=True),
                StructField("quantity_on_hand", IntegerType(), nullable=False),
            ]
        )
        df = spark.createDataFrame(rows, schema=explicit_schema)

    df.write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.inventory")
    print(f"Loaded {len(rows)} rows into {catalog}.{schema}.inventory")
    _upload_reference_images(catalog, schema)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    from pyspark.sql import SparkSession  # imported lazily so unit tests don't need pyspark

    spark = SparkSession.builder.getOrCreate()
    create_tables(spark, args.catalog, args.schema, seed=args.seed)


if __name__ == "__main__":
    main()
