# inStockCV — YOLO Two-Stage Detection Pipeline

**Date:** 2026-05-08
**Status:** Approved
**Project:** inStockCV
**Type:** Feature Addition

---

## Overview

Add a two-stage image analysis pipeline to inStockCV. Stage 1 runs a YOLO shelf-product detector (deployed as a Databricks Model Serving endpoint) to localize and crop the product region from the photo. Stage 2 sends the crop to the existing VLM for brand/SKU extraction. This improves accuracy on shelf photos where a product occupies a fraction of the frame.

The detection stage is opt-in via `USE_DETECTION_STAGE=true`. When disabled (default), the existing single-stage full-image VLM path runs unchanged.

---

## Architecture

### Request Flow

```
Phone photo
    │
    ▼
POST /analyze
    │
    ├─ [USE_DETECTION_STAGE=false] ────────────────► full image → VLM → JSON
    │
    └─ [USE_DETECTION_STAGE=true]
           │
           ▼
      YOLO endpoint (instockcv-yolo)
      foduucom/product-detection-in-shelf-yolov8
           │
           ▼
      list[DetectedCrop]          ← array-based from day 1
      [{bbox, confidence, image_bytes, crop_index}, ...]
           │
           ├─ [no detections / low confidence / error] → full image fallback → VLM
           │
           └─ crops[0] (top-1 by confidence)
                  │
                  ▼
             VLM endpoint (databricks-claude-sonnet-4-6)
                  │
                  ▼
             /analyze response
             {…existing fields…, detection_stage, detections: [{bbox, confidence, crop_index}]}
```

### Extensibility Hook (Roadmap)

The `detections` array in the response carries all detected crops, not just the one used. When the multi-select roadmap item lands:
- Frontend presents all crops as thumbnails for user selection
- User selects one or more `crop_index` values
- A follow-up call (or modified `/analyze`) sends each selected crop to the VLM
- No backend API contract change needed — the array is already there

---

## Components

### 1. YOLO Model Serving Endpoint (`instockcv-yolo`)

- **Model:** `foduucom/product-detection-in-shelf-yolov8` (HuggingFace, mAP@0.5 = 0.91)
- **Deployment:** MLflow pyfunc wrapper, logged to Unity Catalog, served on CPU compute (`Small` size, 1 replica)
- **Input:** `{"image": "<base64-encoded image string>"}`
- **Output:** `{"detections": [{"bbox": [x1, y1, x2, y2], "confidence": 0.87, "class": "product"}]}`
- **Endpoint name:** written to `setup/yolo_endpoint_name.txt` by setup job
- **DAB resource:** `resources/yolo_endpoint.yml`

### 2. `setup/deploy_yolo_endpoint.py` (new)

Runs as a task in `setup_job`:
1. Downloads `foduucom/product-detection-in-shelf-yolov8` weights from HuggingFace
2. Wraps in MLflow pyfunc (`YoloPyfunc`) — `predict()` accepts base64 image, returns detections list
3. Logs model to UC (`{catalog}.{schema}.yolo_shelf_detector`)
4. Creates or updates Model Serving endpoint `instockcv-yolo` (CPU, 1 replica)
5. Writes endpoint name to `setup/yolo_endpoint_name.txt`

### 3. `app/backend/detect.py` (new)

Single public function:

```python
def detect_products(image_bytes: bytes, settings: Settings) -> list[DetectedCrop]
```

- Calls `instockcv-yolo` endpoint via OpenAI-compatible client (same pattern as VLM calls)
- Crops image using Pillow for each detection above `yolo_confidence_threshold`
- Returns `list[DetectedCrop]` sorted by confidence descending
- Empty list on any failure (caller decides fallback behavior)

`DetectedCrop` dataclass:
```python
@dataclass
class DetectedCrop:
    crop_index: int
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2 (pixel coords)
    confidence: float
    image_bytes: bytes                 # cropped JPEG bytes
```

### 4. `app/backend/analyze.py` (modified)

When `settings.use_detection_stage=True`:
1. Call `detect.detect_products(image_bytes, settings)`
2. If crops list is non-empty and `crops[0].confidence >= settings.yolo_confidence_threshold`:
   - Use `crops[0].image_bytes` as input to VLM
   - Set `detection_stage = "yolo"`
   - Include all detections (bbox + confidence + crop_index) in response
3. Otherwise (empty list, low confidence, or any error from detect):
   - Use original full image
   - Set `detection_stage = "fallback"`

When `use_detection_stage=False`: `detection_stage = "disabled"`, no `detections` key.

### 5. `app/backend/config.py` (modified)

New settings fields:
```python
yolo_endpoint: str = _default_yolo_endpoint()   # reads setup/yolo_endpoint_name.txt
yolo_confidence_threshold: float = 0.3          # env: YOLO_CONFIDENCE_THRESHOLD
```

`_default_yolo_endpoint()` follows the same two-candidate path pattern as `_default_model_route()`.

`YOLO_CONFIDENCE_THRESHOLD` is declared as a DAB bundle variable in `databricks.yml` (default: `0.3`) and passed into the app as an env var via `app/app.yml`. This lets it be overridden per target without touching app code:

```yaml
# databricks.yml (variables section)
variables:
  yolo_confidence_threshold:
    default: "0.3"
    description: "Minimum YOLO detection confidence to use crop instead of full image"

# app/app.yml (env section)
env:
  - name: YOLO_CONFIDENCE_THRESHOLD
    value: ${var.yolo_confidence_threshold}
```

To tune for a specific target: `databricks bundle deploy --target dev --var yolo_confidence_threshold=0.5`

---

## Error Handling

| Condition | Behavior | `detection_stage` in response |
|-----------|----------|-------------------------------|
| `USE_DETECTION_STAGE=false` | Skip YOLO entirely | `"disabled"` |
| YOLO endpoint unavailable (503/timeout) | Fall back to full image | `"fallback"` |
| YOLO returns 0 detections | Fall back to full image | `"fallback"` |
| Top-1 confidence < threshold (0.3) | Fall back to full image | `"fallback"` |
| PIL crop error | Fall back to full image | `"fallback"` |
| VLM error | Raise 502 (unchanged behavior) | — |

Fallbacks are logged at WARNING level with the reason. The app never returns a 5xx due to a YOLO failure alone.

---

## `/analyze` Response Contract

Existing fields unchanged. Two new fields added:

| Field | Type | Notes |
|-------|------|-------|
| `detection_stage` | string | `"yolo"` \| `"fallback"` \| `"disabled"` |
| `detections` | array \| absent | Present only when `detection_stage="yolo"`. Each item: `{crop_index, bbox: [x1,y1,x2,y2], confidence}` |

---

## New & Changed Files

| File | Change |
|------|--------|
| `setup/deploy_yolo_endpoint.py` | New — MLflow pyfunc wrapper + endpoint creation |
| `setup/yolo_endpoint_name.txt` | New — written by setup job, read by config.py |
| `resources/yolo_endpoint.yml` | New — DAB-managed CPU Model Serving endpoint |
| `resources/setup_job.yml` | Modified — add `deploy_yolo_endpoint` task |
| `app/backend/detect.py` | New — `detect_products()`, `DetectedCrop` dataclass |
| `app/backend/config.py` | Modified — add `yolo_endpoint`, `yolo_confidence_threshold` |
| `app/backend/analyze.py` | Modified — two-stage path when `use_detection_stage=True` |
| `app/requirements.txt` | Modified — add `Pillow` |
| `tests/test_detect.py` | New — mocked YOLO endpoint tests |
| `tests/test_analyze.py` | Modified — add detection stage path coverage |

---

## Testing Strategy

- **`test_detect.py`:** Mock the YOLO endpoint HTTP call. Test: detections returned sorted by confidence; low-confidence detections filtered; empty response returns `[]`; HTTP error returns `[]`.
- **`test_analyze.py`:** Add parametrized tests for `use_detection_stage=True`. Mock both YOLO and VLM. Test: crop path used when YOLO succeeds; full-image fallback when YOLO returns empty; `detection_stage` field present in response.
- Existing 27 tests must remain green (single-stage path unchanged).

---

## Deployment

1. `databricks bundle deploy --target dev` — creates `instockcv-yolo` Model Serving endpoint via DAB
2. `databricks bundle run setup_job --target dev` — runs `deploy_yolo_endpoint` task (logs model, starts endpoint), plus existing tasks
3. Set `USE_DETECTION_STAGE=true` in `app/app.yml` env vars
4. Re-deploy app: `databricks apps deploy instockcv --source-code-path ...`

The YOLO endpoint cold-starts on first request (~30s on CPU). Subsequent requests are fast.

---

## Roadmap (Out of Scope for This Feature)

- **Multi-crop selection:** Frontend shows all `detections` crops as thumbnails. User taps to select one or more. Selected `crop_index` values are sent back to trigger per-crop VLM calls. Response becomes an array of product results.
- **Qwen3-VL-8B OSS model (Optional Task 16):** Deploy self-hosted VLM. Two-stage pipeline works unchanged — VLM is swapped via `MODEL_ROUTE` env var.
