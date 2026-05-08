# inStockCV

Mobile-optimized Databricks App (React + FastAPI) for retail store employees to photograph products on a shelf and instantly check live inventory quantities — no app install required, runs in a phone browser.

The backend runs FastAPI on Databricks Apps with OAuth m2m auth. The frontend is a Vite-bundled React SPA. Inventory data lives in Delta tables on Unity Catalog. All scans are logged to a `scan_log` table for audit and analytics.

**Live app:** `https://instockcv-1351565862180944.aws.databricksapps.com`

---

## How it works

1. Employee opens the app on their phone and photographs a product
2. `POST /analyze` sends the image to an AI Gateway vision endpoint, which returns structured JSON with brand, product name, size, and top SKU candidates
3. `POST /lookup` fuzzy-matches candidates against the live `inventory` Delta table and returns the quantity on hand
4. The result card shows product info, SKU, quantity, and match confidence

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Mobile Browser (phone camera)                                  │
│  React SPA — Vite build, served as static files from FastAPI    │
│  ScanPanel → photo capture / file select                        │
│  ResultCard → product name, brand, size, SKU, qty, confidence   │
└──────────────────────┬──────────────────────────────────────────┘
                       │ HTTPS (Databricks Apps OAuth OIDC)
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  Databricks App — instockcv                                     │
│  FastAPI (uvicorn)                                              │
│                                                                 │
│  POST /analyze ──► AI Gateway (aigwjmr)                        │
│                    Vision model → structured JSON               │
│                                                                 │
│  POST /lookup  ──► Serverless SQL Warehouse                    │
│                    rapidfuzz match against inventory table      │
│                    BackgroundTask: INSERT into scan_log         │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ Unity Catalog (OAuth m2m)
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  vdm_classic_rikfy0_catalog.instockcv_dev                       │
│  inventory    — 462 synthetic retail SKUs                       │
│  scan_log     — append-only audit log                           │
│  scan_images  — UC Volume for raw photo bytes                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quickstart

### Prerequisites

- Databricks workspace access on databricks workspace with a configured CLI profile
- `databricks` CLI v0.294+
- Node.js 18+ and npm
- Python 3.10+

### Deploy
edit databricks.yaml to support deployment environment 


databricks bundle validate
databricks bundle deploy
databricks bundle run setup_job
databricks bundle run instockcv
---

## API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe → `{"status": "ok"}` |
| `GET` | `/config/models` | Available model routes and default |
| `POST` | `/analyze` | Upload photo → structured SKU candidates |
| `POST` | `/lookup` | Match candidates → live inventory quantity |

### `POST /analyze`

`multipart/form-data` with `file` (image) and optional `model_route`.

Returns `scan_id`, `brand`, `product_name`, `size`, `flavor`, `category`, and `top_3_sku_candidates` with confidence scores.

### `POST /lookup`

JSON body matching the `/analyze` response shape.

Returns `matched`, `sku_id`, `product_name`, `brand`, `size`, `quantity_on_hand`, `match_score`, and `confidence_label` (High / Medium / Low).

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABRICKS_HOST` | — | Workspace URL (auto-injected in apps) |
| `MODEL_ROUTE` | from `setup/endpoint_name.txt` | AI Gateway endpoint name |
| `INVENTORY_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` | Fully-qualified table name |
| `SCAN_LOG_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` | Fully-qualified table name |
| `SQL_WAREHOUSE_HTTP_PATH` | `/sql/1.0/warehouses/5067b513037fbf07` | SQL warehouse HTTP path |
| `IMAGE_VOLUME_PATH` | `/tmp/instockcv_images` | UC volume path or local fallback |
| `USE_DETECTION_STAGE` | `false` | Enable two-stage YOLO detection pipeline (roadmap) |

Copy `.env.example` to `app/.env` for local development.
