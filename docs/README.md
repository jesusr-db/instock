# inStockCV

inStockCV is a mobile-optimized Databricks App (React + FastAPI) that lets retail store employees photograph a product on a shelf, extract the SKU via AI-powered vision inference against an AI Gateway endpoint, and immediately see the live inventory quantity — all from a phone browser with no app install. The backend runs FastAPI on Databricks Apps with OAuth m2m auth; the frontend is a Vite-bundled React SPA served as static files; inventory data lives in Delta tables on Unity Catalog; and all scans are logged to a `scan_log` table for audit and analytics.

| Document | Description |
|---|---|
| [architecture.md](architecture.md) | System component diagram, deployed resources, and key design decisions |
| [data-model.md](data-model.md) | Delta table schemas and inventory data model |
| [dataflow.md](dataflow.md) | End-to-end flow from photo capture to inventory result |
| [api.md](api.md) | All backend endpoints: method, path, params, response shape |
| [quickstart.md](quickstart.md) | Prerequisites, env vars, deploy steps, common commands |
| [gotchas.md](gotchas.md) | Non-obvious platform behaviors and workarounds |

---

_Last regenerated: 2026-05-08_
