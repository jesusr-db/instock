# inStockCV Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a mobile-optimized Databricks App (React + FastAPI) that lets a store employee photograph a retail product and instantly check its inventory quantity against a synthetic Delta table catalog, with model swapping via Databricks AI Gateway.

**Architecture:** A Vite/React frontend captures images and calls a FastAPI backend. The backend calls AI Gateway (GPT-4o by default, Qwen3-VL-8B optionally) to extract structured product attributes + SKU candidates, fuzzy-matches against a synthetic `inventory` Delta table using RapidFuzz, and returns quantity + confidence. A Databricks Asset Bundle (DAB) manages deployment; a `setup_job` running as the app SP provisions all infrastructure (tables, AI Gateway endpoint, UC volume).

**Tech Stack:** Python 3.11, FastAPI, uvicorn, pydantic-settings, openai SDK, databricks-sdk, databricks-sql-connector, rapidfuzz, Pillow — React 18, TypeScript, Vite 5 — Databricks Asset Bundles, Databricks AI Gateway, Delta Lake / Unity Catalog

---

## File Map

| File | Responsibility |
|---|---|
| `databricks.yml` | DAB bundle: defines app resource, includes job resources, declares variables |
| `resources/setup_job.yml` | Setup job task definitions (run as app SP) |
| `.gitignore` | Ignore `__pycache__`, `.env`, `node_modules`, `dist/` |
| `setup/generate_inventory.py` | Pure function: generates ~500 deterministic synthetic SKU rows |
| `setup/create_tables.py` | Creates `inventory` + `scan_log` Delta tables; loads synthetic data via Spark |
| `setup/create_endpoint.py` | Creates AI Gateway external model serving endpoint (GPT-4o) via Databricks SDK |
| `setup/deploy_oss_model.py` | (Optional) Logs Qwen3-VL-8B as MLflow pyfunc model + creates serving endpoint |
| `app/backend/__init__.py` | Empty package marker |
| `app/backend/config.py` | `Settings` via pydantic-settings; single source for all env vars |
| `app/backend/analyze.py` | `POST /analyze` — image upload → AI Gateway → structured JSON |
| `app/backend/lookup.py` | `POST /lookup` — fuzzy match against Delta + async scan_log append |
| `app/backend/main.py` | FastAPI app init; `/health`, `/config/models`; mounts static React build |
| `app/backend/requirements.txt` | Backend Python dependencies |
| `app/app.yml` | Databricks App entrypoint command |
| `app/frontend/package.json` | Frontend npm dependencies |
| `app/frontend/vite.config.ts` | Vite config with dev proxy to FastAPI |
| `app/frontend/index.html` | HTML shell |
| `app/frontend/src/main.tsx` | React DOM entry point |
| `app/frontend/src/api.ts` | Typed fetch wrappers for `/analyze`, `/lookup`, `/config/models` |
| `app/frontend/src/ScanPanel.tsx` | Image upload UI with camera capture; model dropdown |
| `app/frontend/src/ResultCard.tsx` | Result display: SKU, quantity (color-coded), confidence badge |
| `app/frontend/src/App.tsx` | Root: state machine wiring ScanPanel → ResultCard |
| `tests/__init__.py` | Empty test package marker |
| `tests/test_generate_inventory.py` | Unit tests: data shape, uniqueness, determinism |
| `tests/test_create_tables.py` | Unit tests: DDL strings, mock Spark calls |
| `tests/test_create_endpoint.py` | Unit tests: SDK config object structure |
| `tests/test_config.py` | Unit tests: env var loading |
| `tests/test_analyze.py` | Unit tests: prompt string, response parser |
| `tests/test_lookup.py` | Unit tests: fuzzy matching logic, confidence labels |
| `tests/test_main.py` | Integration tests: health + config/models endpoints |

---

## Task 1: Project Scaffold, .gitignore, and DAB Bundle Config

**Files:**
- Create: `databricks.yml`
- Create: `resources/setup_job.yml`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `app/backend/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p resources app/backend app/frontend/src setup tests
touch tests/__init__.py app/backend/__init__.py
```

- [ ] **Step 2: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
*.egg-info/
.pytest_cache/
node_modules/
app/frontend/dist/
.DS_Store
```

- [ ] **Step 3: Create `databricks.yml`**

```yaml
bundle:
  name: inStockCV

variables:
  catalog:
    description: Unity Catalog name
    default: main
  schema:
    description: Schema name
    default: instockcv
  openai_secret_scope:
    description: Databricks secret scope containing OpenAI API key
    default: instockcv-secrets
  openai_secret_key:
    description: Key name within the secret scope
    default: openai-api-key
  deploy_oss_model:
    description: Set to 'true' to deploy Qwen3-VL-8B OSS model endpoint
    default: "false"
  sql_warehouse_http_path:
    description: HTTP path for the SQL warehouse used by the app
  app_service_principal_client_id:
    description: Client ID of the app service principal

targets:
  dev:
    mode: development
    default: true
    variables:
      schema: instockcv_dev

  prod:
    mode: production

include:
  - resources/*.yml
```

- [ ] **Step 4: Create `resources/setup_job.yml`**

```yaml
resources:
  jobs:
    setup_job:
      name: "[inStockCV] Setup"
      run_as:
        service_principal_name: ${var.app_service_principal_client_id}

      tasks:
        - task_key: provision_tables
          new_cluster:
            spark_version: "15.4.x-cpu-ml-scala2.12"
            node_type_id: i3.xlarge
            num_workers: 0
            spark_conf:
              spark.databricks.cluster.profile: singleNode
          spark_python_task:
            python_file: ../setup/create_tables.py
            parameters:
              - --catalog
              - ${var.catalog}
              - --schema
              - ${var.schema}
          libraries:
            - pypi:
                package: databricks-sdk>=0.28.0

        - task_key: create_endpoint
          depends_on:
            - task_key: provision_tables
          new_cluster:
            spark_version: "15.4.x-cpu-ml-scala2.12"
            node_type_id: i3.xlarge
            num_workers: 0
            spark_conf:
              spark.databricks.cluster.profile: singleNode
          spark_python_task:
            python_file: ../setup/create_endpoint.py
            parameters:
              - --secret-scope
              - ${var.openai_secret_scope}
              - --secret-key
              - ${var.openai_secret_key}
          libraries:
            - pypi:
                package: databricks-sdk>=0.28.0
```

- [ ] **Step 5: Commit**

```bash
git add databricks.yml resources/ .gitignore tests/__init__.py app/backend/__init__.py
git commit -m "feat: project scaffold, DAB bundle config, and setup job definition"
```

---

## Task 2: Synthetic Inventory Generator

**Files:**
- Create: `setup/generate_inventory.py`
- Create: `tests/test_generate_inventory.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_generate_inventory.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from setup.generate_inventory import generate_inventory

def test_generates_expected_count():
    rows = generate_inventory(seed=42)
    assert 450 <= len(rows) <= 550

def test_required_columns_present():
    rows = generate_inventory(seed=42)
    required = {"sku_id", "brand", "category", "product_name", "size", "flavor", "quantity_on_hand"}
    assert required.issubset(rows[0].keys())

def test_sku_ids_are_unique():
    rows = generate_inventory(seed=42)
    sku_ids = [r["sku_id"] for r in rows]
    assert len(sku_ids) == len(set(sku_ids))

def test_categories_are_valid():
    rows = generate_inventory(seed=42)
    assert all(r["category"] in {"tobacco", "beverage", "snack"} for r in rows)

def test_deterministic_output():
    assert [r["sku_id"] for r in generate_inventory(seed=42)] == \
           [r["sku_id"] for r in generate_inventory(seed=42)]

def test_quantity_in_range():
    rows = generate_inventory(seed=42)
    assert all(0 <= r["quantity_on_hand"] <= 50 for r in rows)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV
pip install pytest
pytest tests/test_generate_inventory.py -v
```

Expected: `ImportError: No module named 'setup.generate_inventory'`

- [ ] **Step 3: Implement `setup/generate_inventory.py`**

```python
import random

TOBACCO = [
    ("Marlboro", ["Red", "Gold", "Silver", "Black", "Menthol"]),
    ("Newport", ["Menthol", "Red", "Gold"]),
    ("Camel", ["Blue", "Filters", "Menthol", "Turkish Silver"]),
    ("Winston", ["Red", "Blue", "Gold", "White"]),
    ("Pall Mall", ["Red", "Blue", "Menthol", "Orange", "Black"]),
    ("Kool", ["Menthol", "Super Longs"]),
    ("American Spirit", ["Yellow", "Blue", "Orange", "Green"]),
]
TOBACCO_SIZES = ["King Size 20-pack", "King Size 25-pack", "100s 20-pack", "Soft Pack 20-pack"]

BEVERAGES = [
    ("Coca-Cola", ["Original", "Zero Sugar", "Cherry", "Vanilla", "Starlight"]),
    ("Pepsi", ["Original", "Zero Sugar", "Wild Cherry", "Mango"]),
    ("Red Bull", ["Original", "Sugar Free", "Blue Edition", "Red Edition"]),
    ("Monster", ["Original", "Ultra White", "Mango Loco", "Zero Ultra"]),
    ("Gatorade", ["Lemon Lime", "Fruit Punch", "Orange", "Cool Blue"]),
    ("Powerade", ["Mountain Berry Blast", "Fruit Punch", "Orange", "Grape"]),
    ("Sprite", ["Original", "Zero Sugar", "Cranberry"]),
    ("Dr Pepper", ["Original", "Zero Sugar", "Cherry"]),
]
BEVERAGE_SIZES = ["12oz", "20oz", "16oz", "2L", "1L", "8.4oz", "24oz"]

SNACKS = [
    ("Lays", ["Classic", "BBQ", "Sour Cream & Onion", "Salt & Vinegar", "Cheddar"]),
    ("Doritos", ["Nacho Cheese", "Cool Ranch", "Spicy Nacho", "Flamin Hot"]),
    ("Cheetos", ["Crunchy", "Puffs", "Flamin Hot", "Baked"]),
    ("Fritos", ["Original", "BBQ", "Honey BBQ"]),
    ("Pringles", ["Original", "Sour Cream & Onion", "BBQ", "Cheddar", "Pizza"]),
]
SNACK_SIZES = ["1oz", "1.5oz", "2.75oz", "8oz", "13.5oz"]

_FLAVOR_KEYWORDS = {"menthol", "cherry", "vanilla", "mango", "berry", "lemon",
                    "orange", "grape", "punch", "lime", "peach", "tropical"}

def _sku(category: str, brand: str, variant: str, size: str) -> str:
    codes = {"tobacco": "TOB", "beverage": "BEV", "snack": "SNK"}
    return (
        f"{codes[category]}-"
        f"{brand.replace(' ', '')[:4].upper()}-"
        f"{variant.replace(' ', '')[:4].upper()}-"
        f"{size.replace(' ', '').replace('.', '')[:4].upper()}"
    )

def generate_inventory(seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    rows: list[dict] = []
    seen: set[str] = set()

    def fill(category: str, products: list, sizes: list, target: int) -> None:
        attempts = 0
        while sum(1 for r in rows if r["category"] == category) < target and attempts < target * 20:
            attempts += 1
            brand, variants = rng.choice(products)
            variant = rng.choice(variants)
            size = rng.choice(sizes)
            sku = _sku(category, brand, variant, size)
            if sku in seen:
                continue
            seen.add(sku)
            flavor = variant if any(kw in variant.lower() for kw in _FLAVOR_KEYWORDS) else None
            rows.append({
                "sku_id": sku,
                "brand": brand,
                "category": category,
                "product_name": f"{brand} {variant}",
                "size": size,
                "flavor": flavor,
                "quantity_on_hand": rng.randint(0, 50),
            })

    fill("tobacco", TOBACCO, TOBACCO_SIZES, 200)
    fill("beverage", BEVERAGES, BEVERAGE_SIZES, 200)
    fill("snack", SNACKS, SNACK_SIZES, 100)
    return rows
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_generate_inventory.py -v
```

Expected: 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add setup/generate_inventory.py tests/test_generate_inventory.py
git commit -m "feat: synthetic inventory data generator (500 SKUs, deterministic)"
```

---

## Task 3: Delta Table Creation & Data Loading

**Files:**
- Create: `setup/create_tables.py`
- Create: `tests/test_create_tables.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_create_tables.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from unittest.mock import MagicMock, patch
from setup.create_tables import build_ddl_inventory, build_ddl_scan_log, create_tables

def test_inventory_ddl_has_required_columns():
    ddl = build_ddl_inventory("main", "instockcv")
    for col in ["sku_id", "brand", "category", "product_name", "size", "flavor", "quantity_on_hand"]:
        assert col in ddl, f"Missing column: {col}"
    assert "main.instockcv.inventory" in ddl

def test_scan_log_ddl_has_required_columns():
    ddl = build_ddl_scan_log("main", "instockcv")
    for col in ["scan_id", "scanned_at", "model_route", "matched_sku_id", "match_score", "quantity_on_hand"]:
        assert col in ddl, f"Missing column: {col}"
    assert "main.instockcv.scan_log" in ddl

def test_create_tables_calls_spark_sql():
    mock_spark = MagicMock()
    mock_df = MagicMock()
    mock_spark.createDataFrame.return_value = mock_df
    mock_df.write.mode.return_value.saveAsTable = MagicMock()

    create_tables(mock_spark, "main", "instockcv", seed=42)

    sql_calls = [str(c.args[0]) for c in mock_spark.sql.call_args_list]
    assert any("inventory" in s for s in sql_calls)
    assert any("scan_log" in s for s in sql_calls)
    mock_df.write.mode.assert_called_with("overwrite")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_create_tables.py -v
```

Expected: `ImportError: No module named 'setup.create_tables'`

- [ ] **Step 3: Implement `setup/create_tables.py`**

```python
import argparse
from setup.generate_inventory import generate_inventory

def build_ddl_inventory(catalog: str, schema: str) -> str:
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
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
    spark.sql(build_ddl_inventory(catalog, schema))
    spark.sql(build_ddl_scan_log(catalog, schema))
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {catalog}.{schema}.scan_images")

    rows = generate_inventory(seed=seed)
    df = spark.createDataFrame(rows)
    df.write.mode("overwrite").saveAsTable(f"{catalog}.{schema}.inventory")
    print(f"Loaded {len(rows)} rows into {catalog}.{schema}.inventory")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()

    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    create_tables(spark, args.catalog, args.schema)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_create_tables.py -v
```

Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add setup/create_tables.py tests/test_create_tables.py
git commit -m "feat: Delta table DDL and synthetic data loading via Spark"
```

---

## Task 4: AI Gateway Endpoint Creation

**Files:**
- Create: `setup/create_endpoint.py`
- Create: `tests/test_create_endpoint.py`

- [ ] **Step 1: Install Databricks SDK**

```bash
pip install "databricks-sdk>=0.28.0"
```

- [ ] **Step 2: Write failing tests**

```python
# tests/test_create_endpoint.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from databricks.sdk.service.serving import EndpointCoreConfigInput
from setup.create_endpoint import build_endpoint_config, ENDPOINT_NAME

def test_endpoint_name():
    assert ENDPOINT_NAME == "instockcv-gateway"

def test_build_endpoint_config_returns_correct_type():
    config = build_endpoint_config("my-scope", "my-key")
    assert isinstance(config, EndpointCoreConfigInput)

def test_build_endpoint_config_embeds_secret_reference():
    config = build_endpoint_config("my-scope", "my-key")
    entity = config.served_entities[0]
    assert entity.external_model.openai_config.openai_api_key == "{{secrets/my-scope/my-key}}"

def test_create_skips_existing_endpoint():
    from unittest.mock import MagicMock
    from setup.create_endpoint import create_or_update_endpoint
    from databricks.sdk.service.serving import ServingEndpoint

    mock_w = MagicMock()
    existing = MagicMock()
    existing.name = ENDPOINT_NAME
    mock_w.serving_endpoints.list.return_value = [existing]

    create_or_update_endpoint(mock_w, "scope", "key")
    mock_w.serving_endpoints.create_and_wait.assert_not_called()
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
pytest tests/test_create_endpoint.py -v
```

Expected: `ImportError: No module named 'setup.create_endpoint'`

- [ ] **Step 4: Implement `setup/create_endpoint.py`**

```python
import argparse
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput,
    ExternalModel,
    ExternalModelProvider,
    OpenAiConfig,
    AiGatewayConfig,
    AiGatewayUsageTrackingConfig,
)

ENDPOINT_NAME = "instockcv-gateway"

def build_endpoint_config(secret_scope: str, secret_key: str) -> EndpointCoreConfigInput:
    return EndpointCoreConfigInput(
        served_entities=[
            ServedEntityInput(
                name="gpt-4o-entity",
                external_model=ExternalModel(
                    name="gpt-4o",
                    provider=ExternalModelProvider.OPENAI,
                    task="llm/v1/chat",
                    openai_config=OpenAiConfig(
                        openai_api_key=f"{{{{secrets/{secret_scope}/{secret_key}}}}}"
                    ),
                ),
            )
        ]
    )

def create_or_update_endpoint(w: WorkspaceClient, secret_scope: str, secret_key: str) -> None:
    existing = [e for e in w.serving_endpoints.list() if e.name == ENDPOINT_NAME]
    if existing:
        print(f"Endpoint '{ENDPOINT_NAME}' already exists — skipping")
        return
    print(f"Creating endpoint '{ENDPOINT_NAME}'...")
    w.serving_endpoints.create_and_wait(
        name=ENDPOINT_NAME,
        config=build_endpoint_config(secret_scope, secret_key),
        ai_gateway=AiGatewayConfig(
            usage_tracking_config=AiGatewayUsageTrackingConfig(enabled=True)
        ),
    )
    print(f"Endpoint '{ENDPOINT_NAME}' ready")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-scope", required=True)
    parser.add_argument("--secret-key", required=True)
    args = parser.parse_args()
    create_or_update_endpoint(WorkspaceClient(), args.secret_scope, args.secret_key)

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run tests — verify they pass**

```bash
pytest tests/test_create_endpoint.py -v
```

Expected: 4 tests PASS

- [ ] **Step 6: Commit**

```bash
git add setup/create_endpoint.py tests/test_create_endpoint.py
git commit -m "feat: AI Gateway external model endpoint provisioning (GPT-4o)"
```

---

## Task 5: Backend Config Module

**Files:**
- Create: `app/backend/config.py`
- Create: `app/backend/requirements.txt`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import sys, os

def test_settings_loads_env_vars(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("MODEL_ROUTE", "instockcv-gateway")
    monkeypatch.setenv("INVENTORY_TABLE", "main.instockcv.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "main.instockcv.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/Volumes/main/instockcv/scan_images")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc123")

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))
    import importlib
    import backend.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.get_settings.cache_clear()

    settings = cfg_module.get_settings()
    assert settings.model_route == "instockcv-gateway"
    assert settings.inventory_table == "main.instockcv.inventory"
    assert settings.use_detection_stage is False
```

- [ ] **Step 2: Run test — verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend'`

- [ ] **Step 3: Create `app/backend/requirements.txt`**

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
pydantic-settings>=2.2.0
openai>=1.30.0
databricks-sdk>=0.28.0
databricks-sql-connector>=3.3.0
rapidfuzz>=3.6.0
Pillow>=10.3.0
```

- [ ] **Step 4: Install dependencies**

```bash
pip install -r app/backend/requirements.txt
```

- [ ] **Step 5: Create `app/backend/config.py`**

```python
from functools import lru_cache
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    databricks_host: str
    databricks_token: str
    model_route: str = "instockcv-gateway"
    inventory_table: str
    scan_log_table: str
    image_volume_path: str
    sql_warehouse_http_path: str
    use_detection_stage: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: Run test — verify it passes**

```bash
pytest tests/test_config.py -v
```

Expected: 1 test PASS

- [ ] **Step 7: Commit**

```bash
git add app/backend/config.py app/backend/requirements.txt tests/test_config.py
git commit -m "feat: backend config module with pydantic-settings"
```

---

## Task 6: Backend /analyze Endpoint

**Files:**
- Create: `app/backend/analyze.py`
- Create: `tests/test_analyze.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_analyze.py
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

os.environ.update({
    "DATABRICKS_HOST": "https://test.azuredatabricks.net",
    "DATABRICKS_TOKEN": "dapi-test",
    "MODEL_ROUTE": "instockcv-gateway",
    "INVENTORY_TABLE": "main.instockcv.inventory",
    "SCAN_LOG_TABLE": "main.instockcv.scan_log",
    "IMAGE_VOLUME_PATH": "/Volumes/main/instockcv/scan_images",
    "SQL_WAREHOUSE_HTTP_PATH": "/sql/1.0/warehouses/abc123",
})

from backend.analyze import build_vision_prompt, parse_model_response, ModelResponseError
import pytest

def test_build_vision_prompt_contains_required_keys():
    prompt = build_vision_prompt()
    for key in ["brand", "category", "product_name", "size", "flavor", "top_3_sku_candidates", "confidence_score"]:
        assert key in prompt, f"Prompt missing key: {key}"

def test_parse_valid_json():
    raw = json.dumps({
        "brand": "Marlboro", "category": "tobacco",
        "product_name": "Marlboro Red", "size": "King Size 20-pack",
        "flavor": None,
        "top_3_sku_candidates": [
            {"candidate_name": "Marlboro Red King Size", "confidence_score": 0.95},
            {"candidate_name": "Marlboro Gold King Size", "confidence_score": 0.45},
            {"candidate_name": "Camel Red King Size", "confidence_score": 0.30},
        ]
    })
    result = parse_model_response(raw)
    assert result["brand"] == "Marlboro"
    assert len(result["top_3_sku_candidates"]) == 3

def test_parse_strips_markdown_fences():
    raw = '```json\n{"brand":"Pepsi","category":"beverage","product_name":"Pepsi Zero Sugar","size":"20oz","flavor":null,"top_3_sku_candidates":[{"candidate_name":"Pepsi Zero 20oz","confidence_score":0.9}]}\n```'
    result = parse_model_response(raw)
    assert result["brand"] == "Pepsi"

def test_parse_raises_on_garbage():
    with pytest.raises(ModelResponseError):
        parse_model_response("not json at all {{{")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_analyze.py -v
```

Expected: `ImportError: No module named 'backend.analyze'`

- [ ] **Step 3: Implement `app/backend/analyze.py`**

```python
import os, uuid, base64, json, re
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from openai import OpenAI
from backend.config import get_settings

router = APIRouter()

class ModelResponseError(Exception):
    pass

def build_vision_prompt() -> str:
    return (
        "Identify the product in this image. "
        "Return ONLY valid JSON (no markdown, no extra text) with these exact keys: "
        '{"brand":"brand name","category":"tobacco|beverage|snack",'
        '"product_name":"full product name","size":"size description",'
        '"flavor":"flavor or null",'
        '"top_3_sku_candidates":['
        '{"candidate_name":"brand product_name size","confidence_score":0.95}'
        "]} "
        "Provide exactly 3 candidates, highest confidence first."
    )

def parse_model_response(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ModelResponseError(f"Non-JSON model response: {e}") from e

def _save_image(image_bytes: bytes, ext: str, scan_id: str) -> str | None:
    settings = get_settings()
    path = f"{settings.image_volume_path}/{scan_id}.{ext}"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path
    except Exception:
        return None  # non-fatal for POC

@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    model_route: str = Form(default=None),
):
    settings = get_settings()
    route = model_route or settings.model_route
    scan_id = str(uuid.uuid4())
    image_bytes = await file.read()
    ext = (file.filename or "image.jpg").rsplit(".", 1)[-1].lower() or "jpg"
    volume_path = _save_image(image_bytes, ext, scan_id)

    b64 = base64.b64encode(image_bytes).decode()
    mime = f"image/{ext}" if ext in ("jpg", "jpeg", "png", "webp") else "image/jpeg"

    client = OpenAI(
        api_key=settings.databricks_token,
        base_url=f"{settings.databricks_host}/serving-endpoints",
    )
    try:
        response = client.chat.completions.create(
            model=route,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": build_vision_prompt()},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }],
            max_tokens=512,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI Gateway error: {e}")

    raw = response.choices[0].message.content or ""
    try:
        parsed = parse_model_response(raw)
    except ModelResponseError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"scan_id": scan_id, "model_route": route, "image_volume_path": volume_path, **parsed}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_analyze.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/backend/analyze.py tests/test_analyze.py
git commit -m "feat: /analyze endpoint — image upload to AI Gateway with JSON extraction"
```

---

## Task 7: Backend /lookup Endpoint

**Files:**
- Create: `app/backend/lookup.py`
- Create: `tests/test_lookup.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_lookup.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

os.environ.update({
    "DATABRICKS_HOST": "https://test.azuredatabricks.net",
    "DATABRICKS_TOKEN": "dapi-test",
    "MODEL_ROUTE": "instockcv-gateway",
    "INVENTORY_TABLE": "main.instockcv.inventory",
    "SCAN_LOG_TABLE": "main.instockcv.scan_log",
    "IMAGE_VOLUME_PATH": "/Volumes/main/instockcv/scan_images",
    "SQL_WAREHOUSE_HTTP_PATH": "/sql/1.0/warehouses/abc123",
})

from backend.lookup import fuzzy_match_candidates, score_to_label, ConfidenceLabel

INVENTORY = [
    {"sku_id": "TOB-MARL-RED-KING", "brand": "Marlboro", "product_name": "Marlboro Red", "size": "King Size 20-pack", "quantity_on_hand": 15},
    {"sku_id": "BEV-PEPS-ZERO-20OZ", "brand": "Pepsi", "product_name": "Pepsi Zero Sugar", "size": "20oz", "quantity_on_hand": 3},
    {"sku_id": "SNK-LAYS-CLAS-10Z", "brand": "Lays", "product_name": "Lays Classic", "size": "1oz", "quantity_on_hand": 0},
]

def test_matches_exact_brand_product():
    candidates = [{"candidate_name": "Marlboro Red King Size 20-pack", "confidence_score": 0.95}]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert result is not None
    assert result["sku_id"] == "TOB-MARL-RED-KING"

def test_matches_partial_name():
    candidates = [{"candidate_name": "Pepsi Zero 20oz", "confidence_score": 0.88}]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert result is not None
    assert result["sku_id"] == "BEV-PEPS-ZERO-20OZ"

def test_returns_none_when_below_threshold():
    candidates = [{"candidate_name": "Xyz Unknown Widget Brand", "confidence_score": 0.10}]
    result = fuzzy_match_candidates(candidates, INVENTORY, min_score=0.99)
    assert result is None

def test_result_includes_match_score():
    candidates = [{"candidate_name": "Marlboro Red King", "confidence_score": 0.90}]
    result = fuzzy_match_candidates(candidates, INVENTORY)
    assert "match_score" in result
    assert 0.0 <= result["match_score"] <= 1.0

def test_score_to_label_high():
    assert score_to_label(0.90) == ConfidenceLabel.HIGH

def test_score_to_label_medium():
    assert score_to_label(0.75) == ConfidenceLabel.MEDIUM

def test_score_to_label_low():
    assert score_to_label(0.50) == ConfidenceLabel.LOW
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_lookup.py -v
```

Expected: `ImportError: No module named 'backend.lookup'`

- [ ] **Step 3: Implement `app/backend/lookup.py`**

```python
from datetime import datetime, timezone
from enum import Enum
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from rapidfuzz import fuzz
import databricks.sql as dbsql
from backend.config import get_settings

router = APIRouter()

class ConfidenceLabel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

def score_to_label(score: float) -> ConfidenceLabel:
    if score >= 0.85:
        return ConfidenceLabel.HIGH
    if score >= 0.65:
        return ConfidenceLabel.MEDIUM
    return ConfidenceLabel.LOW

def fuzzy_match_candidates(
    candidates: list[dict],
    inventory: list[dict],
    min_score: float = 0.50,
) -> dict | None:
    best_score = 0.0
    best_row: dict | None = None
    for candidate in candidates:
        cname = candidate.get("candidate_name", "")
        conf = candidate.get("confidence_score", 1.0)
        for row in inventory:
            row_str = f"{row['brand']} {row['product_name']} {row['size']}"
            fuzzy = fuzz.token_sort_ratio(cname, row_str) / 100.0
            combined = fuzzy * conf
            if combined > best_score:
                best_score = combined
                best_row = {**row, "match_score": round(fuzzy, 4)}
    if best_row is None or best_row["match_score"] < min_score:
        return None
    return best_row

def _fetch_inventory(settings) -> list[dict]:
    host = settings.databricks_host.replace("https://", "")
    with dbsql.connect(
        server_hostname=host,
        http_path=settings.sql_warehouse_http_path,
        access_token=settings.databricks_token,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT sku_id, brand, product_name, size, quantity_on_hand "
                f"FROM {settings.inventory_table}"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

def _write_scan_log(settings, row: dict) -> None:
    host = settings.databricks_host.replace("https://", "")
    try:
        with dbsql.connect(
            server_hostname=host,
            http_path=settings.sql_warehouse_http_path,
            access_token=settings.databricks_token,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"INSERT INTO {settings.scan_log_table} "
                    "(scan_id, scanned_at, model_route, image_volume_path, "
                    "model_brand, model_product_name, model_size, "
                    "matched_sku_id, match_score, quantity_on_hand) "
                    "VALUES (%(scan_id)s, %(scanned_at)s, %(model_route)s, %(image_volume_path)s, "
                    "%(model_brand)s, %(model_product_name)s, %(model_size)s, "
                    "%(matched_sku_id)s, %(match_score)s, %(quantity_on_hand)s)",
                    row,
                )
    except Exception:
        pass  # non-fatal in POC

class LookupRequest(BaseModel):
    scan_id: str
    model_route: str
    image_volume_path: str | None = None
    brand: str | None = None
    category: str | None = None
    product_name: str | None = None
    size: str | None = None
    flavor: str | None = None
    top_3_sku_candidates: list[dict] = []

@router.post("/lookup")
async def lookup(req: LookupRequest, background_tasks: BackgroundTasks):
    settings = get_settings()
    try:
        inventory = _fetch_inventory(settings)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")

    match = fuzzy_match_candidates(req.top_3_sku_candidates, inventory)
    result = {
        "scan_id": req.scan_id,
        "matched": match is not None,
        "sku_id": match["sku_id"] if match else None,
        "product_name": match["product_name"] if match else req.product_name,
        "brand": match["brand"] if match else req.brand,
        "quantity_on_hand": match["quantity_on_hand"] if match else None,
        "match_score": match["match_score"] if match else 0.0,
        "confidence_label": score_to_label(match["match_score"]).value if match else ConfidenceLabel.LOW.value,
    }
    background_tasks.add_task(_write_scan_log, settings, {
        "scan_id": req.scan_id,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "model_route": req.model_route,
        "image_volume_path": req.image_volume_path,
        "model_brand": req.brand,
        "model_product_name": req.product_name,
        "model_size": req.size,
        "matched_sku_id": result["sku_id"],
        "match_score": result["match_score"],
        "quantity_on_hand": result["quantity_on_hand"],
    })
    return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_lookup.py -v
```

Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/backend/lookup.py tests/test_lookup.py
git commit -m "feat: /lookup endpoint — RapidFuzz matching, async scan_log append"
```

---

## Task 8: FastAPI Main App

**Files:**
- Create: `app/backend/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_main.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

os.environ.update({
    "DATABRICKS_HOST": "https://test.azuredatabricks.net",
    "DATABRICKS_TOKEN": "dapi-test",
    "MODEL_ROUTE": "instockcv-gateway",
    "INVENTORY_TABLE": "main.instockcv.inventory",
    "SCAN_LOG_TABLE": "main.instockcv.scan_log",
    "IMAGE_VOLUME_PATH": "/Volumes/main/instockcv/scan_images",
    "SQL_WAREHOUSE_HTTP_PATH": "/sql/1.0/warehouses/abc123",
})

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

def test_config_models_returns_list():
    resp = client.get("/config/models")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["models"], list)
    assert len(data["models"]) >= 1
    assert "default" in data
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_main.py -v
```

Expected: `ImportError: No module named 'backend.main'`

- [ ] **Step 3: Implement `app/backend/main.py`**

```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from backend.config import get_settings
from backend.analyze import router as analyze_router
from backend.lookup import router as lookup_router

app = FastAPI(title="inStockCV")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(lookup_router)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/config/models")
def config_models():
    settings = get_settings()
    models = [settings.model_route]
    extra = os.environ.get("ADDITIONAL_MODEL_ROUTES", "")
    if extra:
        models += [m.strip() for m in extra.split(",") if m.strip()]
    return {"models": models, "default": settings.model_route}

# Serve React build — must be registered last
static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
```

- [ ] **Step 4: Run all backend tests**

```bash
pytest tests/ -v
```

Expected: All tests PASS (test_generate_inventory × 6, test_create_tables × 3, test_create_endpoint × 4, test_config × 1, test_analyze × 4, test_lookup × 7, test_main × 2) = **27 tests PASS**

- [ ] **Step 5: Commit**

```bash
git add app/backend/main.py tests/test_main.py
git commit -m "feat: FastAPI app wiring — health, config/models, static file serving"
```

---

## Task 9: Frontend Scaffold

**Files:**
- Create: `app/frontend/package.json`
- Create: `app/frontend/vite.config.ts`
- Create: `app/frontend/index.html`
- Create: `app/frontend/tsconfig.json`
- Create: `app/frontend/src/main.tsx`

- [ ] **Step 1: Create `app/frontend/package.json`**

```json
{
  "name": "instockcv-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {
    "@types/react": "^18.3.3",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.4.5",
    "vite": "^5.4.1"
  }
}
```

- [ ] **Step 2: Install frontend dependencies**

```bash
cd app/frontend && npm install && cd ../..
```

Expected: `node_modules/` created in `app/frontend/`

- [ ] **Step 3: Create `app/frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4: Create `app/frontend/vite.config.ts`**

```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/analyze': 'http://localhost:8000',
      '/lookup': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
      '/config': 'http://localhost:8000',
    }
  },
  build: { outDir: 'dist' }
})
```

- [ ] **Step 5: Create `app/frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
    <title>inStockCV</title>
    <style>
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; }
    </style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Create `app/frontend/src/main.tsx`**

```tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

- [ ] **Step 7: Commit scaffold**

```bash
git add app/frontend/package.json app/frontend/vite.config.ts app/frontend/index.html app/frontend/tsconfig.json app/frontend/src/main.tsx app/frontend/package-lock.json
git commit -m "feat: React/Vite frontend scaffold"
```

---

## Task 10: Frontend API Client

**Files:**
- Create: `app/frontend/src/api.ts`

- [ ] **Step 1: Create `app/frontend/src/api.ts`**

```typescript
export interface AnalyzeResult {
  scan_id: string
  model_route: string
  image_volume_path: string | null
  brand: string | null
  category: string | null
  product_name: string | null
  size: string | null
  flavor: string | null
  top_3_sku_candidates: Array<{ candidate_name: string; confidence_score: number }>
}

export interface LookupResult {
  scan_id: string
  matched: boolean
  sku_id: string | null
  product_name: string | null
  brand: string | null
  quantity_on_hand: number | null
  match_score: number
  confidence_label: 'High' | 'Medium' | 'Low'
}

export interface ModelsConfig {
  models: string[]
  default: string
}

export async function fetchModels(): Promise<ModelsConfig> {
  const res = await fetch('/config/models')
  if (!res.ok) throw new Error('Failed to load model list')
  return res.json()
}

export async function analyzeImage(file: File, modelRoute: string): Promise<AnalyzeResult> {
  const form = new FormData()
  form.append('file', file)
  form.append('model_route', modelRoute)
  const res = await fetch('/analyze', { method: 'POST', body: form })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || 'Analyze failed')
  }
  return res.json()
}

export async function lookupSku(analyzeResult: AnalyzeResult): Promise<LookupResult> {
  const res = await fetch('/lookup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(analyzeResult),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(err.detail || 'Lookup failed')
  }
  return res.json()
}
```

- [ ] **Step 2: Commit**

```bash
git add app/frontend/src/api.ts
git commit -m "feat: typed API client (analyze, lookup, config/models)"
```

---

## Task 11: ScanPanel Component

**Files:**
- Create: `app/frontend/src/ScanPanel.tsx`

- [ ] **Step 1: Create `app/frontend/src/ScanPanel.tsx`**

```tsx
import React, { useRef, useState } from 'react'

interface Props {
  onSubmit: (file: File) => void
  isLoading: boolean
  models: string[]
  selectedModel: string
  onModelChange: (model: string) => void
}

export default function ScanPanel({ onSubmit, isLoading, models, selectedModel, onModelChange }: Props) {
  const [preview, setPreview] = useState<string | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  return (
    <div style={s.panel}>
      <div style={s.uploadArea} onClick={() => inputRef.current?.click()}>
        {preview
          ? <img src={preview} alt="Preview" style={s.preview} />
          : (
            <div style={s.placeholder}>
              <div style={s.cameraIcon}>📷</div>
              <p style={s.hint}>Tap to take a photo or select image</p>
            </div>
          )
        }
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>

      {models.length > 1 && (
        <div style={s.modelRow}>
          <label style={s.label}>Model</label>
          <select value={selectedModel} onChange={e => onModelChange(e.target.value)} style={s.select}>
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      )}

      <button
        onClick={() => file && onSubmit(file)}
        disabled={!file || isLoading}
        style={{ ...s.button, opacity: (!file || isLoading) ? 0.5 : 1 }}
      >
        {isLoading ? 'Checking...' : 'Check Inventory'}
      </button>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  panel: { display: 'flex', flexDirection: 'column', gap: 16, padding: 16 },
  uploadArea: {
    border: '2px dashed #ccc', borderRadius: 12, minHeight: 220,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    cursor: 'pointer', overflow: 'hidden', background: '#fff',
  },
  preview: { width: '100%', objectFit: 'cover' },
  placeholder: { textAlign: 'center', padding: 32 },
  cameraIcon: { fontSize: 48 },
  hint: { marginTop: 8, color: '#888', fontSize: 14 },
  modelRow: { display: 'flex', alignItems: 'center', gap: 8 },
  label: { fontSize: 14, color: '#555', minWidth: 50 },
  select: { flex: 1, padding: '8px 12px', borderRadius: 8, border: '1px solid #ddd', fontSize: 14 },
  button: {
    padding: '14px 0', borderRadius: 12, border: 'none',
    background: '#1B3A6B', color: '#fff', fontSize: 16, fontWeight: 600,
    cursor: 'pointer', width: '100%',
  },
}
```

- [ ] **Step 2: Commit**

```bash
git add app/frontend/src/ScanPanel.tsx
git commit -m "feat: ScanPanel — camera capture, file select, model dropdown"
```

---

## Task 12: ResultCard Component

**Files:**
- Create: `app/frontend/src/ResultCard.tsx`

- [ ] **Step 1: Create `app/frontend/src/ResultCard.tsx`**

```tsx
import React from 'react'
import type { LookupResult } from './api'

interface Props {
  result: LookupResult
  onReset: () => void
}

function qtyColor(qty: number | null): string {
  if (qty === null) return '#888'
  if (qty === 0) return '#dc2626'
  if (qty < 10) return '#d97706'
  return '#16a34a'
}

const BADGE_COLORS: Record<string, string> = {
  High: '#16a34a', Medium: '#d97706', Low: '#dc2626',
}

export default function ResultCard({ result, onReset }: Props) {
  return (
    <div style={s.card}>
      {result.matched ? (
        <>
          <p style={s.productName}>{result.product_name ?? 'Unknown Product'}</p>
          <p style={s.brand}>{result.brand}</p>

          <div style={s.row}>
            <span style={s.rowLabel}>SKU</span>
            <span style={s.sku}>{result.sku_id}</span>
          </div>

          <div style={s.row}>
            <span style={s.rowLabel}>In Stock</span>
            <span style={{ ...s.qty, color: qtyColor(result.quantity_on_hand) }}>
              {result.quantity_on_hand ?? '—'}
            </span>
          </div>

          <div style={s.row}>
            <span style={s.rowLabel}>Match</span>
            <span style={{ ...s.badge, background: BADGE_COLORS[result.confidence_label] ?? '#888' }}>
              {result.confidence_label}
            </span>
          </div>
        </>
      ) : (
        <div style={s.noMatch}>
          <div style={{ fontSize: 40 }}>❌</div>
          <p style={{ marginTop: 8, color: '#555', fontSize: 16 }}>Product not found in inventory</p>
        </div>
      )}

      <button onClick={onReset} style={s.resetBtn}>Scan Another</button>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  card: { background: '#fff', borderRadius: 16, padding: 24, boxShadow: '0 2px 12px rgba(0,0,0,0.08)', display: 'flex', flexDirection: 'column', gap: 16 },
  productName: { fontSize: 22, fontWeight: 700, color: '#111' },
  brand: { fontSize: 16, color: '#555' },
  row: { display: 'flex', justifyContent: 'space-between', alignItems: 'center' },
  rowLabel: { fontSize: 13, color: '#888', textTransform: 'uppercase', letterSpacing: 0.5 },
  sku: { fontFamily: 'monospace', fontSize: 14, color: '#333' },
  qty: { fontSize: 40, fontWeight: 800, lineHeight: 1 },
  badge: { display: 'inline-block', padding: '2px 10px', borderRadius: 99, fontSize: 12, fontWeight: 600, color: '#fff' },
  noMatch: { textAlign: 'center', padding: '24px 0' },
  resetBtn: { padding: '12px 0', borderRadius: 12, border: '2px solid #1B3A6B', background: 'transparent', color: '#1B3A6B', fontSize: 15, fontWeight: 600, cursor: 'pointer', width: '100%' },
}
```

- [ ] **Step 2: Commit**

```bash
git add app/frontend/src/ResultCard.tsx
git commit -m "feat: ResultCard — color-coded quantity, confidence badge, no-match state"
```

---

## Task 13: App Root Component & Frontend Build

**Files:**
- Create: `app/frontend/src/App.tsx`

- [ ] **Step 1: Create `app/frontend/src/App.tsx`**

```tsx
import React, { useEffect, useState } from 'react'
import ScanPanel from './ScanPanel'
import ResultCard from './ResultCard'
import { analyzeImage, lookupSku, fetchModels } from './api'
import type { LookupResult } from './api'

type State = 'idle' | 'loading' | 'result' | 'error'

export default function App() {
  const [state, setState] = useState<State>('idle')
  const [result, setResult] = useState<LookupResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<string[]>(['instockcv-gateway'])
  const [selectedModel, setSelectedModel] = useState('instockcv-gateway')

  useEffect(() => {
    fetchModels()
      .then(cfg => { setModels(cfg.models); setSelectedModel(cfg.default) })
      .catch(() => {})
  }, [])

  async function handleSubmit(file: File) {
    setState('loading')
    setError(null)
    try {
      const analyzed = await analyzeImage(file, selectedModel)
      const looked = await lookupSku(analyzed)
      setResult(looked)
      setState('result')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unexpected error')
      setState('error')
    }
  }

  function reset() { setResult(null); setError(null); setState('idle') }

  return (
    <div style={s.root}>
      <header style={s.header}>
        <span style={{ fontSize: 22 }}>📦</span>
        <h1 style={s.title}>inStockCV</h1>
      </header>
      <main style={s.main}>
        {(state === 'idle' || state === 'loading' || state === 'error') && (
          <ScanPanel
            onSubmit={handleSubmit}
            isLoading={state === 'loading'}
            models={models}
            selectedModel={selectedModel}
            onModelChange={setSelectedModel}
          />
        )}
        {state === 'error' && (
          <div style={s.errorBanner}>{error}</div>
        )}
        {state === 'result' && result && (
          <ResultCard result={result} onReset={reset} />
        )}
      </main>
    </div>
  )
}

const s: Record<string, React.CSSProperties> = {
  root: { minHeight: '100vh', background: '#f5f5f5' },
  header: { background: '#1B3A6B', color: '#fff', padding: '14px 20px', display: 'flex', alignItems: 'center', gap: 10 },
  title: { fontSize: 20, fontWeight: 700, letterSpacing: -0.3 },
  main: { padding: 16, maxWidth: 480, margin: '0 auto' },
  errorBanner: { background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', borderRadius: 10, padding: '12px 16px', marginTop: 12, fontSize: 14 },
}
```

- [ ] **Step 2: Build the frontend**

```bash
cd app/frontend && npm run build && cd ../..
```

Expected: `app/frontend/dist/` created with `index.html` and `assets/`

- [ ] **Step 3: Verify static serving works**

Start the FastAPI backend:
```bash
cd app && uvicorn backend.main:app --port 8000
```

Open `http://localhost:8000` — should display the inStockCV UI (served from the React build).
Open `http://localhost:8000/health` — should return `{"status":"ok"}`.
Stop the server with Ctrl+C.

- [ ] **Step 4: Commit**

```bash
cd ..
git add app/frontend/src/App.tsx
git commit -m "feat: App root — idle/loading/result/error state machine"
```

---

## Task 14: App Config & Deployment Setup

**Files:**
- Create: `app/app.yml`
- Create: `.env.example`

- [ ] **Step 1: Create `app/app.yml`**

```yaml
command:
  - uvicorn
  - backend.main:app
  - --host
  - "0.0.0.0"
  - --port
  - "8000"

env:
  - name: MODEL_ROUTE
    value: instockcv-gateway
  - name: INVENTORY_TABLE
    value: main.instockcv.inventory
  - name: SCAN_LOG_TABLE
    value: main.instockcv.scan_log
  - name: IMAGE_VOLUME_PATH
    value: /Volumes/main/instockcv/scan_images
  - name: SQL_WAREHOUSE_HTTP_PATH
    value: FILL_IN_AT_DEPLOY_TIME
```

- [ ] **Step 2: Create `.env.example`**

```bash
# Copy to app/.env and fill in for local development
DATABRICKS_HOST=https://your-workspace.azuredatabricks.net
DATABRICKS_TOKEN=dapi-your-token
MODEL_ROUTE=instockcv-gateway
INVENTORY_TABLE=main.instockcv_dev.inventory
SCAN_LOG_TABLE=main.instockcv_dev.scan_log
IMAGE_VOLUME_PATH=/tmp/instockcv_images
SQL_WAREHOUSE_HTTP_PATH=/sql/1.0/warehouses/your-warehouse-id
```

- [ ] **Step 3: Run full test suite one more time**

```bash
pytest tests/ -v
```

Expected: **27 tests PASS**, 0 failures

- [ ] **Step 4: Commit**

```bash
git add app/app.yml .env.example
git commit -m "feat: Databricks App config and env example"
```

---

## Task 15: Deploy with DAB

- [ ] **Step 1: Install Databricks CLI (if not already installed)**

```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
```

- [ ] **Step 2: Create OpenAI secret scope and key**

```bash
databricks secrets create-scope instockcv-secrets
databricks secrets put-secret instockcv-secrets openai-api-key --string-value "sk-YOUR-OPENAI-KEY"
```

- [ ] **Step 3: Build the frontend before deploying**

```bash
cd app/frontend && npm run build && cd ../..
```

- [ ] **Step 4: Deploy the bundle to dev**

```bash
databricks bundle deploy --target dev \
  --var sql_warehouse_http_path=/sql/1.0/warehouses/YOUR_WAREHOUSE_ID \
  --var app_service_principal_client_id=YOUR_SP_CLIENT_ID
```

Expected: App resource and setup job created in workspace.

- [ ] **Step 5: Run the setup job**

```bash
databricks bundle run setup_job --target dev
```

Expected: Delta tables created, synthetic data loaded, AI Gateway endpoint provisioned. Takes ~5 minutes.

- [ ] **Step 6: Update `app/app.yml` with real warehouse HTTP path, then redeploy**

Edit `app/app.yml`: replace `FILL_IN_AT_DEPLOY_TIME` in `SQL_WAREHOUSE_HTTP_PATH` with the actual value. Then:

```bash
databricks bundle deploy --target dev \
  --var sql_warehouse_http_path=/sql/1.0/warehouses/YOUR_WAREHOUSE_ID \
  --var app_service_principal_client_id=YOUR_SP_CLIENT_ID
```

- [ ] **Step 7: Open the app and test end-to-end**

Get the app URL from the Databricks workspace UI under **Apps**. Open it on a mobile device:
1. Tap "Upload Photo" → take a photo of a cigarette pack or beverage
2. Tap "Check Inventory"
3. Verify result card shows SKU, quantity, and confidence badge

---

## Optional Task 16: Deploy Qwen3-VL-8B OSS Model

Only run this when `DEPLOY_OSS_MODEL=true` is desired.

**Files:**
- Create: `setup/deploy_oss_model.py`

- [ ] **Step 1: Create `setup/deploy_oss_model.py`**

```python
import argparse
import mlflow
from mlflow.pyfunc import PythonModel, PythonModelContext
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import (
    EndpointCoreConfigInput,
    ServedEntityInput,
    ServedModelInputWorkloadSize,
)

QWEN_ENDPOINT_NAME = "instockcv-qwen3vl"
QWEN_HF_ID = "Qwen/Qwen3-VL-8B-Instruct"

class Qwen3VLWrapper(PythonModel):
    def load_context(self, context: PythonModelContext) -> None:
        from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        import torch
        self.processor = AutoProcessor.from_pretrained(QWEN_HF_ID)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            QWEN_HF_ID, torch_dtype=torch.bfloat16, device_map="auto"
        )

    def predict(self, context: PythonModelContext, model_input: dict, params=None) -> str:
        import torch
        from qwen_vl_utils import process_vision_info
        messages = model_input.get("messages", [])
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, _ = process_vision_info(messages)
        inputs = self.processor(text=[text], images=image_inputs, return_tensors="pt").to(self.model.device)
        with torch.no_grad():
            out = self.model.generate(**inputs, max_new_tokens=512)
        trimmed = [o[len(i):] for i, o in zip(inputs.input_ids, out)]
        return self.processor.batch_decode(trimmed, skip_special_tokens=True)[0]

def register_model(catalog: str, schema: str) -> str:
    mlflow.set_registry_uri("databricks-uc")
    full_name = f"{catalog}.{schema}.instockcv_qwen3vl"
    with mlflow.start_run():
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=Qwen3VLWrapper(),
            registered_model_name=full_name,
            pip_requirements=[
                "transformers>=4.45.0",
                "qwen-vl-utils>=0.0.8",
                "torch>=2.3.0",
                "accelerate>=0.30.0",
            ],
        )
    return full_name

def create_endpoint(w: WorkspaceClient, model_name: str) -> None:
    if any(e.name == QWEN_ENDPOINT_NAME for e in w.serving_endpoints.list()):
        print(f"'{QWEN_ENDPOINT_NAME}' already exists — skipping")
        return
    w.serving_endpoints.create_and_wait(
        name=QWEN_ENDPOINT_NAME,
        config=EndpointCoreConfigInput(
            served_entities=[
                ServedEntityInput(
                    entity_name=model_name,
                    entity_version="1",
                    workload_size=ServedModelInputWorkloadSize.SMALL,
                    scale_to_zero_enabled=True,
                )
            ]
        ),
    )
    print(f"Endpoint '{QWEN_ENDPOINT_NAME}' ready — add it as a route in AI Gateway and set ADDITIONAL_MODEL_ROUTES=instockcv-qwen3vl")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args()
    w = WorkspaceClient()
    model_name = register_model(args.catalog, args.schema)
    create_endpoint(w, model_name)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add setup/deploy_oss_model.py
git commit -m "feat: optional Qwen3-VL-8B OSS model registration and endpoint creation"
```

- [ ] **Step 3: Run the OSS deployment (on a GPU cluster)**

```bash
# Run manually on a Databricks GPU cluster or via the setup_job with DEPLOY_OSS_MODEL=true
python setup/deploy_oss_model.py --catalog main --schema instockcv_dev
```

- [ ] **Step 4: Set `ADDITIONAL_MODEL_ROUTES` in `app/app.yml`**

Add to the `env` section in `app/app.yml`:
```yaml
  - name: ADDITIONAL_MODEL_ROUTES
    value: instockcv-qwen3vl
```

Then redeploy the bundle. The model selector dropdown in the UI will now show both `instockcv-gateway` (GPT-4o) and `instockcv-qwen3vl` (Qwen3-VL-8B).
