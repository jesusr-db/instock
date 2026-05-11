"""FastAPI application entry point.

Wires the /analyze and /lookup routers, exposes /health and /config/models,
and serves the React build from app/frontend/dist/ at the root path.
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.analyze import router as analyze_router
from backend.config import get_settings
from backend.lookup import router as lookup_router

app = FastAPI(title="inStockCV", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router)
app.include_router(lookup_router)


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/debug/detect")
def debug_detect() -> dict:
    """Temporary: test YOLO endpoint from app context. Remove after debugging."""
    import base64, time, traceback
    from pathlib import Path
    settings = get_settings()
    # Use a tiny 1x1 white JPEG so we don't need a real image file
    tiny_jpeg = (
        b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
        b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
        b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
        b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e\x1e'
        b'\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e\x1e'
        b'\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00'
        b'\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00'
        b'\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00'
        b'\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81'
        b'\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19'
        b'\x1a%&\'()*456789:CDEFGHIJKLMNOPQRSTUVWXYZ'
        b'cdefghijklmnopqrstuvwxyz\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb'
        b'd\x00\x00\x00\x00\xff\xd9'
    )
    try:
        from backend.detect import detect_products
        t0 = time.time()
        crops = detect_products(tiny_jpeg, settings)
        elapsed = time.time() - t0
        return {
            "use_detection_stage": settings.use_detection_stage,
            "yolo_endpoint": settings.yolo_endpoint,
            "yolo_confidence_threshold": settings.yolo_confidence_threshold,
            "databricks_host": settings.databricks_host,
            "elapsed_s": round(elapsed, 2),
            "crops": len(crops),
            "error": None,
        }
    except Exception as e:
        return {
            "use_detection_stage": settings.use_detection_stage,
            "yolo_endpoint": settings.yolo_endpoint,
            "error": traceback.format_exc(),
        }


@app.get("/config/models")
def config_models() -> dict:
    """Return the list of model routes the frontend may select."""
    settings = get_settings()
    models = [settings.model_route]
    extra = os.environ.get("ADDITIONAL_MODEL_ROUTES", "")
    if extra:
        models += [m.strip() for m in extra.split(",") if m.strip()]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for m in models:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return {"models": unique, "default": settings.model_route}


# Serve React build — must be registered last (catch-all).
_static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
