from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.database import Base
from database.models import SignalReceipt, TradeChannelPublication, User
from services.notification import NotificationService


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


@pytest.mark.asyncio
async def test_trade_channel_publication_is_idempotent(monkeypatch):
    db = _session()
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=42))
    )
    try:
        user = User(telegram_id=7001, is_verified=True, is_active=True)
        db.add(user)
        db.flush()
        receipt = SignalReceipt(
            user_id=user.id,
            source="tradingview",
            idempotency_key="receipt-key",
            signal_text="BUY EURUSD",
            status="executed",
        )
        db.add(receipt)
        db.commit()

        from config.settings import settings
        monkeypatch.setattr(settings, "TRADE_RESULTS_CHANNEL_ID", -100123, raising=False)
        service = NotificationService(db, bot)
        result = {
            "success": True,
            "status": "executed",
            "trade_id": "trade-1",
            "signal": {
                "order_type": "Buy",
                "symbol": "EURUSD",
                "entry": 1.1,
                "stop_loss": 1.09,
                "take_profits": [1.12],
            },
            "calculated": {"position_size": 0.1},
        }

        assert await service.publish_trade_execution(receipt.id, result) is True
        assert await service.publish_trade_execution(receipt.id, result) is True
        row = db.query(TradeChannelPublication).filter_by(signal_receipt_id=receipt.id).one()
        assert row.status == "published"
        assert row.telegram_message_id == 42
        bot.send_message.assert_awaited_once()
        assert "7001" not in bot.send_message.await_args.kwargs["text"]
    finally:
        db.close()
