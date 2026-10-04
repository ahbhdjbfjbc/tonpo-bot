"""Tests for TradingView Signal Gateway (/api/webhooks/tradingview)."""
from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ["DATABASE_URL"] = "sqlite:////tmp/tonpo_webhook_test.db"
os.environ["JWT_SECRET"] = "test-jwt-secret-for-unit-tests-only"
os.environ["BOT_TOKEN"] = "0:TEST"
os.environ["TRADING_DRY_RUN"] = "true"
os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = "tv-test-secret"
os.environ["ADMIN_USER_IDS"] = "[]"
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMmJ5dGVzISE=")


@pytest.fixture
def client(monkeypatch):
    from config.settings import settings
    # conftest injects a lightweight _TestSettings; attach webhook attrs
    monkeypatch.setattr(settings, "TRADINGVIEW_WEBHOOK_SECRET", "tv-test-secret", raising=False)
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:////tmp/tonpo_webhook_test.db", raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret-for-unit-tests-only", raising=False)
    monkeypatch.setattr(settings, "JWT_EXPIRY_HOURS", 24, raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"], raising=False)
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)

    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        yield c


def _headers(secret: str = "tv-test-secret"):
    return {"X-TradingView-Secret": secret, "Content-Type": "application/json"}


def _payload(**overrides):
    base = {
        "symbol": "EURUSD",
        "action": "BUY",
        "stop_loss": 1.0800,
        "take_profits": [1.0950, 1.1000],
        "user_id": 123456789,
        "id": f"sig-{time.time()}-{os.getpid()}",
        "timestamp": time.time(),
    }
    base.update(overrides)
    return base


class TestWebhookAuth:
    def test_unauthorized_missing_secret(self, client):
        r = client.post("/api/webhooks/tradingview", json=_payload())
        assert r.status_code == 401

    def test_unauthorized_wrong_secret(self, client):
        r = client.post(
            "/api/webhooks/tradingview",
            json=_payload(),
            headers=_headers("wrong"),
        )
        assert r.status_code == 401


class TestWebhookValidation:
    def test_malformed_json(self, client):
        r = client.post(
            "/api/webhooks/tradingview",
            content=b"not-json",
            headers=_headers(),
        )
        assert r.status_code == 400

    def test_missing_required_fields(self, client):
        r = client.post(
            "/api/webhooks/tradingview",
            json={"symbol": "EURUSD", "user_id": 1},
            headers=_headers(),
        )
        assert r.status_code == 400

    def test_invalid_action(self, client):
        r = client.post(
            "/api/webhooks/tradingview",
            json=_payload(action="HOLD"),
            headers=_headers(),
        )
        assert r.status_code == 400

    def test_missing_stop_loss(self, client):
        p = _payload()
        del p["stop_loss"]
        r = client.post("/api/webhooks/tradingview", json=p, headers=_headers())
        assert r.status_code == 400


class TestWebhookReplayAndIdempotency:
    def test_replay_protection(self, client):
        with patch("web.runtime.get_signal_pipeline") as mock_get:
            pipeline = MagicMock()
            pipeline.process = AsyncMock(return_value={"success": True, "status": "dry_run"})
            mock_get.return_value = pipeline

            pid = f"unique-replay-{time.time()}"
            p = _payload(id=pid)
            r1 = client.post("/api/webhooks/tradingview", json=p, headers=_headers())
            assert r1.status_code in (200, 400, 500)
            r2 = client.post("/api/webhooks/tradingview", json=p, headers=_headers())
            assert r2.status_code == 409

    def test_stale_timestamp(self, client):
        r = client.post(
            "/api/webhooks/tradingview",
            json=_payload(timestamp=time.time() - 9999, id=f"stale-{time.time()}"),
            headers=_headers(),
        )
        assert r.status_code == 400


class TestWebhookHappyPathDryRun:
    def test_valid_signal_reaches_pipeline(self, client):
        with patch("web.runtime.get_signal_pipeline") as mock_get:
            pipeline = MagicMock()
            pipeline.process = AsyncMock(
                return_value={"success": True, "status": "dry_run", "receipt_id": 1}
            )
            mock_get.return_value = pipeline

            r = client.post(
                "/api/webhooks/tradingview",
                json=_payload(id=f"ok-{time.time()}"),
                headers=_headers(),
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "dry_run"
            assert body["dry_run"] is True
            pipeline.process.assert_awaited_once()


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["dry_run"] is True
