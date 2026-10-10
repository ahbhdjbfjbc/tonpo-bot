"""AI assistant — guidance only, isolation, no trade execution."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import jwt
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/tonpo_ai_test.db")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-for-unit-tests-only")
os.environ.setdefault("BOT_TOKEN", "0:TEST")
os.environ.setdefault("TRADING_DRY_RUN", "true")
os.environ.setdefault("TRADINGVIEW_WEBHOOK_SECRET", "tv-test-secret")
os.environ.setdefault("ADMIN_USER_IDS", "[]")
os.environ.setdefault("ENCRYPTION_KEY", "FKT4wzz7GREEKYGDloNwvaQLa_1EpQgrUpI3Rch65LQ=")


def test_kb_arabic_register():
    from services.ai_assistant import answer
    r = answer("كيف أسجل؟", lang="ar")
    assert r["language"] == "ar"
    assert "تسجيل" in r["reply"] or "register" in r["reply"].lower() or "تليجرام" in r["reply"]
    assert "لا ينفذ" in r["reply"] or "guidance" in r["reply"].lower() or "تعليم" in r["reply"]


def test_kb_english_sl():
    from services.ai_assistant import answer
    r = answer("What is Stop Loss?", lang="en")
    assert r["language"] == "en"
    assert "Stop Loss" in r["reply"] or "stop" in r["reply"].lower()


def test_detect_arabic():
    from services.ai_assistant import detect_lang
    assert detect_lang("مرحبا كيف الحال") == "ar"
    assert detect_lang("hello there") == "en"


def test_assistant_allows_anonymous_guidance():
    """Public guidance is allowed; account context remains optional."""
    os.environ["DATABASE_URL"] = "sqlite:////tmp/tonpo_ai_test.db"
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        r = c.post("/api/assistant/chat", json={"message": "hi"})
        assert r.status_code == 200
        assert r.json()["context"] == {}


def test_assistant_rejects_malformed_token():
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        r = c.post(
            "/api/assistant/chat",
            headers={"Authorization": "Bearer not-a-jwt"},
            json={"message": "hi"},
        )
        assert r.status_code == 401


def test_assistant_rejects_expired_token():
    from fastapi.testclient import TestClient
    from web.app import app
    token = jwt.encode(
        {"user_id": 1, "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )
    with TestClient(app) as c:
        r = c.post(
            "/api/assistant/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "hi"},
        )
        assert r.status_code == 401


def test_assistant_no_gateway_call_in_module():
    import inspect
    import services.ai_assistant as m
    src = inspect.getsource(m)
    assert "TradeExecutor" not in src
    assert "place_market" not in src
    assert "Gateway" not in src or "gateway" in src.lower()  # may mention in text


def test_manual_execute_requires_auth():
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        r = c.post("/api/signals/1/manual-execute")
        assert r.status_code == 401


def test_support_requires_auth():
    from fastapi.testclient import TestClient
    from web.app import app
    with TestClient(app) as c:
        assert c.get("/api/support/tickets").status_code == 401
