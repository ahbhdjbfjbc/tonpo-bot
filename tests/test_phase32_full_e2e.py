"""PHASE 32 deterministic end-to-end dry-run verification."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from bot.handlers import CommandHandlers
from core.models import UnifiedSignal
from database.database import Base
from database.models import SignalReceipt, SubscriptionPlan, User
from database.repositories import UserRepository
from services.results import ResultsService
from services.signal_pipeline import SignalPipeline
from web.api.signals import list_signals
from web.app import app
from web.deps import get_db


USER_ID = 321001


class FreshNews:
    def __init__(self, status="inactive"):
        self.status = status

    def assess(self, symbol):
        if self.status == "inactive":
            return {"status": "inactive", "reason": "No relevant high-impact event", "events": []}
        return {"status": self.status, "reason": f"mock {self.status}", "events": []}


class DryRunExecutor:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"success": False, "status": "dry_run", "error": "Trading is disabled in dry-run mode"}

    async def execute_trade(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return dict(self.result)


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _setup_user(db, telegram_id=USER_ID, *, tier="pro", expiry_days=30, trade_mode="auto"):
    user = UserRepository(db).create_user(
        telegram_id=telegram_id, is_active=True, is_verified=True,
        subscription_tier=tier, subscription_expiry=datetime.utcnow() + timedelta(days=expiry_days),
        trade_mode=trade_mode,
    )
    db.add(SubscriptionPlan(
        name="Pro", tier="pro", price_monthly=1, price_yearly=10,
        max_trades_per_day=10, max_position_size=10, supports_multiple_tps=True,
        supports_auto_trading=True, supports_api=True,
    ))
    db.add(SubscriptionPlan(
        name="Free", tier="free", price_monthly=0, price_yearly=0,
        max_trades_per_day=1, max_position_size=1, supports_multiple_tps=False,
        supports_auto_trading=False, supports_api=False,
    ))
    db.commit()
    return user


def _envelope(external_id="e2e-1", user_id=USER_ID):
    return UnifiedSignal(
        source="tradingview", user_id=user_id, external_id=external_id,
        payload='{"action":"BUY","symbol":"EURUSD","entry":1.1,"stop_loss":1.09,"take_profits":[1.12],"id":"%s"}' % external_id,
    )


def _body(external_id="web-e2e-1", **extra):
    body = {
        "symbol": "EURUSD", "action": "BUY", "entry": 1.1, "stop_loss": 1.09,
        "take_profits": [1.12], "timestamp": datetime.now(timezone.utc).isoformat(),
        "id": external_id,
    }
    body.update(extra)
    return body


def test_full_happy_path_webhook_pipeline_persistence_centers_and_telegram(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_WEBHOOK_SECRET", "phase32-test-secret", raising=False)
    monkeypatch.setattr(settings, "ENABLE_WEBHOOKS", True, raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_TELEGRAM_ID", USER_ID, raising=False)
    monkeypatch.setattr(settings, "TRADINGVIEW_SYMBOL_MAP", {}, raising=False)
    monkeypatch.setattr(settings, "ALLOWED_SYMBOLS", ["EURUSD"], raising=False)
    engine, db = _db()
    _setup_user(db)
    executor = DryRunExecutor()
    pipeline = SignalPipeline(db, executor)
    pipeline.news = FreshNews("inactive")
    from web.api import webhooks as webhook_module
    monkeypatch.setattr(
        webhook_module, "_get_webhook_cache",
        lambda: type("AllowCache", (), {"check_rate_limit": lambda self, key, limit, period: (True, period)})(),
    )
    app.dependency_overrides[get_db] = lambda: db
    try:
        with patch("web.runtime.get_signal_pipeline", return_value=pipeline), TestClient(app) as client:
            response = client.post("/api/webhooks/tradingview", json=_body(), headers={"X-TradingView-Secret": "phase32-test-secret"})
        assert response.status_code == 200
        assert response.json()["status"] == "dry_run"
        assert response.json()["dry_run"] is True
        assert len(executor.calls) == 1
        receipt = db.query(SignalReceipt).one()
        assert receipt.status == "dry_run"
        assert receipt.news_status == "inactive"
        assert receipt.rejection_reason == "Trading is disabled in dry-run mode"
        user = db.query(User).filter_by(telegram_id=USER_ID).one()
        signals = list_signals(user=user, db=db, limit=50, offset=0, status=None, source=None)
        assert signals["total"] == 1 and signals["items"][0]["status"] == "dry_run"
        results = ResultsService(db).results(USER_ID, "all")
        assert results["has_signals"] is True and results["signals"][0]["status"] == "dry_run"
        message = Mock(); message.reply_text = AsyncMock()
        update = Mock(effective_user=Mock(id=USER_ID), message=message)
        handlers = CommandHandlers(db, None)
        asyncio.run(handlers.signals(update, None))
        assert "dry_run" in message.reply_text.await_args.args[0]
    finally:
        app.dependency_overrides.clear()
        db.close(); engine.dispose()


def test_duplicate_and_concurrent_same_signal_have_one_executor_call(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    engine, db = _db(); _setup_user(db)
    executor = DryRunExecutor(); pipeline = SignalPipeline(db, executor); pipeline.news = FreshNews()
    async def run_concurrent():
        return await asyncio.gather(pipeline.process(_envelope("concurrent")), pipeline.process(_envelope("concurrent")))
    try:
        first, second = asyncio.run(run_concurrent())
        assert sorted([first["status"], second["status"]]) == ["dry_run", "duplicate"]
        assert len(executor.calls) == 1
        assert db.query(SignalReceipt).count() == 1
        duplicate = asyncio.run(pipeline.process(_envelope("concurrent")))
        assert duplicate["status"] == "duplicate"
    finally:
        db.close(); engine.dispose()


@pytest.mark.parametrize("news_status,expected", [("active", "news_blocked"), ("stale", "news_stale"), ("unavailable", "news_unavailable")])
def test_news_rejection_paths_never_reach_executor(monkeypatch, news_status, expected):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    engine, db = _db(); _setup_user(db)
    executor = DryRunExecutor(); pipeline = SignalPipeline(db, executor); pipeline.news = FreshNews(news_status)
    try:
        result = asyncio.run(pipeline.process(_envelope("news-" + news_status)))
        assert result["status"] == expected
        assert len(executor.calls) == 0
        receipt = db.query(SignalReceipt).one()
        assert receipt.status == expected and receipt.news_status == news_status
        assert receipt.rejection_reason == "mock " + news_status
    finally:
        db.close(); engine.dispose()


def test_subscription_inactive_and_symbol_constraints_are_persisted_rejections(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    engine, db = _db(); user = _setup_user(db, tier="free", expiry_days=-1)
    user.allowed_symbols = ["GBPUSD"]; db.commit()
    executor = DryRunExecutor(); pipeline = SignalPipeline(db, executor); pipeline.news = FreshNews()
    try:
        result = asyncio.run(pipeline.process(_envelope("constraint")))
        assert result["status"] == "invalid"
        assert len(executor.calls) == 0
        assert db.query(SignalReceipt).one().rejection_reason == "Symbol is not enabled for this account"
    finally:
        db.close(); engine.dispose()


def test_unknown_execution_is_persisted_and_not_blindly_retried(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    engine, db = _db(); _setup_user(db)
    executor = DryRunExecutor({"success": False, "status": "unknown", "error": "safe unknown"})
    pipeline = SignalPipeline(db, executor); pipeline.news = FreshNews()
    try:
        first = asyncio.run(pipeline.process(_envelope("unknown")))
        second = asyncio.run(pipeline.process(_envelope("unknown")))
        assert first["status"] == "unknown"
        assert second["status"] == "unknown" and second["reconciliation_required"] is True
        assert len(executor.calls) == 1
    finally:
        db.close(); engine.dispose()
