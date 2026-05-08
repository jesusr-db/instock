# Dataflow

## End-to-End Flow

```
User (mobile browser)
        │
        │ 1. Tap to take photo / select image
        │
        ▼
   ScanPanel.tsx
        │ handleFileChange → stores File object + local preview URL
        │
        │ 2. Tap "Check Inventory"
        │
        ▼
   analyzeImage() [api.ts]
        │ POST /analyze   multipart/form-data
        │ fields: file (image bytes), model_route (string)
        │
        ▼
   POST /analyze  [analyze.py]
        │
        ├─► _save_image() — writes bytes to UC volume (or /tmp fallback)
        │       returns image_volume_path (or None on OSError)
        │
        ├─► base64-encode image
        │
        ├─► OpenAI client → AI Gateway /serving-endpoints/{model_route}
        │       payload: vision message with base64 image + structured prompt
        │       max_tokens: 512
        │
        ├─► parse_model_response() — strips ```json fences, JSON.parse
        │
        └─► returns AnalyzeResult JSON:
                scan_id, model_route, image_volume_path,
                brand, category, product_name, size, flavor,
                top_3_sku_candidates [{candidate_name, confidence_score}×3]
        │
        ▼
   lookupSku() [api.ts]
        │ POST /lookup   application/json
        │ body: full AnalyzeResult
        │
        ▼
   POST /lookup  [lookup.py]
        │
        ├─► _fetch_inventory() — SELECT sku_id, brand, product_name, size,
        │       quantity_on_hand FROM inventory via SQL warehouse
        │
        ├─► fuzzy_match_candidates()
        │       for each (candidate, inventory_row):
        │         fuzzy = token_sort_ratio(candidate_name, "brand product_name size") / 100
        │         combined = fuzzy × confidence_score
        │       returns best row where raw fuzzy >= 0.50
        │
        ├─► score_to_label() → High (≥0.85) / Medium (≥0.65) / Low
        │
        ├─► BackgroundTask: _write_scan_log() — INSERT into scan_log (async, non-fatal)
        │
        └─► returns LookupResult JSON:
                scan_id, matched, sku_id, product_name, brand, size,
                quantity_on_hand, match_score, confidence_label
        │
        ▼
   ResultCard.tsx
        ├─► matched=true:  product_name, brand · size, SKU, qty (color-coded), match badge
        └─► matched=false: "Product not found in inventory" message
```

## Pipeline Refresh Cadence

The `inventory` table is loaded once by the setup job and is **static** — it does not refresh automatically. `quantity_on_hand` values are synthetic and do not reflect real-time stock changes. In a production deployment, this table would be replaced or refreshed by an ETL pipeline fed from a POS or WMS system.

The `scan_log` table grows with every scan. No retention policy is currently configured.

## Sync Status

The AI Gateway endpoint name is resolved at setup_job time by `setup/create_endpoint.py` and written to `setup/endpoint_name.txt`. The app reads this file at startup via `_default_model_route()` in `config.py`. If the file is missing (e.g. fresh clone without running setup), the fallback is `"instockcv-gateway"` — the `MODEL_ROUTE` env var must be set explicitly in that case.
