# Data Model

All tables live in Unity Catalog under `vdm_classic_rikfy0_catalog.instockcv_dev` (dev target). The catalog and schema are bundle variables, overridable per target.

## Table: `inventory`

Primary reference table. Populated once by the setup job from `setup/generate_inventory.py` (~500 synthetic SKUs). Read-only at runtime.

| Column | Type | Nullable | Description |
|---|---|---|---|
| `sku_id` | STRING | NOT NULL | Deterministic SKU identifier: `{CAT}-{BRAND4}-{VAR4}-{SIZE5}-{PACK}` |
| `brand` | STRING | NOT NULL | Brand name (e.g. `Coca-Cola`, `Marlboro`, `Lays`) |
| `category` | STRING | NOT NULL | One of: `tobacco`, `beverage`, `snack` |
| `product_name` | STRING | NOT NULL | `"{brand} {variant}"` (e.g. `Coca-Cola Zero Sugar`) |
| `size` | STRING | NOT NULL | Size string, optionally suffixed with pack count for multi-packs (e.g. `20oz (6pk)`) |
| `flavor` | STRING | NULL | Variant name if it matches a known flavor keyword, else NULL |
| `quantity_on_hand` | INT | NOT NULL | Synthetic on-hand count, random 0–50 |

**SKU generation axes:** brand × variant × size × pack_count
- Tobacco: 7 brands × ~4 variants × 4 sizes × 2 pack counts (~224 combos)
- Beverage: 8 brands × ~4 variants × 7 sizes × 4 pack counts (~896 combos)
- Snack: 5 brands × ~4 variants × 5 sizes × 3 pack counts (~300 combos)
- Total combinatorial space ~1,300; targets 200 tobacco + 200 beverage + 100 snack = 500 rows

## Table: `scan_log`

Append-only audit log. Written asynchronously via FastAPI `BackgroundTasks` after every `/lookup` call. Failures are swallowed (non-fatal).

| Column | Type | Nullable | Description |
|---|---|---|---|
| `scan_id` | STRING | NOT NULL | UUID generated at `/analyze` time |
| `scanned_at` | TIMESTAMP | NOT NULL | UTC timestamp of the lookup call |
| `model_route` | STRING | NULL | AI Gateway endpoint name used for this scan |
| `image_volume_path` | STRING | NULL | Path to the uploaded image in the UC volume (NULL if save failed) |
| `model_brand` | STRING | NULL | Brand extracted by the vision model |
| `model_product_name` | STRING | NULL | Product name extracted by the vision model |
| `model_size` | STRING | NULL | Size string extracted by the vision model |
| `matched_sku_id` | STRING | NULL | Matched `sku_id` from inventory (NULL if no match) |
| `match_score` | FLOAT | NULL | Raw fuzzy match ratio [0, 1] (before confidence weighting) |
| `quantity_on_hand` | INT | NULL | Quantity at time of scan (NULL if no match) |

## UC Volume: `scan_images`

Stores raw uploaded image bytes. Path pattern: `{IMAGE_VOLUME_PATH}/{scan_id}.{ext}`. Save failures are non-fatal — `image_volume_path` in `scan_log` will be NULL.

## Config Property → Table Name Mapping

| Settings field | Default value | Purpose |
|---|---|---|
| `inventory_table` | `vdm_classic_rikfy0_catalog.instockcv_dev.inventory` | Inventory SELECT queries |
| `scan_log_table` | `vdm_classic_rikfy0_catalog.instockcv_dev.scan_log` | Scan audit INSERT |
| `image_volume_path` | `/tmp/instockcv_images` (local dev) | Image byte storage |
| `sql_warehouse_http_path` | `/sql/1.0/warehouses/5067b513037fbf07` | Warehouse for both tables |
