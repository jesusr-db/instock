"""Create Delta tables and UC volume for inStockCV, then load synthetic data.

Run as a Spark Python task in the setup_job. The job's run-as identity
must have privileges to CREATE SCHEMA / CREATE TABLE / CREATE VOLUME in
the target catalog.

Usage:
    python create_tables.py --catalog main --schema instockcv [--seed 42]
"""
from __future__ import annotations

import argparse

from setup.generate_inventory import generate_inventory


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
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.scan_images")

    rows = generate_inventory(seed=seed)
    df = spark.createDataFrame(rows)
    df.write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.inventory")
    print(f"Loaded {len(rows)} rows into {catalog}.{schema}.inventory")


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
