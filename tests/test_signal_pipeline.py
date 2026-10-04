import json
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import UnifiedSignal
from core.parser import SignalParser
from services.signal_pipeline import SignalPipeline
from database.database import Base
import database.models
from database.repositories import UserRepository
from database.models import AdminSetting, SignalReceipt, SubscriptionPlan


def test_tradingview_authentication_fails_closed_without_configured_secret(monkeypatch):
    from services import signal_pipeline

    monkeypatch.setattr(signal_pipeline.settings, 'TRADINGVIEW_WEBHOOK_SECRET', None, raising=False)
    assert not SignalPipeline.authenticate_tradingview('anything')
    monkeypatch.setattr(signal_pipeline.settings, 'TRADINGVIEW_WEBHOOK_SECRET', 'unit-test-only', raising=False)
    assert SignalPipeline.authenticate_tradingview('unit-test-only')
    assert not SignalPipeline.authenticate_tradingview('wrong')


def test_telegram_channel_authentication_requires_allowlisting(monkeypatch):
    from services import signal_pipeline

    monkeypatch.setattr(signal_pipeline.settings, 'TELEGRAM_SIGNAL_CHANNEL_IDS', [-100123], raising=False)
    assert SignalPipeline.authenticate_telegram_channel(-100123)
    assert not SignalPipeline.authenticate_telegram_channel(-100124)
    monkeypatch.setattr(signal_pipeline.settings, 'TELEGRAM_SIGNAL_CHANNEL_IDS', [], raising=False)
    assert not SignalPipeline.authenticate_telegram_channel(-100123)


def test_tradingview_payload_normalizes_to_shared_signal_format():
    source = UnifiedSignal(
        source='tradingview',
        user_id=7,
        payload=json.dumps({
            'action': 'buy', 'symbol': 'eurusd', 'entry': None,
            'stop_loss': 1.08, 'take_profits': [1.09, 1.10],
        }),
    )
    normalized = SignalPipeline.normalize(source)
    assert normalized.source == 'tradingview'
    assert normalized.user_id == 7
    assert normalized.payload == 'BUY EURUSD\nEntry NOW\nSL 1.08\nTP1 1.09\nTP2 1.1'
    parsed = SignalParser().parse(normalized.payload, source=normalized.source)
    assert parsed.symbol == 'EURUSD'
    assert parsed.take_profits == [1.09, 1.1]


def test_tradingview_normalization_preserves_all_targets_and_requires_object():
    source = UnifiedSignal(
        source='tradingview', user_id=7,
        payload=json.dumps({
            'action': 'SELL', 'symbol': 'EURUSD', 'stop_loss': 1.1,
            'take_profits': [1.09, 1.08, 1.07, 1.06],
        }),
    )
    normalized = SignalPipeline.normalize(source)
    assert 'TP4 1.06' in normalized.payload
    with pytest.raises(ValueError, match='JSON object'):
        SignalPipeline.normalize(UnifiedSignal(
            source='tradingview', user_id=7, payload='[]'
        ))


def test_tradingview_normalization_rejects_incomplete_signal():
    source = UnifiedSignal(source='tradingview', user_id=7, payload='{}')
    with pytest.raises(ValueError, match='requires action'):
        SignalPipeline.normalize(source)


def test_pipeline_persists_idempotency_and_blocks_execution_in_dry_run(monkeypatch):
    from services import signal_pipeline

    monkeypatch.setattr(signal_pipeline.settings, 'TRADING_DRY_RUN', True, raising=False)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        user = UserRepository(db).create_user(telegram_id=54321, is_verified=True)
        db.add(SubscriptionPlan(name='Free', tier='free', price_monthly=0, price_yearly=0,
                                max_trades_per_day=10, max_position_size=1,
                                supports_multiple_tps=False, supports_auto_trading=False))
        db.commit()

        class Executor:
            async def execute_trade(self, *args, **kwargs):
                raise AssertionError('dry-run must not invoke the executor')

        signal = UnifiedSignal(source='manual', user_id=user.telegram_id,
                               payload='BUY EURUSD\nEntry 1.0800\nSL 1.0700\nTP1 1.0900')
        pipeline = SignalPipeline(db, Executor())
        incoming = UnifiedSignal(source='telegram_channel', user_id=user.telegram_id,
                                 external_id='channel:1', payload=signal.payload)
        review = asyncio.run(pipeline.process(incoming))
        assert review['status'] == 'manual_review'
        confirmed = asyncio.run(pipeline.confirm(user.telegram_id, review['receipt_id']))
        assert confirmed['status'] == 'dry_run'
        retried_confirmation = asyncio.run(
            pipeline.confirm(user.telegram_id, review['receipt_id'])
        )
        assert retried_confirmation['status'] == 'already_processed'

        user.trade_mode = 'semi_auto'
        db.commit()
        incoming = UnifiedSignal(source='telegram_channel', user_id=user.telegram_id,
                                 external_id='channel:2', payload=signal.payload)
        review = asyncio.run(pipeline.process(incoming))
        assert review['status'] == 'confirmation_required'
        cancelled = asyncio.run(pipeline.cancel(user.telegram_id, review['receipt_id']))
        assert cancelled['status'] == 'cancelled'

        user.trade_mode = 'auto'
        db.commit()
        incoming = UnifiedSignal(source='telegram_channel', user_id=user.telegram_id,
                                 external_id='channel:3', payload=signal.payload)
        gated = asyncio.run(pipeline.process(incoming))
        assert gated['status'] == 'subscription_required'

        user.trade_mode = 'manual'
        db.commit()
        first = asyncio.run(pipeline.process(signal, confirmed=True))
        second = asyncio.run(pipeline.process(signal, confirmed=True))
        assert first['status'] == 'dry_run'
        assert second['status'] == 'duplicate'
        assert db.query(SignalReceipt).count() == 4
    finally:
        db.close()
        engine.dispose()


def test_pipeline_emergency_stop_blocks_execution_without_bypassing_dry_run(monkeypatch):
    from services import signal_pipeline

    monkeypatch.setattr(signal_pipeline.settings, 'TRADING_DRY_RUN', False, raising=False)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        user = UserRepository(db).create_user(telegram_id=54322, is_verified=True)
        db.add(SubscriptionPlan(name='Free', tier='free', price_monthly=0, price_yearly=0,
                                max_trades_per_day=10, max_position_size=1,
                                supports_multiple_tps=False, supports_auto_trading=False))
        db.add(AdminSetting(key='emergency_stop', value='true', updated_by=1362929493))
        db.commit()

        class Executor:
            async def execute_trade(self, *args, **kwargs):
                raise AssertionError('emergency stop must block executor invocation')

        signal = UnifiedSignal(source='manual', user_id=user.telegram_id,
                               payload='BUY EURUSD\nEntry 1.0800\nSL 1.0700\nTP1 1.0900')
        result = asyncio.run(SignalPipeline(db, Executor()).process(signal, confirmed=True))
        assert result['status'] == 'blocked'
        assert result['error'] == 'Emergency stop is active'
    finally:
        db.close()
        engine.dispose()
