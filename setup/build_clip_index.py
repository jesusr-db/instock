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
VS_ENDPOINT_NAME = "instockcv-vs"
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
    import urllib.error
    payload = json.dumps({"dataframe_records": [{"image": image_b64}]}).encode()
    url = f"{workspace_host}/serving-endpoints/{endpoint_name}/invocations"
    for attempt in range(5):
        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
            embedding_str = result["predictions"][0]["embedding"]
            return json.loads(embedding_str)
        except urllib.error.HTTPError as e:
            # 4xx errors won't recover with retries
            if 400 <= e.code < 500:
                raise RuntimeError(f"CLIP endpoint rejected request (HTTP {e.code}): {e.read().decode()}") from e
            if attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"  CLIP endpoint HTTP {e.code} (attempt {attempt+1}/5). Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except Exception as e:
            if attempt < 4:
                wait = 15 * (attempt + 1)
                print(f"  CLIP endpoint call failed (attempt {attempt+1}/5): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


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


def _ensure_vs_endpoint(workspace_host: str, token: str) -> None:
    """Create instockcv-vs endpoint if it doesn't exist and wait for ONLINE."""
    _, err = _vs_request(workspace_host, token, "GET", f"endpoints/{VS_ENDPOINT_NAME}")
    if err is None:
        print(f"VS endpoint '{VS_ENDPOINT_NAME}' already exists.")
        return

    print(f"Creating VS endpoint '{VS_ENDPOINT_NAME}'...")
    body = {"name": VS_ENDPOINT_NAME, "endpoint_type": "STANDARD"}
    result, err = _vs_request(workspace_host, token, "POST", "endpoints", body)
    if err:
        raise RuntimeError(f"Failed to create VS endpoint: {err.read().decode()}")
    print(f"VS endpoint '{VS_ENDPOINT_NAME}' created. Waiting for ONLINE (up to 20 min)...")

    for _ in range(120):
        result, err = _vs_request(workspace_host, token, "GET", f"endpoints/{VS_ENDPOINT_NAME}")
        if err:
            time.sleep(10)
            continue
        state = (result or {}).get("endpoint_status", {}).get("state", "")
        print(f"  VS endpoint state: {state}")
        if state == "ONLINE":
            print(f"VS endpoint '{VS_ENDPOINT_NAME}' is ONLINE.")
            return
        if state in ("OFFLINE", "PROVISIONING_FAILED"):
            raise RuntimeError(f"VS endpoint '{VS_ENDPOINT_NAME}' failed: {state}")
        time.sleep(10)
    raise RuntimeError(f"VS endpoint '{VS_ENDPOINT_NAME}' did not reach ONLINE within 20 minutes.")


def _vs_request(workspace_host: str, token: str, method: str, path: str, body=None):
    import urllib.request
    import urllib.error
    url = f"{workspace_host}/api/2.0/vector-search/{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        return None, e


def _create_or_sync_vs_index(workspace_host, token, catalog, schema):
    full_index_name = f"{catalog}.{schema}.{INDEX_NAME}"

    _, err = _vs_request(workspace_host, token, "GET", f"indexes/{full_index_name}")
    if err is None:
        print(f"Index '{full_index_name}' already exists.")
        return full_index_name

    print(f"Creating Direct Access index '{full_index_name}'...")
    body = {
        "name": full_index_name,
        "endpoint_name": VS_ENDPOINT_NAME,
        "primary_key": "combo_key",
        "index_type": "DIRECT_ACCESS",
        "direct_access_index_spec": {
            "embedding_vector_columns": [
                {"name": "embedding", "embedding_dimension": 512}
            ],
            "schema_json": json.dumps({
                "combo_key": "string",
                "brand": "string",
                "variant": "string",
                "category": "string",
                "embedding": "array<float>",
            }),
        },
    }
    result, err = _vs_request(workspace_host, token, "POST", "indexes", body)
    if err:
        raise RuntimeError(f"Failed to create VS index: {err.read().decode()}")
    print(f"Index created: {result.get('name')}")
    return full_index_name


def _wait_for_vs_index_ready(workspace_host: str, token: str, full_index_name: str) -> None:
    print(f"Waiting for VS index '{full_index_name}' to reach ONLINE...")
    for _ in range(240):
        result, err = _vs_request(workspace_host, token, "GET", f"indexes/{full_index_name}")
        if err:
            time.sleep(5)
            continue
        state = (result or {}).get("status", {}).get("detailed_state", "")
        print(f"  VS index state: {state}")
        if state.startswith("ONLINE"):
            print(f"VS index '{full_index_name}' is ONLINE ({state}).")
            return
        if "FAILED" in state or "OFFLINE" in state:
            raise RuntimeError(f"VS index '{full_index_name}' in terminal bad state: {state}")
        time.sleep(10)
    raise RuntimeError(f"VS index '{full_index_name}' did not reach ONLINE within 40 minutes.")


def _upsert_to_vs_index(workspace_host, token, catalog, schema, rows):
    full_index_name = f"{catalog}.{schema}.{INDEX_NAME}"
    batch_size = 50
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        body = {"inputs_json": json.dumps(batch)}
        _, err = _vs_request(workspace_host, token, "POST",
                             f"indexes/{full_index_name}/upsert-data", body)
        if err:
            raise RuntimeError(f"Upsert failed at row {i}: {err.read().decode()}")
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

    _ensure_vs_endpoint(host, token)

    print(f"Building CLIP embeddings from {volume_ref_dir}...")
    if not os.path.isdir(volume_ref_dir):
        raise RuntimeError(f"Reference image directory not found: {volume_ref_dir}. Upload reference images to the UC volume first.")
    rows = _build_embeddings(volume_ref_dir, host, token, clip_endpoint)
    if not rows:
        raise RuntimeError(f"No reference images found in {volume_ref_dir}. Expected subdirectories with {{brand}}_{{variant}}.jpg files.")
    print(f"Built {len(rows)} embeddings.")

    _write_embeddings_to_delta(spark, rows, catalog, schema)
    full_index = _create_or_sync_vs_index(host, token, catalog, schema)
    _wait_for_vs_index_ready(host, token, full_index)
    _upsert_to_vs_index(host, token, catalog, schema, rows)

    output_path = DEFAULT_OUTPUT
    with open(output_path, "w") as f:
        f.write(f"{catalog}.{schema}.{INDEX_NAME}\n")
    print(f"Index name written to {output_path}")


if __name__ == "__main__":
    main()
