# API Reference

Base URL (deployed): `https://instockcv-1351565862180944.aws.databricksapps.com`

All endpoints are protected by Databricks OIDC OAuth2 when accessed externally. The React SPA calls them same-origin and inherits the session cookie automatically.

---

## Health & Config

### `GET /health`

Liveness probe. Returns immediately with no DB or model calls.

**Response**
```json
{"status": "ok"}
```

---

### `GET /config/models`

Returns the list of model routes available in the frontend dropdown. Reads `MODEL_ROUTE` from settings as the default, then appends any routes from the `ADDITIONAL_MODEL_ROUTES` env var (comma-separated). Deduplicates while preserving order.

**Response**
```json
{
  "models": ["aigwjmr"],
  "default": "aigwjmr"
}
```

| Field | Type | Description |
|---|---|---|
| `models` | `string[]` | All available model route names |
| `default` | `string` | The primary route (from `MODEL_ROUTE` setting) |

---

## Analyze Router (`analyze.py`)

### `POST /analyze`

Receives a product photo, sends it to the AI Gateway vision endpoint, parses the structured JSON response, and saves the raw image to the UC volume.

**Request** — `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | image file | yes | JPEG, PNG, or WebP product photo |
| `model_route` | string | no | Override the default model route for this request |

**Response** — `200 OK`
```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "model_route": "aigwjmr",
  "image_volume_path": "/Volumes/.../scan_images/550e8400....jpg",
  "brand": "Coca-Cola",
  "category": "beverage",
  "product_name": "Coca-Cola Zero Sugar",
  "size": "20oz",
  "flavor": "Zero Sugar",
  "top_3_sku_candidates": [
    {"candidate_name": "Coca-Cola Zero Sugar 20oz", "confidence_score": 0.95},
    {"candidate_name": "Coca-Cola Zero Sugar 12oz", "confidence_score": 0.72},
    {"candidate_name": "Pepsi Zero Sugar 20oz", "confidence_score": 0.31}
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `scan_id` | string | UUID, generated per request |
| `model_route` | string | Endpoint actually used |
| `image_volume_path` | string \| null | UC volume path where image was saved; null on save failure |
| `brand` | string \| null | Brand name from model |
| `category` | string \| null | `tobacco` \| `beverage` \| `snack` |
| `product_name` | string \| null | Full product name from model |
| `size` | string \| null | Size description from model |
| `flavor` | string \| null | Flavor or null |
| `top_3_sku_candidates` | array | Up to 3 candidates ordered by confidence (highest first) |

**Error responses**
- `502` — AI Gateway error (model call failed)
- `422` — Model returned non-JSON output

---

## Lookup Router (`lookup.py`)

### `POST /lookup`

Fetches the live inventory from the SQL warehouse, fuzzy-matches the top SKU candidates from `/analyze` output, writes a `scan_log` row asynchronously, and returns the match result.

**Request** — `application/json` (mirrors `AnalyzeResult`)

| Field | Type | Required | Description |
|---|---|---|---|
| `scan_id` | string | yes | From `/analyze` response |
| `model_route` | string | yes | From `/analyze` response |
| `image_volume_path` | string \| null | no | For scan_log recording |
| `brand` | string \| null | no | Model-extracted brand |
| `category` | string \| null | no | Model-extracted category |
| `product_name` | string \| null | no | Model-extracted product name |
| `size` | string \| null | no | Model-extracted size |
| `flavor` | string \| null | no | Model-extracted flavor |
| `top_3_sku_candidates` | array | no | `[{candidate_name, confidence_score}]` |

**Matching algorithm**
- For each `(candidate, inventory_row)` pair: `combined = token_sort_ratio(candidate_name, "brand product_name size") / 100 × confidence_score`
- Best match returned only if raw fuzzy ratio ≥ 0.50
- Confidence label: High ≥ 0.85, Medium ≥ 0.65, Low < 0.65

**Response** — `200 OK`
```json
{
  "scan_id": "550e8400-e29b-41d4-a716-446655440000",
  "matched": true,
  "sku_id": "BEV-Coca-ZERO-20oz-1ct",
  "product_name": "Coca-Cola Zero Sugar",
  "brand": "Coca-Cola",
  "size": "20oz",
  "quantity_on_hand": 14,
  "match_score": 0.9412,
  "confidence_label": "High"
}
```

| Field | Type | Description |
|---|---|---|
| `scan_id` | string | Echo of request `scan_id` |
| `matched` | boolean | True if a fuzzy match above threshold was found |
| `sku_id` | string \| null | Matched inventory SKU; null if no match |
| `product_name` | string \| null | From matched inventory row (or model fallback if no match) |
| `brand` | string \| null | From matched inventory row (or model fallback) |
| `size` | string \| null | From matched inventory row (or model fallback) |
| `quantity_on_hand` | integer \| null | Live count from inventory; null if no match |
| `match_score` | float | Raw fuzzy ratio [0, 1]; 0.0 if no match |
| `confidence_label` | string | `"High"` \| `"Medium"` \| `"Low"` |

**Error responses**
- `502` — SQL warehouse connection error

**Side effect (async):** Inserts a row into `scan_log` via `BackgroundTasks`. Failures are swallowed and do not affect the response.
