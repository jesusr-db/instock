# Architecture

## System Component Diagram

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
│  POST /analyze ──► OpenAI-compat client                        │
│                        │                                        │
│                        ▼                                        │
│               AI Gateway endpoint                               │
│               aigwjmr (or databricks-claude-sonnet-4-6)        │
│               Vision model → structured JSON                    │
│                                                                 │
│  POST /lookup  ──► databricks-sql-connector                    │
│                        │                                        │
│                        ▼                                        │
│               Serverless SQL Warehouse                          │
│               SELECT from inventory table                       │
│               rapidfuzz token_sort_ratio match                  │
│               BackgroundTask: INSERT into scan_log              │
│                                                                 │
│  GET /config/models ──► reads MODEL_ROUTE env + ADDITIONAL_    │
│  GET /health        ──► liveness probe                         │
│  GET /             ──► static React SPA (html=True)            │
└──────────────────────────────────┬──────────────────────────────┘
                                   │ Unity Catalog (OAuth m2m)
                                   ▼
┌─────────────────────────────────────────────────────────────────┐
│  Unity Catalog — vdm_classic_rikfy0_catalog.instockcv_dev       │
│                                                                 │
│  Delta Table: inventory  (462 rows, synthetic SKUs)             │
│  Delta Table: scan_log   (append-only audit log)                │
│  UC Volume:   scan_images (uploaded photo bytes)                │
└─────────────────────────────────────────────────────────────────┘
```

## Deployed Resources

| Name | Type | Purpose | Status |
|---|---|---|---|
| `instockcv` | Databricks App | Hosts FastAPI + React SPA | Running |
| `[inStockCV] Setup` | Databricks Job (`setup_job`) | Provisions UC schema, tables, volume, loads inventory, resolves endpoint | ID `913830059117370` |
| `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` | Delta Table | 462 synthetic retail SKUs | Loaded |
| `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` | Delta Table | Append-only scan audit log | Active |
| `vdm_classic_rikfy0_catalog.instockcv_dev.scan_images` | UC Volume | Raw uploaded photo bytes | Active |
| `aigwjmr` | AI Gateway Endpoint | Multi-model vision inference (40% gemma-3-12b-it / 60% gpt-oss-120b) | Active |
| Serverless Starter Warehouse | SQL Warehouse | Inventory queries and scan_log writes | `5067b513037fbf07` |

## Design Decisions

**Why FastAPI serves the React SPA as static files**
Databricks Apps exposes a single port. Rather than running a separate static file server, the React `dist/` directory is mounted at the root path via FastAPI's `StaticFiles(html=True)` — a single process handles both API and SPA. The dist directory is excluded from git (`.gitignore`) but included in the DAB sync via an explicit `sync.include` block so it is uploaded to the workspace.

**Why OAuth m2m instead of a hardcoded token**
Databricks Apps auto-provisions `DATABRICKS_CLIENT_ID` + `DATABRICKS_CLIENT_SECRET` for the app's service principal at deploy time. `get_databricks_token()` in `config.py` prefers `DATABRICKS_TOKEN` when set (local dev) and falls back to `WorkspaceClient().config.authenticate()` (deployed app). This avoids embedding long-lived PATs and makes rotation automatic.

**Why the AI Gateway endpoint name is read from a file**
`setup/create_endpoint.py` resolves the best available endpoint at deploy time and writes its name to `setup/endpoint_name.txt`. `config.py` reads that file at startup so the app never has a hardcoded endpoint name. This decouples endpoint provisioning from application code and survives endpoint renames or workspace migrations.

**Why explicit Spark schema in create_tables.py**
Spark infers Python `int` as `LongType`. The `inventory` DDL defines `quantity_on_hand` as `INT` (`IntegerType`). Delta's overwrite-with-schema-evolution rejects this merge. An explicit `StructType` is passed to `createDataFrame()` to match the DDL exactly.
