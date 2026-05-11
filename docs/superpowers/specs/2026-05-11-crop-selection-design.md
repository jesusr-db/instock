# Crop Selection UX — Design Spec
**Date:** 2026-05-11  
**Branch:** `accuracyimprovements`  
**Status:** Approved

---

## Problem

The current pipeline sends the full image (or YOLO's auto-selected best crop) directly to VLM with no worker input. When YOLO picks a bad crop (e.g., the 202×57 Pringles sliver at 0.32 confidence), the worker has no way to correct it — they only see the wrong result.

---

## Solution

Split the pipeline into two explicit steps with a user-controlled crop selection screen between them:

1. **Detect** — run YOLO, return bounding box coordinates to the client
2. **Select** — worker taps a YOLO box or draws their own crop on the image
3. **Analyze** — send original image + selected coordinates to VLM

---

## UX Flow

### Happy path (YOLO finds regions)

```
Upload image
    ↓
POST /detect  (YOLO only — fast, no VLM)
    ↓
Crop-select screen:
  - Original image displayed full-width
  - YOLO bboxes overlaid as tappable rectangles with confidence %
  - "Draw my own" button always visible
  - Worker taps a box (or draws) → box highlights
  - "Analyze →" confirm button sends selected coords
    ↓
POST /analyze (original file + crop_x1/y1/x2/y2)
    ↓
POST /lookup → ResultCard (unchanged)
```

### Zero detections path

```
POST /detect → crops: []
    ↓
Crop-select screen:
  - Warning banner: "No regions detected — draw around the product or analyze full image"
  - Full image shown, no YOLO boxes
  - "Draw my own" button highlighted (primary action)
  - "Use full image" button available as secondary action
  - Worker draws a box OR taps "Use full image"
    ↓
POST /analyze (file + coords, or file only for full image)
    ↓
POST /lookup → ResultCard
```

---

## App States

| State | Trigger |
|-------|---------|
| `idle` | Initial / after reset |
| `detecting` | POST /detect in flight |
| `crop-select` | /detect returned (0 or more crops) |
| `analyzing` | POST /analyze in flight |
| `lookup` | POST /lookup in flight |
| `result` | Lookup complete |
| `error` | Any request failed |

---

## API Changes

### New: `POST /detect`

**Input:** `multipart/form-data` with `file` (image)

**Output:**
```json
{
  "crops": [
    { "crop_index": 0, "bbox": [x1, y1, x2, y2], "confidence": 0.87 },
    { "crop_index": 1, "bbox": [x1, y1, x2, y2], "confidence": 0.72 },
    { "crop_index": 2, "bbox": [x1, y1, x2, y2], "confidence": 0.45 }
  ]
}
```

No `scan_id` — `/detect` is a bbox query, not a scan record. The scan is created when `/analyze` runs.

- Runs YOLO via `detect_products()` from `detect.py` (existing logic, no duplication)
- Returns raw bbox pixel coordinates (original image space)
- Returns empty `crops: []` when nothing detected — never errors on zero detections
- Does NOT call VLM

### Modified: `POST /analyze`

New optional form fields: `crop_x1`, `crop_y1`, `crop_x2`, `crop_y2` (integers, image pixel coords)

**Behavior:**
- If all four crop fields provided: skip YOLO, crop the image server-side using PIL, send crop to VLM. `detection_stage` = `"user-crop"`.
- If no crop fields: current behavior (run YOLO if `use_detection_stage=true`, then VLM).

Response shape unchanged — `POST /lookup` requires no modifications.

---

## Frontend Components

### `CropSelector.tsx` (new)

**Props:**
```ts
interface CropSelectorProps {
  imageFile: File            // original image for display
  crops: DetectCrop[]        // YOLO bboxes (may be empty)
  onConfirm: (coords: [number, number, number, number] | null) => void
  // null → use full image
}
```

**Behavior:**
- Renders the image onto an `<img>` tag (or canvas) at full container width
- Overlays YOLO bboxes as absolutely-positioned `<div>` borders, scaled to display size
- Each bbox div is tappable — tap highlights it (blue border, semi-transparent fill), deselects others
- **"Draw my own" button:** enters draw mode — subsequent touch/mouse drag on image draws a dashed rectangle; release confirms the drawn box; another tap on "Draw my own" re-enters draw mode
- Confirm button disabled until a selection exists (YOLO box tapped OR box drawn)
- "Use full image" link calls `onConfirm(null)`
- Zero crops: same UI but no YOLO boxes, warning banner shown, draw-my-own is the primary CTA

**Coordinate scaling:**
- `scaleX = naturalWidth / displayWidth`, `scaleY = naturalHeight / displayHeight`
- Bbox display: divide natural coords by scale → CSS pixels
- On confirm: multiply drawn/selected display coords by scale → natural image coords → send to backend

### `App.tsx` changes

New state values: `'detecting'` and `'crop-select'`

```
handleSubmit(file):
  setState('detecting')
  result = await detectCrops(file)        // POST /detect
  storeFile(file)
  storeCrops(result.crops)
  setState('crop-select')

handleCropConfirm(coords | null):
  setState('analyzing')
  analyzeResult = await analyzeImage(file, model, coords)   // POST /analyze
  setState('lookup')
  lookupResult = await lookupSku(analyzeResult)
  setState('result')
```

Loading steps strip:
- `'detecting'` → "Detecting products (YOLO)" (already in STEPS list — no change needed)
- Strip is hidden during `crop-select` (worker is acting, not waiting)

### `api.ts` changes

```ts
// New
export interface DetectResult {
  crops: DetectCrop[]
}
export interface DetectCrop {
  crop_index: number
  bbox: [number, number, number, number]
  confidence: number
}

export async function detectCrops(file: File): Promise<DetectResult>

// Modified signature — coords is [x1,y1,x2,y2] in original image pixels, or null for full image
export async function analyzeImage(
  file: File,
  modelRoute: string,
  cropCoords?: [number, number, number, number]
): Promise<AnalyzeResult>
```

---

## Backend Files

| File | Change |
|------|--------|
| `app/backend/detect_route.py` | New — FastAPI router with `POST /detect` |
| `app/backend/analyze.py` | Accept `crop_x1/y1/x2/y2` form fields; crop image before VLM when provided |
| `app/main.py` | Register `detect_route.router` |
| `app/frontend/src/api.ts` | Add `detectCrops()`, update `analyzeImage()` |
| `app/frontend/src/CropSelector.tsx` | New component |
| `app/frontend/src/App.tsx` | New states, updated `handleSubmit` flow |

---

## Error Handling

- `/detect` failure → skip crop-select, go directly to `'error'` state
- `/analyze` with bad coords (out of bounds) → backend clamps with PIL (same as existing bbox clamping in `detect.py`), never errors
- Worker submits without selecting → confirm button is disabled (client-side guard)

---

## Out of Scope

- Saving or replaying user-drawn crops
- Multi-crop selection (pick more than one region)
- Crop history / undo
- Confidence threshold UI controls
