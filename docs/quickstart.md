# Quickstart

## Prerequisites

<!-- NARRATIVE -->
- Databricks workspace access on `fe-vm-vdm-classic-rikfy0.cloud.databricks.com` with a configured `DEFAULT` CLI profile
- `databricks` CLI installed (v0.294+)
- Terraform binary at `/opt/homebrew/bin/terraform` (v1.14.9) — required due to CLI bundled GPG key expiry bug; see [gotchas.md](gotchas.md)
- Node.js 18+ and npm (for frontend build)
- Python 3.10+
<!-- /NARRATIVE -->

## Environment Variables

Copy `.env.example` to `app/.env` and fill in for local development. In Databricks Apps these are injected automatically from `app/app.yml`.

| Variable | Default | Required | Description |
|---|---|---|---|
| `DATABRICKS_HOST` | — | yes | Workspace URL (auto-injected in apps; no `https://` prefix needed — config adds it) |
| `DATABRICKS_TOKEN` | — | local dev | PAT for local dev; omit in Databricks Apps (OAuth m2m is used instead) |
| `MODEL_ROUTE` | read from `setup/endpoint_name.txt`, fallback `instockcv-gateway` | yes | AI Gateway endpoint name |
| `INVENTORY_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` | yes | Fully-qualified Delta table name |
| `SCAN_LOG_TABLE` | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` | yes | Fully-qualified Delta table name |
| `IMAGE_VOLUME_PATH` | `/tmp/instockcv_images` | yes | UC volume path or local `/tmp` fallback |
| `SQL_WAREHOUSE_HTTP_PATH` | `/sql/1.0/warehouses/5067b513037fbf07` | yes | SQL warehouse HTTP path |
| `USE_DETECTION_STAGE` | `false` | no | Enable two-stage YOLO detection pipeline (future) |
| `ADDITIONAL_MODEL_ROUTES` | — | no | Comma-separated extra model routes for the dropdown |

## Deploy Steps

**1. Build the frontend**
```bash
cd app/frontend && npm install && npm run build && cd ../..
```

**2. Validate the bundle**
```bash
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate
```

**3. Deploy**
```bash
DATABRICKS_CONFIG_PROFILE=DEFAULT \
DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform \
DATABRICKS_TF_VERSION=1.14.9 \
  databricks bundle deploy --target dev \
    --var sql_warehouse_http_path=/sql/1.0/warehouses/5067b513037fbf07

databricks apps deploy instockcv \
  --source-code-path /Workspace/Users/jesus.rodriguez@databricks.com/.bundle/instockcv/dev/files/app \
  --profile=DEFAULT
```

**4. Run the setup job** (first deploy only, or to re-seed data)
```bash
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle run setup_job --target dev
```

## Common Commands

```bash
# Run tests
pytest tests/ -v

# Local backend (from app/ directory with app/.env populated)
uvicorn backend.main:app --reload --port 8000

# Local frontend dev server (proxies /analyze, /lookup, /health to :8000)
cd app/frontend && npm run dev

# Validate bundle without deploying
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate

# Check deployed app status
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks apps get instockcv
```

## Known Failure Modes

<!-- NARRATIVE -->
- **`ModuleNotFoundError: No module named 'openai'`** — `requirements.txt` is missing from `app/` root. Copy `app/backend/requirements.txt` to `app/requirements.txt`.
- **`ValidationError: databricks_token Field required`** — Running outside Databricks Apps without `DATABRICKS_TOKEN` set. Set it in `.env` for local dev.
- **`DATABRICKS_HOST` missing `https://`** — The platform omits the scheme. `config.py` adds it in `model_post_init` — but only if the value is non-empty. Ensure the env var is set.
- **AI Gateway 40–60% failure rate** — `aigwjmr` routes 60% of traffic to `gpt-oss-120b`, a text-only model that rejects vision messages. Pin to a vision-only endpoint or override `MODEL_ROUTE` to `databricks-claude-sonnet-4-6`.
<!-- /NARRATIVE -->
