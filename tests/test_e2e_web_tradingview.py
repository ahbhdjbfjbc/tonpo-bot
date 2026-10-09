"""E2E verification: TradingView → pipeline → dry-run; user isolation; SL/TP; no real orders."""
from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tonpo_e2e_web.db")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only")
os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ.setdefault("TRADING_DRY_RUN", "true")
os.environ.setdefault("TRADINGVIEW_WEBHOOK_SECRET", "tv-e2e-secret")
os.environ.setdefault("ADMIN_USER_IDS", "[]")
os.environ.setdefault("ENCRYPTION_KEY", "FKT4wzz7GREEKYGDloNwvaQLa_1EpQgrUpI3Rch65LQ=")


@pytest.fixture
def client(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADINGVIEW_WEBHOOK_SECRET", "tv-e2e-secret", raising=False)
    monkeypatch.setattr(settings, "ENABLE_WEBHOOKS", True, raising=False)
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_TELEGRAM_ID", 111001, raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_SYMBOL_MAP", {}, raising=False)
    monkeypatch.setattr(settings, "JWT_SECRET", "test-jwt-secret-for-unit-tests-only", raising=False)
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:////tmp/tonpo_e2e_web.db", raising=False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["*"], raising=False)
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [], raising=False)
    monkeypatch.setattr(settings, "JWT_EXPIRY_HOURS", 24, raising=False)

    from fastapi.testclient import TestClient
    from web.app import app
    from web.api import webhooks as webhook_module
    monkeypatch.setattr(
        webhook_module, "_get_webhook_cache",
        lambda: type("AllowCache", (), {"check_rate_limit": lambda self, key, limit, period: (True, period)})(),
    )
    with TestClient(app) as c:
        yield c


def _tv_headers(secret="tv-e2e-secret"):
    return {"X-TradingView-Secret": secret, "Content-Type": "application/json"}


def _tv_body(**over):
    b = {
        "symbol": "EURUSD",
        "action": "BUY",
        "stop_loss": 1.0800,
        "take_profits": [1.0950, 1.1000],
        "id": f"e2e-{time.time()}-{os.getpid()}",
        "timestamp": time.time(),
        "strategy": "E2EStrategy",
    }
    b.update(over)
    return b


class TestWebhookSLTP:
    def test_missing_sl_rejected(self, client):
        body = _tv_body()
        del body["stop_loss"]
        r = client.post("/api/webhooks/tradingview", json=body, headers=_tv_headers())
        assert r.status_code == 400

    def test_valid_payload_reaches_pipeline_with_sl_tp(self, client):
        captured = {}

        async def fake_process(envelope, **kwargs):
            captured["payload"] = envelope.payload
            captured["user_id"] = envelope.user_id
            captured["source"] = envelope.source
            return {"success": True, "status": "dry_run", "receipt_id": 42}

        with patch("web.runtime.get_signal_pipeline") as mock_get:
            pipeline = MagicMock()
            pipeline.process = AsyncMock(side_effect=fake_process)
            mock_get.return_value = pipeline
            body = _tv_body(id=f"sltp-{time.time()}")
            r = client.post("/api/webhooks/tradingview", json=body, headers=_tv_headers())
            assert r.status_code == 200
            assert r.json()["status"] == "dry_run"
            assert r.json()["dry_run"] is True
            assert captured["source"] == "tradingview"
            assert captured["user_id"] == 111001
            # Payload must carry SL and TPs into pipeline
            import json
            data = json.loads(captured["payload"])
            assert data["stop_loss"] == 1.0800
            assert data["take_profits"] == [1.0950, 1.1000]
            assert data["action"] == "BUY"
            assert data["symbol"] == "EURUSD"


class TestUserIsolationAPI:
    def test_signals_require_auth(self, client):
        r = client.get("/api/signals")
        assert r.status_code == 401

    def test_trades_require_auth(self, client):
        r = client.get("/api/trades")
        assert r.status_code == 401

    def test_dashboard_requires_auth(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 401

    def test_results_activity_and_news_require_auth(self, client):
        for path in ("/api/results", "/api/activity/today", "/api/news/status"):
            assert client.get(path).status_code == 401


class TestNoManualExecuteEndpoint:
    """Web platform is monitoring + webhook ingress; no web execute endpoint by design."""

    def test_no_post_execute_route(self, client):
        # Common paths that must NOT exist for bypass
        for path in ("/api/trades/execute", "/api/signals/execute", "/api/execute"):
            r = client.post(path, json={})
            assert r.status_code in (404, 405, 401, 422)


class TestMT5HonestState:
    def test_mt5_requires_auth(self, client):
        r = client.get("/api/mt5/status")
        assert r.status_code == 401


class TestHealthDryRun:
    def test_health_reports_dry_run(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["dry_run"] is True


class TestStaticUI:
    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        body = r.text
        assert "dashboard" in body.lower() or "لوحة" in body
        assert "signals" in body.lower() or "الإشارات" in body
        # No hardcoded secrets in HTML
        assert "tv-e2e-secret" not in body
        assert "test-jwt-secret" not in body

    def test_app_js_has_no_execute_button_wiring(self, client):
        r = client.get("/static/js/app.js")
        assert r.status_code == 200
        js = r.text
        # Navigation pages exist
        assert "renderSignals" in js
        assert "renderTrades" in js
        assert "renderMT5" in js
        # No manual execute POST from UI
        assert "/api/trades/execute" not in js
        assert "Manual Execute" not in js
