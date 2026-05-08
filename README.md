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

- Databricks workspace access on `fe-vm-vdm-classic-rikfy0.cloud.databricks.com` with a configured `DEFAULT` CLI profile
- `databricks` CLI v0.294+
- Terraform at `/opt/homebrew/bin/terraform` (v1.14.9) — see [Known issues](#known-issues)
- Node.js 18+ and npm
- Python 3.10+

### Deploy

```bash
# 1. Build the frontend
cd app/frontend && npm install && npm run build && cd ../..

# 2. Validate the bundle
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate

# 3. Deploy
DATABRICKS_CONFIG_PROFILE=DEFAULT \
DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform \
DATABRICKS_TF_VERSION=1.14.9 \
  databricks bundle deploy --target dev \
    --var sql_warehouse_http_path=/sql/1.0/warehouses/5067b513037fbf07

databricks apps deploy instockcv \
  --source-code-path /Workspace/Users/jesus.rodriguez@databricks.com/.bundle/instockcv/dev/files/app \
  --profile=DEFAULT

# 4. Run setup job (first deploy only, or to re-seed data)
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle run setup_job --target dev
```

### Common commands

```bash
pytest tests/ -v                          # run tests (33 total)
uvicorn backend.main:app --reload --port 8000   # local backend
cd app/frontend && npm run dev            # local frontend (proxies to :8000)
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks apps get instockcv
```

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
| `DATABRICKS_TOKEN` | — | PAT for local dev; omit in Databricks Apps |
| `MODEL_ROUTE` | from `setup/endpoint_name.txt` | AI Gateway endpoint name |
| `INVENTORY_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` | Fully-qualified table name |
| `SCAN_LOG_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` | Fully-qualified table name |
| `SQL_WAREHOUSE_HTTP_PATH` | `/sql/1.0/warehouses/5067b513037fbf07` | SQL warehouse HTTP path |
| `IMAGE_VOLUME_PATH` | `/tmp/instockcv_images` | UC volume path or local fallback |
| `USE_DETECTION_STAGE` | `false` | Enable two-stage YOLO detection pipeline (roadmap) |

Copy `.env.example` to `app/.env` for local development.

---

## Known issues

**Terraform GPG key expired (CLI v0.294)**
`databricks bundle deploy` fails with `openpgp: key expired`. Fix: `brew reinstall terraform` and pass `DATABRICKS_TF_EXEC_PATH` + `DATABRICKS_TF_VERSION` as shown in the deploy command above.

**`aigwjmr` routes 60% of traffic to a text-only model**
The AI Gateway endpoint splits 40% to `gemma-3-12b-it` (vision) and 60% to `gpt-oss-120b` (text-only). Vision requests on the text-only backend fail. Set `MODEL_ROUTE=databricks-claude-sonnet-4-6` to use a vision-capable model exclusively.

**DAB skips `.gitignore`'d files**
The built frontend (`app/frontend/dist/`) is in `.gitignore`. Without an explicit `sync.include` block in `databricks.yml`, the React app is never uploaded. The bundle config already includes this override — don't remove it.

**Databricks Apps don't inject `DATABRICKS_TOKEN`**
The platform uses OAuth m2m (`DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET`). `config.py` mints a token on demand via `WorkspaceClient().config.authenticate()` — don't make `databricks_token` required in `Settings`.

---

## Deployed resources

| Resource | Type | ID / Path |
|----------|------|-----------|
| `instockcv` | Databricks App | `https://instockcv-1351565862180944.aws.databricksapps.com` |
| `[inStockCV] Setup` | Databricks Job | `913830059117370` |
| `inventory` | Delta Table | `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` |
| `scan_log` | Delta Table | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` |
| `scan_images` | UC Volume | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_images` |
| Serverless Starter Warehouse | SQL Warehouse | `5067b513037fbf07` |
