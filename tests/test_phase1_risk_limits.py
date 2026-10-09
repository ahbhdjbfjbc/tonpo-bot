"""Phase 1: real SignalPipeline -> TradeExecutor risk-limit enforcement."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import settings
from core.models import UnifiedSignal
from database.database import Base
from database.models import SubscriptionPlan, Trade, UserSettings
from database.repositories import UserRepository
from services.signal_pipeline import SignalPipeline
from services.trade_executor import TradeExecutor


class DemoConnection:
    def __init__(self, *, balance=1000.0, equity=1000.0, positions=None):
        self.account = {"balance": balance, "equity": equity, "currency": "USD"}
        self.positions = positions
        self.order_calls = 0

    async def get_account_information(self):
        return dict(self.account)

    async def get_positions(self):
        return self.positions

    async def get_symbol_price(self, symbol):
        return {"bid": 1.0999, "ask": 1.1001}

    async def get_symbol_constraints(self, symbol):
        return {
            "tick_size": 0.0001,
            "tick_value": 10.0,
            "volume_step": 0.1,
            "volume_min": 0.1,
            "volume_max": 2.0,
        }

    async def create_market_buy_order(self, *args, **kwargs):
        self.order_calls += 1
        return {"success": True, "status": "accepted", "orderId": "demo-order"}

    async def verify_market_execution(self, order_id):
        return True


class DemoProvider:
    def __init__(self, connection):
        self.connection = connection

    async def get_connection(self, user_id):
        return self.connection


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def _setup(db):
    user = UserRepository(db).create_user(
        telegram_id=910001, is_active=True, is_verified=True,
        subscription_tier="pro", subscription_expiry=datetime.utcnow() + timedelta(days=30),
        trade_mode="auto",
    )
    db.add(SubscriptionPlan(
        name="Pro", tier="pro", price_monthly=1, price_yearly=10,
        max_trades_per_day=10, max_position_size=10,
        supports_multiple_tps=True, supports_auto_trading=True,
    ))
    db.commit()
    return user


def _signal(external_id):
    return UnifiedSignal(
        source="tradingview", user_id=910001, external_id=external_id,
        payload=(
            '{"action":"BUY","symbol":"EURUSD","entry":1.1,'
            '"stop_loss":1.09,"take_profits":[1.12],"id":"%s"}' % external_id
        ),
    )


def _run(db, connection, signal_id):
    executor = TradeExecutor(db, execution_provider=DemoProvider(connection))
    pipeline = SignalPipeline(db, executor)
    pipeline.news.assess = lambda symbol: {"status": "inactive", "reason": "no event", "events": []}
    return asyncio.run(pipeline.process(_signal(signal_id)))


def test_daily_loss_includes_realized_and_floating_pnl_before_order(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", False, raising=False)
    engine, db = _db()
    try:
        user = _setup(db)
        user.settings.max_daily_loss = 100.0
        db.add(Trade(
            user_id=user.id, order_type="Buy", symbol="EURUSD", entry_price=1.1,
            stop_loss=1.09, take_profits=[1.12], position_size=0.1,
            risk_percentage=1, risk_amount=10, potential_reward=20,
            signal_text="closed", status="executed", profit_loss=-60,
            closed_at=datetime.utcnow(),
        ))
        db.commit()
        connection = DemoConnection(positions=[{"symbol": "EURUSD", "profit": -50.0}])
        result = _run(db, connection, "daily-loss")
        assert result["status"] == "risk_blocked"
        assert result["reason_code"] == "daily_loss"
        assert connection.order_calls == 0
    finally:
        db.close(); engine.dispose()


def test_drawdown_from_persisted_peak_equity_blocks_before_order(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", False, raising=False)
    engine, db = _db()
    try:
        user = _setup(db)
        user.settings.max_drawdown_pct = 10.0
        user.settings.peak_equity = 1000.0
        db.commit()
        connection = DemoConnection(balance=1000.0, equity=850.0, positions=[])
        result = _run(db, connection, "drawdown")
        assert result["status"] == "risk_blocked"
        assert result["reason_code"] == "max_drawdown"
        assert connection.order_calls == 0
    finally:
        db.close(); engine.dispose()


def test_max_open_trades_uses_authoritative_positions_and_persisted_trades(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", False, raising=False)
    engine, db = _db()
    try:
        user = _setup(db)
        user.settings.max_open_trades = 1
        db.add(Trade(
            user_id=user.id, order_type="Buy", symbol="EURUSD", entry_price=1.1,
            stop_loss=1.09, take_profits=[1.12], position_size=0.1,
            risk_percentage=1, risk_amount=10, potential_reward=20,
            signal_text="open", status="pending",
        ))
        db.commit()
        connection = DemoConnection(positions=[])
        result = _run(db, connection, "open-trades")
        assert result["status"] == "risk_blocked"
        assert result["reason_code"] == "max_open_trades"
        assert connection.order_calls == 0
    finally:
        db.close(); engine.dispose()


def test_max_open_positions_blocks_from_broker_snapshot_before_order(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", False, raising=False)
    engine, db = _db()
    try:
        user = _setup(db)
        user.settings.max_open_positions = 1
        db.commit()
        connection = DemoConnection(positions=[{"symbol": "EURUSD", "profit": 0.0}])
        result = _run(db, connection, "open-positions")
        assert result["status"] == "risk_blocked"
        assert result["reason_code"] == "max_open_positions"
        assert connection.order_calls == 0
    finally:
        db.close(); engine.dispose()


def test_missing_equity_or_positions_fails_closed_before_order(monkeypatch):
    monkeypatch.setattr(settings, "TRADING_DRY_RUN", False, raising=False)
    engine, db = _db()
    try:
        user = _setup(db)
        user.settings.max_daily_loss = 100.0
        db.commit()
        connection = DemoConnection(positions=None)
        connection.account.pop("equity")
        result = _run(db, connection, "missing-snapshot")
        assert result["status"] == "risk_blocked"
        assert result["reason_code"] == "account_snapshot_unavailable"
        assert connection.order_calls == 0
    finally:
        db.close(); engine.dispose()
