"""Focused PHASE 29 coverage for real results and news fail-closed behavior."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import UnifiedSignal
from database.database import Base
from database.models import SignalReceipt, SubscriptionPlan, Trade
from database.repositories import UserRepository
from services.news_protection import NewsEvent, NewsProtectionService
from services.results import ResultsService
from services.signal_pipeline import SignalPipeline


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_results_use_only_closed_persisted_trades():
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(telegram_id=29001)
        db.add(Trade(
            user_id=user.id, order_type="Buy", symbol="EURUSD", entry_price=1.1,
            stop_loss=1.09, take_profits=[1.12], position_size=0.1,
            risk_percentage=1, risk_amount=10, potential_reward=20,
            signal_text="BUY EURUSD", status="closed", profit_loss=25,
            closed_at=datetime.utcnow(), execution_results=[],
        ))
        db.add(Trade(
            user_id=user.id, order_type="Buy", symbol="GBPUSD", entry_price=1.2,
            stop_loss=1.19, take_profits=[1.22], position_size=0.1,
            risk_percentage=1, risk_amount=10, potential_reward=20,
            signal_text="BUY GBPUSD", status="executed", profit_loss=999,
            closed_at=None, execution_results=[],
        ))
        db.commit()
        result = ResultsService(db).results(user.telegram_id, "all")
        assert result["metrics"]["total_closed_trades"] == 1
        assert result["metrics"]["total_pnl"] == 25
    finally:
        db.close()
        engine.dispose()


def test_news_protection_active_and_provider_failure_fail_closed(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "NEWS_PROTECTION_ENABLED", True, raising=False)
    event = NewsEvent("event-1", "USD", "high", datetime.now(timezone.utc) + timedelta(minutes=5), "Test event")
    active = NewsProtectionService(provider=type("Provider", (), {"fetch": lambda self: [event]})()).assess("EURUSD")
    assert active["status"] == "active"

    unavailable = NewsProtectionService(provider=type("Provider", (), {"fetch": lambda self: (_ for _ in ()).throw(RuntimeError("provider unavailable"))})()).assess("EURUSD")
    assert unavailable["status"] == "unavailable"


def test_pipeline_blocks_new_trade_when_news_data_unavailable(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "NEWS_PROTECTION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", True, raising=False)
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(telegram_id=29002, is_verified=True)
        db.add(SubscriptionPlan(name="Free", tier="free", price_monthly=0, price_yearly=0, max_trades_per_day=10, max_position_size=1, supports_multiple_tps=False, supports_auto_trading=False))
        db.commit()

        class Executor:
            bot = None
            async def execute_trade(self, *args, **kwargs):
                raise AssertionError("news block must prevent execution")

        pipeline = SignalPipeline(db, Executor())
        pipeline.news = NewsProtectionService(provider=type("Provider", (), {"fetch": lambda self: (_ for _ in ()).throw(RuntimeError("unavailable"))})())
        result = asyncio.run(pipeline.process(UnifiedSignal(
            source="manual", user_id=user.telegram_id,
            payload="BUY EURUSD\nEntry 1.10\nSL 1.09\nTP1 1.12",
        ), confirmed=True))
        assert result["status"] == "news_unavailable"
        receipt = db.query(SignalReceipt).filter_by(user_id=user.id).one()
        assert receipt.status == "news_unavailable"
        assert receipt.news_status == "unavailable"
    finally:
        db.close()
        engine.dispose()
