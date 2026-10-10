"""
Tonpo Web Platform — FastAPI application.

Serves:
  - REST API under /api/*
  - TradingView webhook gateway
  - Professional dark FinTech SPA
"""
from __future__ import annotations

import logging
import time
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
import redis
from services.cache import CacheService, RateLimitUnavailable

from web.cors import LOCAL_DEVELOPMENT_ORIGINS, resolve_cors_origins

from config.settings import settings
from database.database import db_manager
from web.runtime import initialize_web_execution_provider, shutdown_web_execution_provider

logger = logging.getLogger(__name__)
_login_rate_limiter = None

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Tonpo Trading Platform",
    description="Professional trading dashboard & Signal Gateway",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)


@app.on_event("startup")
async def initialize_web_runtime() -> None:
    """Wire webhook execution in this process; Bot memory is not shared here."""
    await initialize_web_execution_provider()


@app.on_event("shutdown")
async def shutdown_web_runtime() -> None:
    await shutdown_web_execution_provider()

app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(
        getattr(settings, 'CORS_ORIGINS', LOCAL_DEVELOPMENT_ORIGINS)
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def safe_request_diagnostics(request: Request, call_next):
    """Log request metadata for auth diagnosis without logging credentials."""
    started = time.perf_counter()
    body = await request.body()
    body_present = bool(body)
    init_data_present = False
    init_data_length = 0
    if request.url.path == "/api/auth/telegram-webapp" and body:
        try:
            payload = json.loads(body)
            init_data = payload.get("init_data") if isinstance(payload, dict) else None
            init_data_present = isinstance(init_data, str) and bool(init_data)
            init_data_length = len(init_data) if isinstance(init_data, str) else 0
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    if request.url.path == "/api/auth/login" and body and getattr(settings, "REDIS_URL", None):
        try:
            payload = json.loads(body)
            telegram_id = payload.get("telegram_id") if isinstance(payload, dict) else None
            if telegram_id is not None:
                global _login_rate_limiter
                if _login_rate_limiter is None:
                    _login_rate_limiter = CacheService()
                allowed, retry_after = _login_rate_limiter.check_rate_limit(
                    f"ratelimit:web-login:{request.client.host if request.client else 'unknown'}:{telegram_id}",
                    10,
                    60,
                )
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Too many login attempts"},
                        headers={"Retry-After": str(max(1, retry_after))},
                    )
        except RateLimitUnavailable:
            return JSONResponse(status_code=503, content={"detail": "Login temporarily unavailable"})
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' https://telegram.org https://cdn.tailwindcss.com; "
        "script-src-attr 'none'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' ws: wss:; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.url.scheme == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.url.path == "/" or request.url.path == "/static/js/app.js":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "HTTP request method=%s path=%s status=%s duration_ms=%s body_present=%s "
        "init_data_present=%s init_data_length=%s content_type=%s",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        body_present,
        init_data_present,
        init_data_length,
        request.headers.get("content-type", ""),
    )
    return response

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
from web.api.results import router as results_router
from web.api.analytics import router as analytics_router
from web.api.protection import router as protection_router
from web.api.subscription import router as subscription_router
from web.api.public import router as public_router

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
app.include_router(results_router)
app.include_router(analytics_router)
app.include_router(protection_router)
app.include_router(subscription_router)
app.include_router(public_router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "tonpo-web",
        "dry_run": bool(getattr(settings, "TRADING_DRY_RUN", True)),
        "readiness_endpoint": "/api/ready",
    }


@app.get("/api/live")
def live():
    """Process liveness; deliberately does not claim dependency readiness."""
    return {"status": "alive", "service": "tonpo-web"}


@app.get("/api/ready")
def ready():
    """Readiness gate for orchestration and traffic routing."""
    checks = {"database": "not_checked", "schema": "not_checked", "redis": "not_checked"}
    try:
        if not getattr(db_manager, "_initialized", False):
            db_manager.initialize(getattr(settings, "DATABASE_URL", None))
        session = db_manager.get_session()
        try:
            session.execute(text("SELECT 1"))
            checks["database"] = "ok"
            version = session.execute(text("SELECT version_num FROM alembic_version")).first()
            if version and version[0]:
                checks["schema"] = str(version[0])
        finally:
            session.close()
    except Exception:
        checks["database"] = "unavailable"
        checks["schema"] = "unavailable"

    redis_url = getattr(settings, "REDIS_URL", None)
    if redis_url:
        try:
            client = redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
            client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "unavailable"
    else:
        checks["redis"] = "not_configured"

    ready_state = checks["database"] == "ok" and checks["schema"] not in {"not_checked", "unavailable"}
    ready_state = ready_state and checks["redis"] == "ok"
    payload = {"status": "ready" if ready_state else "not_ready", "service": "tonpo-web", "checks": checks}
    return JSONResponse(status_code=200 if ready_state else 503, content=payload)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.error("Unhandled error on %s (%s)", request.url.path, type(exc).__name__)
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
