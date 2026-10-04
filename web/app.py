"""
Tonpo Web Platform — FastAPI application.

Serves:
  - REST API under /api/*
  - TradingView webhook gateway
  - Professional dark FinTech SPA
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config.settings import settings

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Tonpo Trading Platform",
    description="Professional trading dashboard & Signal Gateway",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=getattr(settings, "CORS_ORIGINS", ["*"]) or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from web.api.auth import router as auth_router
from web.api.webhooks import router as webhooks_router
from web.api.dashboard import router as dashboard_router
from web.api.signals import router as signals_router
from web.api.trades import router as trades_router
from web.api.mt5 import router as mt5_router
from web.api.risk import router as risk_router
from web.api.settings_api import router as settings_router
from web.api.admin import router as admin_router
from web.api.ws import router as ws_router
from web.api.assistant import router as assistant_router
from web.api.support import router as support_router
from web.api.manual_trade import router as manual_trade_router
from web.api.trading_mode import router as trading_mode_router

app.include_router(auth_router)
app.include_router(webhooks_router)
app.include_router(dashboard_router)
app.include_router(signals_router)
app.include_router(trades_router)
app.include_router(mt5_router)
app.include_router(risk_router)
app.include_router(settings_router)
app.include_router(admin_router)
app.include_router(ws_router)
app.include_router(assistant_router)
app.include_router(support_router)
app.include_router(manual_trade_router)
app.include_router(trading_mode_router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "tonpo-web",
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
    }


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": "Tonpo Web API", "docs": "/api/docs"})


def create_app() -> FastAPI:
    return app
