# inStockCV — Design Spec

**Date:** 2026-04-29  
**Status:** Approved  
**Project:** inStockCV  
**Type:** POC / Customer Demo

---

## Overview

A Databricks App that allows a store employee to photograph a product on a shelf, identify the item using a vision AI model via Databricks AI Gateway, and look up its current quantity in a synthetic inventory Delta table. The result is displayed immediately in a mobile-optimized UI.

---

## Architecture

### Components

| Component | Technology | Purpose |
|---|---|---|
| Frontend | React (Vite) | Mobile-optimized upload UI and result display |
| Backend | FastAPI | Image intake, AI Gateway calls, Delta lookup |
| AI Model (default) | GPT-4o via AI Gateway | Vision analysis, structured attribute + SKU extraction |
| AI Model (OSS option) | Qwen3-VL-8B (self-hosted) | Open-source VLM; same interface, no external API calls |
| Detection model (optional) | YOLOv8 shelf detector | Stage 1: product localization + count from shelf photos |
| Model Router | Databricks AI Gateway | Abstraction layer; swap models via env var |
| Inventory store | Delta table (`inventory`) | Synthetic product catalog, ~500 SKUs |
| Audit log | Delta table (`scan_log`) | Append-only record of every scan |
| Image store | Unity Catalog Volume | Persists uploaded images |
| Deployment | Databricks Asset Bundle (DAB) | Single source of truth for all resources |
| Provisioning | `setup_job` (runs as app SP) | Creates tables, loads data, creates AI Gateway endpoint |

### Request Flow

1. Employee opens app on phone, taps **Upload Photo**
2. Selects image from camera or file (React frontend)
3. Frontend `POST /analyze` → backend encodes image as base64, calls AI Gateway
4. AI Gateway routes to GPT-4o (or configured alternative); model returns structured JSON:
   - `brand`, `category`, `product_name`, `size`, `flavor`
   - `top_3_sku_candidates`: list of `{candidate_name, confidence_score}`
5. Backend `POST /lookup` → fuzzy matches candidates against `inventory` Delta table using RapidFuzz (token sort ratio on `brand + product_name + size`)
6. Best match returned with `sku_id`, `quantity_on_hand`, `match_score`
7. Result card rendered in UI; scan appended to `scan_log` asynchronously

---

## Frontend (React)

**Single-page, mobile-first.**

### Layout

- **Header:** App name (`inStockCV`), model selector dropdown (default: `gpt-4o`; alternatives configurable via AI Gateway routes)
- **Scan Panel:** Large "Upload Photo" button (`accept="image/*"`, `capture="environment"` for direct camera on mobile), image thumbnail preview
- **Submit:** "Check Inventory" button — disabled until image selected, shows spinner while processing
- **Results Card:**
  - Product name + brand
  - SKU ID
  - Quantity on hand (large, color-coded: green ≥ 10, yellow 1–9, red = 0)
  - Match confidence badge: High (≥ 0.85), Medium (0.65–0.84), Low (< 0.65)
  - "Scan Another" button resets state

### Auth

No app-level auth. Databricks App runtime handles workspace-level access. The app URL is shared internally for the POC.

---

## Backend (FastAPI)

### Endpoints

#### `POST /analyze`
- Accepts multipart image upload
- Saves image to Unity Catalog volume (path: `{volume_root}/{scan_id}.{ext}`)
- Encodes image as base64; calls AI Gateway with prompt:
  > "Identify the product in this image. Return JSON with: brand, category, product_name, size, flavor (null if not applicable), and top_3_sku_candidates as a list of objects each with candidate_name and confidence_score (0.0–1.0)."
- Model route selected by `MODEL_ROUTE` env var — no code change needed to swap models
- Returns structured JSON

#### `POST /lookup`
- Accepts structured model output from `/analyze`
- Queries `inventory` Delta table via Databricks SQL connector
- Fuzzy matches `brand + product_name + size` against catalog using RapidFuzz token sort ratio
- Returns best match: `sku_id`, `product_name`, `brand`, `quantity_on_hand`, `match_score`
- Appends row to `scan_log` asynchronously (non-blocking)

#### `GET /health`
- Returns `{"status": "ok"}` for Databricks App health check

### Configuration (env vars)

| Var | Purpose | Default |
|---|---|---|
| `DATABRICKS_HOST` | Workspace URL | required |
| `MODEL_ROUTE` | AI Gateway route name | `gpt-4o` |
| `INVENTORY_TABLE` | Fully-qualified Delta table | required |
| `SCAN_LOG_TABLE` | Fully-qualified Delta table | required |
| `IMAGE_VOLUME_PATH` | Unity Catalog volume root path | required |
| `OPENAI_API_KEY_SECRET` | Databricks secret scope + key for OpenAI key | required |
| `DEPLOY_OSS_MODEL` | Deploy Qwen3-VL-8B OSS model endpoint in setup_job | `false` |
| `USE_DETECTION_STAGE` | Enable YOLOv8 pre-detection stage in /analyze | `false` |

The app SP's runtime token is used for all Databricks SDK/SQL calls — no hardcoded credentials.

---

## AI Gateway & Model Options

The AI Gateway serves as the abstraction layer — the backend calls a named route, and the route config determines which model runs. Swapping models requires no code changes, only an env var update and (if adding a new model) a new serving endpoint.

### Default Route: GPT-4o (External)

- **Type:** External model serving endpoint (OpenAI provider)
- **Default route name:** `gpt-4o`
- **Created by:** `setup_job` using Databricks Python SDK (`workspace_client.serving_endpoints.create()`)
- **OpenAI API key:** Stored in Databricks Secrets; injected into the serving endpoint config by `setup_job`

### Optional Route: Qwen3-VL-8B (Open Source, Self-Hosted)

A fully open-source alternative deployable inside the Databricks workspace — no external API calls, no data leaving the environment. This is the strongest demo story for data-sensitive customers.

- **Model:** `Qwen/Qwen3-VL-8B-Instruct` (HuggingFace, Apache 2.0)
- **Why:** Best open-source VLM for reading product labels — OCR-grade text extraction, structured JSON output, runs on a single A10 GPU
- **Deployment:** Custom MLflow `pyfunc` model logged to Unity Catalog, served via Databricks Model Serving GPU endpoint
- **AI Gateway route name:** `qwen3-vl`
- **Created by:** `setup_job` (optional step, skipped if `DEPLOY_OSS_MODEL=false`)

### Optional Two-Stage Pipeline (Detection + Identification)

For images containing multiple products or full shelf displays, a two-stage approach improves accuracy:

1. **Stage 1 — YOLOv8 shelf detector** (`foduucom/product-detection-in-shelf-yolov8`, mAP@0.5 = 0.91): Detects and crops individual product regions from the shelf image, counts items per slot. Runs on CPU.
2. **Stage 2 — VLM (GPT-4o or Qwen3-VL):** Receives the cropped region(s) and returns structured brand/product/size attributes.

The two-stage path is enabled by setting `USE_DETECTION_STAGE=true` in the backend config. When disabled, the full image is sent directly to the VLM (simpler, sufficient for single-product close-up photos).

### Model selector in UI

The frontend model dropdown exposes whichever AI Gateway routes are configured. The `setup_job` writes the list of active routes to a config endpoint (`GET /config/models`) so the frontend doesn't need to be redeployed when routes change.

---

## Data

### `inventory` Delta table (~500 rows)

| Column | Type | Notes |
|---|---|---|
| `sku_id` | STRING | `{CAT}-{BRAND}-{VARIANT}-{SIZE}-{COUNT}` e.g. `TOB-MARL-RED-KS-20` |
| `brand` | STRING | e.g. `Marlboro` |
| `category` | STRING | `tobacco`, `beverage`, `snack` |
| `product_name` | STRING | e.g. `Marlboro Red` |
| `size` | STRING | e.g. `King Size`, `20-pack`, `12oz` |
| `flavor` | STRING | nullable |
| `quantity_on_hand` | INT | Random 0–50, seeded for repeatability |

Category distribution: ~200 tobacco, ~200 beverage, ~100 snack SKUs.

### `scan_log` Delta table (append-only)

| Column | Type | Notes |
|---|---|---|
| `scan_id` | STRING | UUID |
| `scanned_at` | TIMESTAMP | UTC |
| `model_route` | STRING | AI Gateway route used |
| `image_volume_path` | STRING | Path in Unity Catalog volume |
| `model_brand` | STRING | Raw model output |
| `model_product_name` | STRING | Raw model output |
| `model_size` | STRING | Raw model output |
| `matched_sku_id` | STRING | nullable — best fuzzy match |
| `match_score` | FLOAT | RapidFuzz score 0.0–1.0 |
| `quantity_on_hand` | INT | nullable — from inventory table |

---

## Deployment (DAB)

### `databricks.yml` defines:
- **App resource** — React + FastAPI Databricks App
- **Setup job** — one-time provisioning job (idempotent, safe to re-run)
- **Targets** — `dev` and `prod` with separate catalog/schema

### `setup_job` responsibilities (runs as app SP):
1. Create AI Gateway external model serving endpoint (GPT-4o, via Python SDK)
2. *(Optional)* Deploy Qwen3-VL-8B as a custom MLflow model on a GPU serving endpoint; register as AI Gateway route `qwen3-vl` (controlled by `DEPLOY_OSS_MODEL` env var)
3. Create `inventory` Delta table; generate and load ~500 synthetic rows (deterministic seed)
4. Create `scan_log` Delta table
5. Create Unity Catalog volume for image uploads
6. Grant app SP: `USE CATALOG`, `USE SCHEMA`, `SELECT`, `MODIFY` on tables and volume

### Permissions model:
- App runtime uses the app service principal's injected token for all operations
- No hardcoded tokens anywhere in application code
- `setup_job` also runs as the app SP for permission consistency

---

## Project Structure

```
inStockCV/
├── databricks.yml               # DAB bundle definition
├── resources/
│   └── setup_job.yml            # Setup job resource definition
├── app/
│   ├── app.yml                  # Databricks App config
│   ├── backend/
│   │   ├── main.py              # FastAPI app
│   │   ├── analyze.py           # /analyze endpoint
│   │   ├── lookup.py            # /lookup endpoint
│   │   └── requirements.txt
│   └── frontend/
│       ├── src/
│       │   ├── App.tsx
│       │   ├── ScanPanel.tsx
│       │   └── ResultCard.tsx
│       ├── package.json
│       └── vite.config.ts
└── setup/
    ├── create_endpoint.py       # AI Gateway endpoint creation (GPT-4o + optional Qwen3-VL)
    ├── deploy_oss_model.py      # Log + register Qwen3-VL-8B MLflow model (optional)
    ├── create_tables.py         # Delta table creation
    └── generate_inventory.py    # Synthetic data generation
```

---

## Success Criteria (POC)

- Store employee can upload a photo from a phone and receive a result in < 10 seconds
- Fuzzy match returns the correct SKU for clearly-labeled product photos
- Model can be swapped (GPT-4o → Qwen3-VL → Claude) by changing one env var and redeploying
- Open-source Qwen3-VL-8B path deployable with `DEPLOY_OSS_MODEL=true` — no external API calls
- Full environment (tables, endpoint, app) stands up from `databricks bundle deploy` + running the setup job
