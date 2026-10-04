"""Per-user trading_mode isolation + dry-run barrier."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tonpo_mode_test.db")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only")
os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ.setdefault("TRADING_DRY_RUN", "true")
os.environ.setdefault("TRADINGVIEW_WEBHOOK_SECRET", "tv-test-secret")
os.environ.setdefault("ADMIN_USER_IDS", "[]")
os.environ.setdefault("ENCRYPTION_KEY", "FKT4wzz7GREEKYGDloNwvaQLa_1EpQgrUpI3Rch65LQ=")


@pytest.fixture
def client(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret-for-unit-tests-only", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:////tmp/tonpo_mode_test.db", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"], raising=False)
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)
    monkeypatch.setattr(settings, "JWT_EXPIRY_HOURS", 24, raising=False)

    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        yield c


def test_mode_requires_auth(client):
    assert client.get("/api/trading-mode").status_code == 401
    assert client.patch("/api/trading-mode", json={"mode": "demo"}).status_code == 401


def test_live_without_confirm_rejected(client, monkeypatch):
    """Patch get_current_user to a fake user with trading_mode."""
    from database.models import User
    from web import deps

    user = MagicMock(spec=User)
    user.id = 1
    user.telegram_id = 9001
    user.trading_mode = "demo"
    user.has_gateway_credentials = False
    user.subscription_tier = "free"

    def fake_user():
        return user

    # Override dependency
    from web.app import app
    from web.deps import get_current_user, get_db

    app.dependency_overrides[get_current_user] = lambda: user

    # Minimal db session mock for audit
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock()
    app.dependency_overrides[get_db] = lambda: session

    try:
        r = client.patch("/api/trading-mode", json={"mode": "live", "confirm_live": False})
        assert r.status_code == 400
        assert "confirm" in r.json()["detail"].lower() or "confirm_live" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_live_with_confirm_ok_and_still_dry_run_env(client):
    from database.models import User
    from web.app import app
    from web.deps import get_current_user, get_db

    user = MagicMock(spec=User)
    user.id = 2
    user.telegram_id = 9002
    user.trading_mode = "demo"
    user.has_gateway_credentials = False
    user.subscription_tier = "free"

    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.refresh = MagicMock(side_effect=lambda u: setattr(u, "trading_mode", "live"))

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: session
    try:
        r = client.patch("/api/trading-mode", json={"mode": "live", "confirm_live": True})
        assert r.status_code == 200
        body = r.json()
        assert body["mode"] == "live"
        assert body["dry_run_env"] is True
        assert body["real_orders_possible"] is False
        assert user.trading_mode == "live"
    finally:
        app.dependency_overrides.clear()


def test_invalid_mode(client):
    from web.app import app
    from web.deps import get_current_user, get_db
    from database.models import User

    user = MagicMock(spec=User)
    user.id = 3
    user.telegram_id = 9003
    user.trading_mode = "demo"
    session = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: session
    try:
        r = client.patch("/api/trading-mode", json={"mode": "paper", "confirm_live": True})
        assert r.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_ai_refuses_live_activation():
    from services.ai_assistant import answer
    r = answer("فعّل live من فضلك", lang="ar")
    assert r["intent"] == "refuse_mode_change"
    assert "لا أستطيع" in r["reply"] or "cannot" in r["reply"].lower()


def test_ai_explains_demo():
    from services.ai_assistant import answer
    r = answer("ما هو وضع DEMO؟", lang="ar")
    assert r["language"] == "ar"
    assert "DEMO" in r["reply"] or "تجريب" in r["reply"]


def test_dry_run_setting_unchanged():
    from config.settings import settings
    assert bool(getattr(settings, "TRADING_DRY_RUN", True)) is True
