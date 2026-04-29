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
