# YOLO Two-Stage Detection Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a YOLO shelf-product detector (deployed as a Databricks Model Serving endpoint) as Stage 1 in `/analyze`, so product regions are cropped before the VLM sees them, improving accuracy on shelf photos.

**Architecture:** `USE_DETECTION_STAGE=true` triggers a call to the `instockcv-yolo` MLflow pyfunc endpoint, which returns bounding boxes. The FastAPI backend crops the top-1 detection with Pillow and sends it to the VLM instead of the full image. Fallback to full image on any YOLO failure. The response carries a `detections` array (all detected crops) for future multi-select support.

**Tech Stack:** Python 3.11, FastAPI, MLflow pyfunc, ultralytics YOLOv8, Pillow, databricks-sdk, Databricks Asset Bundle (DAB), pytest

---

## File Map

| File | Change |
|------|--------|
| `app/backend/config.py` | Add `yolo_endpoint`, `yolo_confidence_threshold` settings |
| `app/backend/detect.py` | **New** — `DetectedCrop` dataclass + `detect_products()` |
| `app/backend/analyze.py` | Add two-stage path; append `detection_stage` + `detections` to response |
| `app/app.yml` | Add `YOLO_ENDPOINT`, `YOLO_CONFIDENCE_THRESHOLD`, `USE_DETECTION_STAGE` env vars |
| `databricks.yml` | Add `yolo_confidence_threshold` and `use_detection_stage` bundle variables |
| `setup/deploy_yolo_endpoint.py` | **New** — MLflow pyfunc wrapper + endpoint creation, writes `setup/yolo_endpoint_name.txt` |
| `resources/setup_job.yml` | Add `deploy_yolo_endpoint` task + ultralytics/mlflow to environment |
| `tests/test_detect.py` | **New** — mocked unit tests for detect module |
| `tests/test_analyze.py` | Add detection stage path tests |
| `tests/test_config.py` | Add assertions for new settings fields |

---

## Task 1: Add `yolo_endpoint` and `yolo_confidence_threshold` to config

**Files:**
- Modify: `app/backend/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py` — append after the existing test:

```python
def test_settings_yolo_defaults(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("MODEL_ROUTE", "aigwjmr")
    monkeypatch.setenv("INVENTORY_TABLE", "main.instockcv.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "main.instockcv.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/Volumes/main/instockcv/scan_images")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc123")

    import backend.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.get_settings.cache_clear()

    settings = cfg_module.get_settings()
    assert settings.yolo_confidence_threshold == 0.3
    assert isinstance(settings.yolo_endpoint, str)
    assert len(settings.yolo_endpoint) > 0


def test_settings_yolo_threshold_override(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://test.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setenv("MODEL_ROUTE", "aigwjmr")
    monkeypatch.setenv("INVENTORY_TABLE", "main.instockcv.inventory")
    monkeypatch.setenv("SCAN_LOG_TABLE", "main.instockcv.scan_log")
    monkeypatch.setenv("IMAGE_VOLUME_PATH", "/Volumes/main/instockcv/scan_images")
    monkeypatch.setenv("SQL_WAREHOUSE_HTTP_PATH", "/sql/1.0/warehouses/abc123")
    monkeypatch.setenv("YOLO_CONFIDENCE_THRESHOLD", "0.65")

    import backend.config as cfg_module
    importlib.reload(cfg_module)
    cfg_module.get_settings.cache_clear()

    settings = cfg_module.get_settings()
    assert settings.yolo_confidence_threshold == 0.65
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV
pytest tests/test_config.py -v
```

Expected: `AttributeError: 'Settings' object has no attribute 'yolo_confidence_threshold'`

- [ ] **Step 3: Add `_default_yolo_endpoint()` and new fields to `config.py`**

Add after `_default_model_route()` (around line 41) and add two fields to `Settings`:

```python
def _default_yolo_endpoint() -> str:
    """Read YOLO_ENDPOINT default from setup/yolo_endpoint_name.txt."""
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "setup" / "yolo_endpoint_name.txt",
        Path("setup/yolo_endpoint_name.txt"),
    ]
    for path in candidates:
        if path.is_file():
            try:
                return path.read_text().strip()
            except OSError:
                continue
    return "instockcv-yolo"
```

In the `Settings` class, add after `use_detection_stage`:

```python
yolo_endpoint: str = _default_yolo_endpoint()
yolo_confidence_threshold: float = 0.3
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_config.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/backend/config.py tests/test_config.py
git commit -m "feat: add yolo_endpoint and yolo_confidence_threshold to Settings"
```

---

## Task 2: Create `detect.py` — `DetectedCrop` + `detect_products()`

**Files:**
- Create: `app/backend/detect.py`
- Create: `tests/test_detect.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_detect.py`:

```python
"""Unit tests for app.backend.detect."""
import base64
import os
import sys
from dataclasses import dataclass
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

os.environ.update(
    {
        "DATABRICKS_HOST": "https://test.azuredatabricks.net",
        "DATABRICKS_TOKEN": "dapi-test",
        "MODEL_ROUTE": "aigwjmr",
        "INVENTORY_TABLE": "main.instockcv.inventory",
        "SCAN_LOG_TABLE": "main.instockcv.scan_log",
        "IMAGE_VOLUME_PATH": "/tmp/instockcv_images",
        "SQL_WAREHOUSE_HTTP_PATH": "/sql/1.0/warehouses/abc123",
    }
)

from backend.config import get_settings  # noqa: E402
from backend.detect import DetectedCrop, detect_products  # noqa: E402


def _make_test_image(width: int = 100, height: int = 100) -> bytes:
    """Return minimal JPEG bytes for a solid-color test image."""
    img = Image.new("RGB", (width, height), color=(128, 64, 32))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_query_response(detections: list[dict]):
    """Build a mock SDK QueryEndpointResponse with the given detections."""
    response = MagicMock()
    response.predictions = [{"detections": detections}]
    return response


def test_detect_products_returns_sorted_by_confidence():
    settings = get_settings()
    image_bytes = _make_test_image(200, 200)

    raw = [
        {"bbox": [10, 10, 50, 50], "confidence": 0.6, "class": "product"},
        {"bbox": [60, 60, 120, 120], "confidence": 0.9, "class": "product"},
        {"bbox": [130, 10, 180, 60], "confidence": 0.75, "class": "product"},
    ]

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response(raw)
        crops = detect_products(image_bytes, settings)

    assert len(crops) == 3
    assert crops[0].confidence == 0.9
    assert crops[1].confidence == 0.75
    assert crops[2].confidence == 0.6
    assert crops[0].crop_index == 0
    assert crops[1].crop_index == 1
    assert crops[2].crop_index == 2


def test_detect_products_returns_cropped_jpeg_bytes():
    settings = get_settings()
    image_bytes = _make_test_image(200, 200)

    raw = [{"bbox": [10, 10, 80, 80], "confidence": 0.85, "class": "product"}]

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response(raw)
        crops = detect_products(image_bytes, settings)

    assert len(crops) == 1
    crop = crops[0]
    assert isinstance(crop.image_bytes, bytes)
    # Verify it's a valid image
    decoded = Image.open(BytesIO(crop.image_bytes))
    assert decoded.size == (70, 70)  # bbox is 10→80 = 70px wide and tall
    assert crop.bbox == (10, 10, 80, 80)


def test_detect_products_returns_empty_on_no_detections():
    settings = get_settings()
    image_bytes = _make_test_image()

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.return_value = _mock_query_response([])
        crops = detect_products(image_bytes, settings)

    assert crops == []


def test_detect_products_returns_empty_on_endpoint_error():
    settings = get_settings()
    image_bytes = _make_test_image()

    with patch("backend.detect.WorkspaceClient") as MockWC:
        MockWC.return_value.serving_endpoints.query.side_effect = Exception("endpoint unavailable")
        crops = detect_products(image_bytes, settings)

    assert crops == []


def test_detected_crop_dataclass_fields():
    crop = DetectedCrop(
        crop_index=0,
        bbox=(10, 20, 100, 200),
        confidence=0.88,
        image_bytes=b"fake",
    )
    assert crop.crop_index == 0
    assert crop.bbox == (10, 20, 100, 200)
    assert crop.confidence == 0.88
    assert crop.image_bytes == b"fake"
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_detect.py -v
```

Expected: `ModuleNotFoundError: No module named 'backend.detect'`

- [ ] **Step 3: Create `app/backend/detect.py`**

```python
"""Stage 1 detection — calls YOLO serving endpoint, returns cropped product regions."""
from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from backend.config import Settings


@dataclass
class DetectedCrop:
    crop_index: int
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2 (pixel coords)
    confidence: float
    image_bytes: bytes                 # cropped JPEG bytes


def detect_products(image_bytes: bytes, settings: Settings) -> list[DetectedCrop]:
    """Call YOLO endpoint, crop detections, return sorted by confidence desc.

    Returns [] on any failure — callers fall back to full-image VLM path.
    """
    try:
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        b64 = base64.b64encode(image_bytes).decode()
        response = w.serving_endpoints.query(
            name=settings.yolo_endpoint,
            dataframe_records=[{"image": b64}],
        )
        predictions = response.predictions or []
        if not predictions:
            return []
        raw_detections: list[dict] = (
            predictions[0].get("detections", [])
            if isinstance(predictions[0], dict)
            else []
        )
        if not raw_detections:
            return []

        raw_detections.sort(key=lambda d: d["confidence"], reverse=True)

        img = Image.open(BytesIO(image_bytes))
        crops: list[DetectedCrop] = []
        for i, det in enumerate(raw_detections):
            x1, y1, x2, y2 = (int(v) for v in det["bbox"])
            crop_img = img.crop((x1, y1, x2, y2))
            buf = BytesIO()
            crop_img.save(buf, format="JPEG")
            crops.append(
                DetectedCrop(
                    crop_index=i,
                    bbox=(x1, y1, x2, y2),
                    confidence=float(det["confidence"]),
                    image_bytes=buf.getvalue(),
                )
            )
        return crops
    except Exception:
        return []
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/test_detect.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/backend/detect.py tests/test_detect.py
git commit -m "feat: add detect.py with DetectedCrop and detect_products()"
```

---

## Task 3: Wire detection stage into `analyze.py`

**Files:**
- Modify: `app/backend/analyze.py`
- Modify: `tests/test_analyze.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analyze.py` (after existing imports and env setup — keep all existing tests, add these new ones):

```python
from unittest.mock import MagicMock, patch

from backend.detect import DetectedCrop


def _make_jpeg_bytes(width: int = 50, height: int = 50) -> bytes:
    from io import BytesIO
    from PIL import Image
    img = Image.new("RGB", (width, height), color=(100, 100, 100))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_vlm_response(brand: str = "Pepsi") -> MagicMock:
    import json
    payload = json.dumps({
        "brand": brand,
        "category": "beverage",
        "product_name": f"{brand} Zero",
        "size": "20oz",
        "flavor": None,
        "top_3_sku_candidates": [
            {"candidate_name": f"{brand} Zero 20oz", "confidence_score": 0.9}
        ],
    })
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = payload
    return mock_resp


def test_analyze_detection_stage_uses_crop_when_yolo_succeeds(monkeypatch):
    """When use_detection_stage=True and YOLO succeeds, VLM receives the crop bytes."""
    from backend import analyze as analyze_module
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "true")
    monkeypatch.setenv("YOLO_ENDPOINT", "instockcv-yolo")

    crop_bytes = _make_jpeg_bytes(60, 60)
    fake_crops = [
        DetectedCrop(crop_index=0, bbox=(10, 10, 70, 70), confidence=0.88, image_bytes=crop_bytes)
    ]

    captured_b64 = {}

    def fake_create(**kwargs):
        msgs = kwargs.get("messages", [])
        for part in msgs[0]["content"]:
            if part.get("type") == "image_url":
                captured_b64["url"] = part["image_url"]["url"]
        return _mock_vlm_response()

    with patch("backend.detect.detect_products", return_value=fake_crops) as mock_detect, \
         patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.side_effect = fake_create
        import asyncio
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "yolo"
    assert len(data["detections"]) == 1
    assert data["detections"][0]["confidence"] == 0.88
    assert data["detections"][0]["crop_index"] == 0


def test_analyze_detection_stage_falls_back_when_yolo_returns_empty(monkeypatch):
    """When YOLO returns [], full image is sent to VLM and detection_stage='fallback'."""
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "true")
    monkeypatch.setenv("YOLO_ENDPOINT", "instockcv-yolo")

    with patch("backend.detect.detect_products", return_value=[]), \
         patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _mock_vlm_response()
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "fallback"
    assert "detections" not in data


def test_analyze_detection_stage_disabled_by_default(monkeypatch):
    """When use_detection_stage=False (default), detection_stage='disabled'."""
    from backend import config as config_module

    config_module.get_settings.cache_clear()
    monkeypatch.setenv("USE_DETECTION_STAGE", "false")

    with patch("backend.analyze.OpenAI") as MockOpenAI:
        MockOpenAI.return_value.chat.completions.create.return_value = _mock_vlm_response()
        from fastapi.testclient import TestClient
        from backend.main import app
        client = TestClient(app)
        image_bytes = _make_jpeg_bytes(100, 100)
        resp = client.post(
            "/analyze",
            files={"file": ("test.jpg", image_bytes, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["detection_stage"] == "disabled"
    assert "detections" not in data
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_analyze.py -v -k "detection_stage"
```

Expected: `KeyError: 'detection_stage'` (field not in response yet)

- [ ] **Step 3: Modify `app/backend/analyze.py`**

Replace the `analyze` function (lines 72–133) with the two-stage version. Keep everything above the route decorator unchanged:

```python
@router.post("/analyze")
async def analyze(
    file: UploadFile = File(...),
    model_route: str = Form(default=None),
):
    """Vision inference endpoint.

    Body: multipart/form-data with `file` (image) and optional `model_route`.
    Returns: scan_id, model_route, image_volume_path, brand, category,
             product_name, size, flavor, top_3_sku_candidates,
             detection_stage, detections (when stage ran successfully).
    """
    settings = get_settings()
    route = model_route or settings.model_route
    scan_id = str(uuid.uuid4())

    image_bytes = await file.read()
    filename = file.filename or "image.jpg"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    if ext not in ("jpg", "jpeg", "png", "webp"):
        ext = "jpg"

    volume_path = _save_image(image_bytes, ext, scan_id)

    # Stage 1: YOLO detection (optional)
    vlm_image_bytes = image_bytes
    detection_stage = "disabled"
    detections_meta: list[dict] | None = None

    if settings.use_detection_stage:
        from backend.detect import detect_products

        crops = detect_products(image_bytes, settings)
        if crops and crops[0].confidence >= settings.yolo_confidence_threshold:
            vlm_image_bytes = crops[0].image_bytes
            detection_stage = "yolo"
            detections_meta = [
                {"crop_index": c.crop_index, "bbox": list(c.bbox), "confidence": c.confidence}
                for c in crops
            ]
        else:
            detection_stage = "fallback"

    # Stage 2: VLM
    b64 = base64.b64encode(vlm_image_bytes).decode()
    mime = "image/jpeg"

    client = OpenAI(
        api_key=get_databricks_token(settings),
        base_url=f"{settings.databricks_host}/serving-endpoints",
    )
    try:
        response = client.chat.completions.create(
            model=route,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": build_vision_prompt()},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=512,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI Gateway error: {e}") from e

    raw = response.choices[0].message.content or ""
    try:
        parsed = parse_model_response(raw)
    except ModelResponseError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    result = {
        "scan_id": scan_id,
        "model_route": route,
        "image_volume_path": volume_path,
        "detection_stage": detection_stage,
        **parsed,
    }
    if detections_meta is not None:
        result["detections"] = detections_meta
    return result
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/ -v
```

Expected: all 30 tests PASS (27 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add app/backend/analyze.py tests/test_analyze.py
git commit -m "feat: wire YOLO two-stage detection into /analyze"
```

---

## Task 4: Create `setup/deploy_yolo_endpoint.py`

**Files:**
- Create: `setup/deploy_yolo_endpoint.py`

No unit tests for this script — it runs against live Databricks infrastructure. It is written to be idempotent (safe to re-run).

- [ ] **Step 1: Create `setup/deploy_yolo_endpoint.py`**

```python
"""Deploy foduucom/product-detection-in-shelf-yolov8 as an MLflow pyfunc endpoint.

Steps:
  1. Define YoloPyfunc wrapper (ultralytics → detections list)
  2. Log model to Unity Catalog with pip requirements
  3. Create or update 'instockcv-yolo' CPU Model Serving endpoint
  4. Write endpoint name to setup/yolo_endpoint_name.txt

Usage (run as Databricks job task or locally):
    python -m setup.deploy_yolo_endpoint
"""
from __future__ import annotations

import os
import time

ENDPOINT_NAME = "instockcv-yolo"
MODEL_NAME = "yolo_shelf_detector"

try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.getcwd()

DEFAULT_OUTPUT = os.path.join(_here, "yolo_endpoint_name.txt")


def _get_catalog_schema() -> tuple[str, str]:
    catalog = os.environ.get("CATALOG", "vdm_classic_rikfy0_catalog")
    schema = os.environ.get("SCHEMA", "instockcv_dev")
    return catalog, schema


def _log_yolo_model(catalog: str, schema: str) -> str:
    """Log YoloPyfunc to UC. Returns the registered model URI."""
    import mlflow
    import mlflow.pyfunc
    import pandas as pd

    class YoloPyfunc(mlflow.pyfunc.PythonModel):
        def load_context(self, context):
            from ultralytics import YOLO
            self.model = YOLO("foduucom/product-detection-in-shelf-yolov8")

        def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
            import base64
            from io import BytesIO
            from PIL import Image as PILImage

            results = []
            for _, row in model_input.iterrows():
                img_bytes = base64.b64decode(row["image"])
                img = PILImage.open(BytesIO(img_bytes))
                preds = self.model(img)
                detections = []
                for r in preds:
                    for box in r.boxes:
                        detections.append(
                            {
                                "bbox": [round(v, 1) for v in box.xyxy[0].tolist()],
                                "confidence": round(float(box.conf[0]), 4),
                                "class": r.names[int(box.cls[0])],
                            }
                        )
                results.append({"detections": detections})
            return pd.DataFrame(results)

    mlflow.set_registry_uri("databricks-uc")
    full_model_name = f"{catalog}.{schema}.{MODEL_NAME}"

    with mlflow.start_run(run_name="yolo_shelf_detector_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=YoloPyfunc(),
            pip_requirements=[
                "ultralytics>=8.0.0",
                "Pillow>=10.3.0",
            ],
            registered_model_name=full_model_name,
        )
    print(f"Model logged: {model_info.model_uri}")
    return full_model_name


def _create_or_update_endpoint(
    workspace_client, full_model_name: str, model_version: str
) -> None:
    """Create instockcv-yolo endpoint if absent; skip if already READY."""
    from databricks.sdk.service.serving import (
        EndpointCoreConfigInput,
        ServedModelInput,
        ServedModelInputWorkloadSize,
    )

    try:
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        print(f"Endpoint '{ENDPOINT_NAME}' already exists (state: {ep.state}). Skipping creation.")
        return
    except Exception:
        pass  # Does not exist — create it

    print(f"Creating endpoint '{ENDPOINT_NAME}'...")
    workspace_client.serving_endpoints.create(
        name=ENDPOINT_NAME,
        config=EndpointCoreConfigInput(
            served_models=[
                ServedModelInput(
                    model_name=full_model_name,
                    model_version=model_version,
                    workload_size=ServedModelInputWorkloadSize.SMALL,
                    scale_to_zero_enabled=True,
                )
            ]
        ),
    )

    # Wait for READY (up to 10 minutes)
    for _ in range(60):
        ep = workspace_client.serving_endpoints.get(ENDPOINT_NAME)
        state = ep.state.ready if ep.state else None
        print(f"  Endpoint state: {state}")
        if str(state) == "EndpointStateReady.READY":
            print(f"Endpoint '{ENDPOINT_NAME}' is READY.")
            return
        time.sleep(10)
    raise RuntimeError(f"Endpoint '{ENDPOINT_NAME}' did not reach READY within 10 minutes.")


def _get_latest_model_version(workspace_client, full_model_name: str) -> str:
    """Return the latest version number for the registered model."""
    versions = list(
        workspace_client.model_versions.list(full_model_name)
    )
    if not versions:
        raise RuntimeError(f"No versions found for model '{full_model_name}'")
    latest = sorted(versions, key=lambda v: int(v.version), reverse=True)[0]
    return latest.version


def write_endpoint_name(name: str, output_path: str = DEFAULT_OUTPUT) -> None:
    with open(output_path, "w") as f:
        f.write(name + "\n")


def main() -> None:
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    catalog, schema = _get_catalog_schema()
    print(f"Using catalog={catalog} schema={schema}")

    full_model_name = _log_yolo_model(catalog, schema)
    model_version = _get_latest_model_version(w, full_model_name)
    print(f"Model version: {model_version}")

    _create_or_update_endpoint(w, full_model_name, model_version)
    write_endpoint_name(ENDPOINT_NAME)
    print(f"Endpoint name written to: {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add setup/deploy_yolo_endpoint.py
git commit -m "feat: add deploy_yolo_endpoint setup script"
```

---

## Task 5: Wire `deploy_yolo_endpoint` into bundle config

**Files:**
- Modify: `resources/setup_job.yml`
- Modify: `databricks.yml`
- Modify: `app/app.yml`

- [ ] **Step 1: Update `resources/setup_job.yml`**

Replace the entire file with:

```yaml
resources:
  jobs:
    setup_job:
      name: "[inStockCV] Setup"

      tasks:
        - task_key: create_endpoint
          spark_python_task:
            python_file: ../setup/create_endpoint.py
          environment_key: default

        - task_key: deploy_yolo_endpoint
          depends_on:
            - task_key: create_endpoint
          spark_python_task:
            python_file: ../setup/deploy_yolo_endpoint.py
            parameters:
              - --catalog
              - ${var.catalog}
              - --schema
              - ${var.schema}
          environment_key: yolo

        - task_key: provision_tables
          depends_on:
            - task_key: deploy_yolo_endpoint
          spark_python_task:
            python_file: ../setup/create_tables.py
            parameters:
              - --catalog
              - ${var.catalog}
              - --schema
              - ${var.schema}
          environment_key: default

      environments:
        - environment_key: default
          spec:
            client: "1"
            dependencies:
              - "databricks-sdk>=0.28.0"

        - environment_key: yolo
          spec:
            client: "1"
            dependencies:
              - "databricks-sdk>=0.28.0"
              - "ultralytics>=8.0.0"
              - "mlflow>=2.10.0"
              - "Pillow>=10.3.0"
```

- [ ] **Step 2: Add bundle variables to `databricks.yml`**

In the `variables:` block, add after `sql_warehouse_http_path`:

```yaml
  use_detection_stage:
    description: "Enable YOLO two-stage detection in /analyze"
    default: "false"
  yolo_confidence_threshold:
    description: "Minimum YOLO detection confidence to use crop instead of full image"
    default: "0.3"
```

- [ ] **Step 3: Update `app/app.yml` env section**

Add these three env entries to the `env:` list:

```yaml
  - name: USE_DETECTION_STAGE
    value: ${var.use_detection_stage}
  - name: YOLO_CONFIDENCE_THRESHOLD
    value: ${var.yolo_confidence_threshold}
  - name: YOLO_ENDPOINT
    value: instockcv-yolo
```

- [ ] **Step 4: Validate bundle**

```bash
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle validate
```

Expected: `Validation OK`

- [ ] **Step 5: Commit**

```bash
git add resources/setup_job.yml databricks.yml app/app.yml
git commit -m "feat: wire deploy_yolo_endpoint into bundle config"
```

---

## Task 6: Build, deploy, and enable

- [ ] **Step 1: Build frontend**

```bash
cd /Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV/app/frontend && npm run build
```

Expected: `✓ built in ~400ms`

- [ ] **Step 2: Bundle deploy**

```bash
cd /Users/jesus.rodriguez/Documents/ItsAVibe/gitrepos_FY27/inStockCV
DATABRICKS_CONFIG_PROFILE=DEFAULT \
DATABRICKS_TF_EXEC_PATH=/opt/homebrew/bin/terraform \
DATABRICKS_TF_VERSION=1.14.9 \
databricks bundle deploy --target dev \
  --var sql_warehouse_http_path=/sql/1.0/warehouses/5067b513037fbf07
```

Expected: `Deployment complete!`

- [ ] **Step 3: Run setup job**

```bash
DATABRICKS_CONFIG_PROFILE=DEFAULT databricks bundle run setup_job --target dev
```

This will run three tasks in sequence:
1. `create_endpoint` (~10s)
2. `deploy_yolo_endpoint` (~5–10 min — downloads YOLO weights, logs MLflow model, waits for endpoint READY)
3. `provision_tables` (~30s)

Expected final output: `TERMINATED SUCCESS`

- [ ] **Step 4: Enable detection stage and re-deploy app**

Update `app/app.yml` — change the `USE_DETECTION_STAGE` value:

```yaml
  - name: USE_DETECTION_STAGE
    value: "true"
```

Then re-deploy the app:

```bash
databricks apps deploy instockcv \
  --source-code-path /Workspace/Users/jesus.rodriguez@databricks.com/.bundle/instockcv/dev/files/app \
  --profile=DEFAULT
```

Expected: App status `RUNNING`

- [ ] **Step 5: Smoke test**

Upload a product photo to `https://instockcv-1351565862180944.aws.databricksapps.com` and confirm:
- Result appears as normal (brand, SKU, quantity)
- Check backend logs or add a test call to `/analyze` and verify `detection_stage` = `"yolo"` in the response JSON

- [ ] **Step 6: Commit final state**

```bash
git add app/app.yml
git commit -m "feat: enable USE_DETECTION_STAGE=true for dev deployment"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| YOLO deployed as Databricks Model Serving endpoint | Task 4 + 5 |
| `setup/deploy_yolo_endpoint.py` logs pyfunc, creates endpoint | Task 4 |
| `setup/yolo_endpoint_name.txt` written by setup job | Task 4 |
| `yolo_endpoint` + `yolo_confidence_threshold` in Settings | Task 1 |
| `YOLO_CONFIDENCE_THRESHOLD` as DAB bundle variable | Task 5 |
| `detect.py` with `DetectedCrop` + `detect_products()` | Task 2 |
| SDK fallback pattern in `detect_products()` | Task 2 |
| Two-stage path in `analyze.py` | Task 3 |
| `detection_stage` field in response | Task 3 |
| `detections` array (all crops) in response | Task 3 |
| Fallback to full image on any YOLO failure | Task 3 |
| `deploy_yolo_endpoint` task in setup_job with `yolo` environment | Task 5 |
| All 27 existing tests remain green | Task 3 Step 4 |

**Type consistency check:**
- `DetectedCrop.bbox` is `tuple[int,int,int,int]` in detect.py → serialized as `list` in response (via `list(c.bbox)`) ✓
- `detect_products` signature `(image_bytes: bytes, settings: Settings) -> list[DetectedCrop]` used consistently in analyze.py and test_detect.py ✓
- `crops[0].confidence` compared to `settings.yolo_confidence_threshold` (both `float`) ✓
