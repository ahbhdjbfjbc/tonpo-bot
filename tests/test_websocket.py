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


def test_spa_response_has_csp_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    csp = response.headers.get("content-security-policy", "")
    assert "script-src-attr 'none'" in csp
    assert "object-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp



def test_ws_authenticates_with_first_frame_and_tolerates_non_object_messages(client, monkeypatch):
    from types import SimpleNamespace
    from web.api import ws as ws_api

    user = SimpleNamespace(id=71, is_active=True, is_banned=False, has_gateway_credentials=False)

    class FakeDB:
        def expire_all(self):
            pass

        def close(self):
            pass

    db = FakeDB()
    monkeypatch.setattr(ws_api.db_manager, "_initialized", True, raising=False)
    monkeypatch.setattr(ws_api.db_manager, "get_session", lambda: db)
    monkeypatch.setattr(ws_api, "_auth_user", lambda token, _db: user if token == "valid-test-token" else None)
    monkeypatch.setattr(ws_api, "_snapshot", lambda _db, _user: {"type": "snapshot", "user_id": 71})

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "token": "valid-test-token"})
        assert ws.receive_json()["type"] == "connected"
        assert ws.receive_json() == {"type": "snapshot", "user_id": 71}
        ws.send_json(["not", "an", "object"])
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
