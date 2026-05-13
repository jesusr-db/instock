"""Build the CLIP Vector Search index for inStockCV.

Reads reference images from UC volume, calls the CLIP serving endpoint per image,
writes 512-d embeddings to Delta table sku_clip_embeddings, then creates (or rebuilds)
a Direct Access VS Index.

Runs as a spark_python_task in the setup_job after provision_tables.
"""
from __future__ import annotations
import base64
import json
import os
import time

INDEX_NAME = "instockcv_clip_index"
CLIP_ENDPOINT_ENV = "CLIP_ENDPOINT"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "clip_index_name.txt")


def _get_params() -> tuple[str, str]:
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--catalog", default=os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog"))
    parser.add_argument("--schema", default=os.environ.get("SCHEMA", "instockcv_dev"))
    args, _ = parser.parse_known_args()
    return args.catalog, args.schema


def _load_clip_endpoint() -> str:
    name = os.environ.get(CLIP_ENDPOINT_ENV, "")
    if name:
        return name
    candidates = [
        os.path.join(_here, "clip_endpoint_name.txt"),
        os.path.join(os.getcwd(), "setup", "clip_endpoint_name.txt"),
        os.path.join(os.getcwd(), "clip_endpoint_name.txt"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            with open(p) as f:
                return f.read().strip()
    raise RuntimeError(
        "CLIP endpoint name not found. Set CLIP_ENDPOINT env var or run deploy_clip_endpoint.py first."
    )


def _encode_image_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _call_clip_endpoint(workspace_host: str, token: str, endpoint_name: str, image_b64: str) -> list[float]:
    import urllib.request
    payload = json.dumps({"dataframe_records": [{"image": image_b64}]}).encode()
    req = urllib.request.Request(
        f"{workspace_host}/serving-endpoints/{endpoint_name}/invocations",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    embedding_str = result["predictions"][0]["embedding"]
    return json.loads(embedding_str)


def _build_embeddings(volume_reference_dir, workspace_host, token, clip_endpoint):
    rows = []
    for category in os.listdir(volume_reference_dir):
        cat_dir = os.path.join(volume_reference_dir, category)
        if not os.path.isdir(cat_dir):
            continue
        for fname in os.listdir(cat_dir):
            if not fname.endswith((".jpg", ".jpeg", ".png")):
                continue
            combo_key = os.path.splitext(fname)[0]
            parts = combo_key.split("_", 1)
            if len(parts) != 2:
                continue
            brand, variant = parts[0].replace("_", " "), parts[1].replace("_", " ")
            img_path = os.path.join(cat_dir, fname)
            b64 = _encode_image_base64(img_path)
            embedding = _call_clip_endpoint(workspace_host, token, clip_endpoint, b64)
            rows.append({
                "combo_key": combo_key,
                "brand": brand,
                "variant": variant,
                "category": category,
                "embedding": embedding,
            })
            print(f"  Embedded {combo_key} ({len(rows)} total)")
            time.sleep(0.05)
    return rows


def _write_embeddings_to_delta(spark, rows, catalog, schema):
    from pyspark.sql.types import (
        ArrayType, FloatType, StringType, StructField, StructType,
    )
    from pyspark.sql import Row

    schema_spark = StructType([
        StructField("combo_key", StringType(), nullable=False),
        StructField("brand", StringType(), nullable=False),
        StructField("variant", StringType(), nullable=False),
        StructField("category", StringType(), nullable=False),
        StructField("embedding", ArrayType(FloatType()), nullable=False),
    ])
    spark_rows = [Row(**{k: v for k, v in r.items()}) for r in rows]
    df = spark.createDataFrame(spark_rows, schema=schema_spark)
    df.write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.sku_clip_embeddings")
    print(f"Wrote {len(rows)} embeddings to {catalog}.{schema}.sku_clip_embeddings")


def _create_or_sync_vs_index(workspace_host, token, catalog, schema):
    from databricks.vectorsearch.client import VectorSearchClient

    vs_client = VectorSearchClient(
        workspace_url=workspace_host,
        personal_access_token=token,
        disable_notice=True,
    )
    full_index_name = f"{catalog}.{schema}.{INDEX_NAME}"

    try:
        idx = vs_client.get_index(index_name=full_index_name)
        print(f"Index '{full_index_name}' exists. Syncing...")
        idx.sync()
    except Exception:
        print(f"Creating Direct Access index '{full_index_name}'...")
        vs_client.create_direct_access_index(
            endpoint_name="databricks-vector-search",
            index_name=full_index_name,
            primary_key="combo_key",
            embedding_dimension=512,
            embedding_vector_column="embedding",
            schema={
                "combo_key": "string",
                "brand": "string",
                "variant": "string",
                "category": "string",
                "embedding": "array<float>",
            },
        )

    return full_index_name


def _upsert_to_vs_index(workspace_host, token, catalog, schema, rows):
    from databricks.vectorsearch.client import VectorSearchClient
    vs_client = VectorSearchClient(
        workspace_url=workspace_host,
        personal_access_token=token,
        disable_notice=True,
    )
    full_index_name = f"{catalog}.{schema}.{INDEX_NAME}"
    idx = vs_client.get_index(index_name=full_index_name)
    batch_size = 50
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        idx.upsert(batch)
        print(f"  Upserted rows {i}–{i + len(batch) - 1}")
    print(f"All {len(rows)} rows upserted to {full_index_name}")


def main():
    from pyspark.sql import SparkSession
    from databricks.sdk import WorkspaceClient

    spark = SparkSession.builder.getOrCreate()
    w = WorkspaceClient()
    catalog, schema = _get_params()

    headers = w.config.authenticate()
    token = headers.get("Authorization", "").replace("Bearer ", "")
    host = w.config.host
    if host and not host.startswith("http"):
        host = f"https://{host}"

    clip_endpoint = _load_clip_endpoint()
    volume_ref_dir = f"/Volumes/{catalog}/{schema}/scan_images/reference"

    print(f"Building CLIP embeddings from {volume_ref_dir}...")
    rows = _build_embeddings(volume_ref_dir, host, token, clip_endpoint)
    print(f"Built {len(rows)} embeddings.")

    _write_embeddings_to_delta(spark, rows, catalog, schema)
    _create_or_sync_vs_index(host, token, catalog, schema)
    _upsert_to_vs_index(host, token, catalog, schema, rows)

    output_path = DEFAULT_OUTPUT
    with open(output_path, "w") as f:
        f.write(f"{catalog}.{schema}.{INDEX_NAME}\n")
    print(f"Index name written to {output_path}")


if __name__ == "__main__":
    main()
