"""WebSocket auth and isolation tests."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tonpo_ws_test.db")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only")
os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ.setdefault("TRADING_DRY_RUN", "true")
os.environ.setdefault("TRADINGVIEW_WEBHOOK_SECRET", "tv-test-secret")
os.environ.setdefault("ADMIN_USER_IDS", "[]")


@pytest.fixture
def client(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret-for-unit-tests-only", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:////tmp/tonpo_ws_test.db", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"], raising=False)
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        yield c


def test_ws_rejects_without_token(client):
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert data.get("type") == "error" or "Unauthorized" in str(data.get("detail", ""))


def test_health_still_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
