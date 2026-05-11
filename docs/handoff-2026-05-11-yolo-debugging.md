# inStockCV — YOLO Two-Stage Pipeline Debugging Handoff

**Date:** 2026-05-11  
**Branch:** `feat/yolo-two-stage-pipeline`  
**App URL:** https://instockcv-1351565862180944.aws.databricksapps.com  
**Workspace:** fe-vm-vdm-classic-rikfy0.cloud.databricks.com

---

## What Was Being Built

A two-stage vision pipeline:
1. **YOLO** (`instockcv-yolo` serving endpoint) — detects product regions in the shelf image and crops the best one
2. **VLM** (Claude Sonnet via `databricks-claude-sonnet-4-6`) — identifies the product from the crop (or full image if YOLO finds nothing)
3. **Fuzzy matcher** — maps the VLM output to an inventory SKU

The intent: YOLO crops away shelf clutter so the VLM sees a clean product view instead of a busy aisle.

---

## Issues Found and Fixed

### 1. YOLO Endpoint Always Returning "fallback"

**Symptom:** Every scan showed `🖼️ Full image / YOLO: no products detected` in the pipeline summary, even for images where YOLO clearly detects products when called directly.

**Root cause:** `detect.py` called `get_databricks_token(settings)` to mint an OAuth token, then passed it explicitly as `Config(token=token, ...)`. Inside Databricks Apps, the platform also injects `DATABRICKS_CLIENT_ID` and `DATABRICKS_CLIENT_SECRET` as env vars. The SDK sees both a PAT token and OAuth m2m credentials simultaneously and raises:

```
ValueError: validate: more than one authorization method configured: oauth and pat
```

This exception was silently caught by `except Exception: return []`, making YOLO always return empty → always fallback.

**How we found it:** Added a temporary `POST /debug/detect` endpoint that called YOLO from within the app context and returned either the raw detections or the full traceback. The traceback revealed the SDK conflict.

**Fix (`detect.py`):**
```python
# Before (broken):
token = get_databricks_token(settings)
w = WorkspaceClient(config=Config(host=..., token=token, http_timeout_seconds=300))

# After (fixed):
# No explicit token — SDK picks up OAuth m2m from env vars automatically
w = WorkspaceClient(config=Config(host=settings.databricks_host, http_timeout_seconds=300))
```

**Commit:** `b77f35d`

---

### 2. `http_timeout_seconds` Earlier Failure

**Context:** Before discovering the auth conflict, we suspected the YOLO endpoint was cold-starting (scale-to-zero) and the default SDK timeout (~60s) was expiring silently.

**Fix attempted:** Added `http_timeout_seconds=300` to `Config` to survive cold-starts. This is still correct and was kept — the parameter is accepted by `Config` via kwargs and applied to HTTP requests.

**Commit:** `7798f4b`

---

### 3. DAB Variable Substitution Does Not Apply to Uploaded Source Files

**Symptom:** After first deploy, `GET /config/models` returned 500. The app crashed on startup.

**Root cause:** `app/app.yml` used DAB variable syntax (`${var.use_detection_stage}`). DAB variable substitution only applies to resource YAML files in `resources/` — it does NOT process files that are uploaded as app source code. The literal string `"${var.use_detection_stage}"` was passed to pydantic-settings, which couldn't parse it as a bool.

**Fix:** Hardcoded values directly in `app/app.yml`:
```yaml
- name: USE_DETECTION_STAGE
  value: "true"
- name: YOLO_CONFIDENCE_THRESHOLD
  value: "0.3"
```

**Commit:** `5c26e3e`

---

### 4. VLM Brand Hallucinations from YOLO Crops

**Symptom:** After YOLO was fixed, scans started returning completely wrong brands:
- Sprite 24-can case → identified as "Doritos Flamin Hot"
- Dr Pepper bottles → identified as "Pepsi Zero Sugar"
- Pringles shelf → identified as "Pepsi Original"

**Root cause:** The YOLO model sometimes crops a region that, without broader image context, is ambiguous or misleading. Claude is then hallucinating a brand it cannot clearly see. The fuzzy matcher correctly matches what Claude returned — the problem was upstream.

**What made it worse:** An attempted fix that added 40% weight to size field comparison inadvertently boosted wrong-brand matches that happened to share a size token. Reverted.

**Fix:** Tightened the VLM prompt to refuse to guess when the label is not legible:
```python
"IMPORTANT: Only identify a product if you can clearly read the brand name from the image. "
"If the image is too small, blurry, or the label is not legible, return brand=null "
"and an empty top_3_sku_candidates array. Do NOT guess a brand you cannot see."
```

**Result:** When Claude can't read the label, the response is "Product not found" instead of a confident wrong match. Better UX for workers — a null tells them to retake the photo; a wrong match sends them to the wrong shelf.

**Commits:** `30099ef` (bad attempt, reverted), `aa63a42` (prompt fix)

---

## Open Issue: Singles vs. Bundle Pack Confusion

**Status: Not resolved**

**Symptom:** A shelf of individual Dr Pepper 20oz bottles is matched to SKU `BEV-DRPE-ORIG-200Z-24PK` (24-pack case) instead of the 1-count single.

**Root cause:** The fuzzy matcher uses `token_sort_ratio` on the full concatenated string `"{brand} {product_name} {size}"`. This metric sorts tokens alphabetically before comparing, so brand and product name tokens dominate. The size differentiator ("24pk" vs "1ct" vs "single") is just one token among many — not enough to distinguish pack counts when everything else is identical.

Example scores (token_sort_ratio, candidate = "Dr Pepper Original 20oz"):
- `Dr Pepper Original 20oz Single` → 0.73
- `Dr Pepper Original 20oz 24pk` → 0.68

The gap is only 0.05, which is often within noise. An attempted fix (40% size weight using VLM's extracted `size` field) improved the singles/bundles discrimination but caused regressions on brand-hallucination cases, so it was reverted.

**Why the size-weight fix caused regressions:** When Claude hallucinates a brand, the candidate name and brand field both contain the wrong brand. Adding size weight then boosts whatever wrong-brand SKU has a similar size, rather than rejecting it.

**Recommended next steps:**

**Option A — Fix the VLM prompt to be more size-specific**  
Add explicit instruction: "If you see individual units on a shelf, note size as '1ct' or 'single'. If you see a case/multipack, note the pack count (e.g., '24pk', '6pk')."  
Currently the VLM sometimes returns "20oz" without specifying pack count, making the matcher's job harder.

**Option B — Staged matching with brand gate first**  
Only apply size weight after confirming brand match. Steps:
1. Filter inventory to rows where `fuzz.token_set_ratio(req.brand, row["brand"]) >= 70`
2. Within that filtered set, score by both full string (60%) + size field (40%)

This prevents size weight from amplifying cross-brand hallucinations (the regression that caused the rollback), while still giving size a stronger voice within the correct brand.

**Option C — Structured size parsing**  
Parse pack-count tokens explicitly: extract numeric quantities from both the VLM output and inventory row size strings, and apply a hard penalty when they differ by more than 2×. E.g., "20oz" (implicitly 1) vs "20oz 24pk" (24 units) → penalty factor of 0.5.

**Option D — Retrain or replace YOLO model**  
The product detection model (`foduucom/product-detection-in-shelf-yolov8` from HuggingFace) is generic. It sometimes crops misleading regions. A model fine-tuned on this store's specific product range would produce cleaner crops and fewer hallucinations downstream.

---

## Deployment Reference

Full redeploy sequence (run from project root):

```bash
# 1. Rebuild frontend if any src/ changes
npm --prefix /path/to/inStockCV/app/frontend run build

# 2. Deploy bundle (uploads workspace files, applies resource permissions)
DATABRICKS_CONFIG_PROFILE=DEFAULT \
DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform \
DATABRICKS_TF_VERSION=1.14.9 \
databricks bundle deploy --target dev \
  --var sql_warehouse_http_path=/sql/1.0/warehouses/5067b513037fbf07

# 3. Deploy app (restarts the FastAPI process from new source)
DATABRICKS_CONFIG_PROFILE=DEFAULT \
databricks apps deploy instockcv \
  --source-code-path /Workspace/Users/jesus.rodriguez@databricks.com/.bundle/instockcv/dev/files/app \
  --profile=DEFAULT
```

Key things to know:
- `bundle deploy` uploads files AND enforces serving endpoint permissions (CAN_QUERY for app SP)
- `apps deploy` restarts the app; settings are re-read on startup (`@lru_cache` on `get_settings()`)
- The YOLO endpoint scales to zero — first query after idle period triggers cold start (~2 min). The 300s SDK timeout handles this.
- App logs: append `/logz` to the app URL (requires browser login)

---

## Files Changed on This Branch

| File | Change |
|------|--------|
| `app/backend/detect.py` | Auth fix (ambient SDK auth), 300s timeout, proper logging |
| `app/backend/analyze.py` | Tightened VLM prompt (no guessing when label unclear) |
| `app/backend/lookup.py` | Reverted to original token_sort_ratio scoring |
| `app/backend/config.py` | `use_detection_stage` bool setting, `yolo_endpoint` setting |
| `app/app.yml` | Hardcoded `USE_DETECTION_STAGE=true`, `YOLO_ENDPOINT=instockcv-yolo` |
| `app/frontend/src/App.tsx` | Loading step indicator (uploading → detecting → analyzing → lookup) |
| `app/frontend/src/ResultCard.tsx` | Pipeline summary (YOLO crop % conf → model → inventory lookup) |
| `app/frontend/src/api.ts` | Added `Detection` type, `detection_stage` field to `AnalyzeResult` |
| `resources/app.yml` | Added `serving_endpoint` resources for YOLO + AI Gateway (CAN_QUERY) |
| `resources/setup_job.yml` | Added `huggingface_hub` to YOLO environment deps |
| `setup/deploy_yolo_endpoint.py` | Bundle weights as MLflow artifact (no HF network call at serve time) |
