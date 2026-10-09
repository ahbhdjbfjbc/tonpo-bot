"""PHASE 35 deterministic protection, analytics, notifications, and UX contracts."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database.database import Base
from database.models import AdminSetting, SignalReceipt, SubscriptionPlan, Trade
from database.repositories import UserRepository, NotificationRepository
from services.protection import ProtectionService
from services.smart_analytics import SmartAnalyticsService
from services.notification import NotificationService
from core.models import TradeSignal, UnifiedSignal
from services.signal_pipeline import SignalPipeline
from config.constants import OrderType

def db_session():
    engine=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine,sessionmaker(bind=engine)()

def user(db, telegram_id):
    return UserRepository(db).create_user(telegram_id=telegram_id,is_active=True,is_verified=True,subscription_tier="free")

def signal(metadata=None):
    return TradeSignal(order_type=OrderType.BUY,symbol="EURUSD",entry=1.1,stop_loss=1.09,take_profits=[1.12],metadata=metadata or {})

def test_protection_spread_slippage_volatility_and_session_fail_closed():
    engine,db=db_session()
    try:
        u=user(db,350001); u.settings.max_spread=0.0001; u.settings.max_slippage=0.2; u.settings.max_volatility=2.0; u.settings.session_start_utc="09:00"; u.settings.session_end_utc="17:00"; db.commit()
        service=ProtectionService(db)
        assert service.evaluate(u,signal({"bid":1.0,"ask":1.001}))['code']=='spread'
        u.settings.max_spread=None; db.commit(); assert service.evaluate(u,signal({"slippage":0.3}))['code']=='slippage'
        u.settings.max_slippage=None; db.commit(); assert service.evaluate(u,signal({"volatility":3.0}))['code']=='volatility'
        u.settings.max_volatility=None; db.commit(); assert service.evaluate(u,signal(),now=datetime(2026,1,1,2,0,tzinfo=timezone.utc))['code']=='session'
    finally: db.close();engine.dispose()

def test_daily_and_consecutive_loss_protection_and_kill_switch():
    engine,db=db_session()
    try:
        u=user(db,350002); u.settings.max_daily_loss=50; u.settings.max_consecutive_losses=2; db.add_all([Trade(user_id=u.id,order_type="BUY",symbol="EURUSD",entry_price=1.1,stop_loss=1.09,take_profits=[1.12],position_size=1,risk_percentage=.01,risk_amount=10,potential_reward=20,signal_text="x",status="closed",profit_loss=-60,closed_at=datetime.utcnow()), Trade(user_id=u.id,order_type="BUY",symbol="EURUSD",entry_price=1.1,stop_loss=1.09,take_profits=[1.12],position_size=1,risk_percentage=.01,risk_amount=10,potential_reward=20,signal_text="x",status="closed",profit_loss=-10,closed_at=datetime.utcnow()-timedelta(minutes=1))]); db.commit()
        service=ProtectionService(db); assert service.evaluate(u,signal())['code']=='daily_loss'
        u.settings.max_daily_loss=None; db.commit(); assert service.evaluate(u,signal())['code']=='consecutive_loss'
        u.settings.max_consecutive_losses=None; db.add(AdminSetting(key='kill_switch',value='true',updated_by=1)); db.commit(); assert service.evaluate(u,signal())['code']=='kill_switch'
    finally: db.close();engine.dispose()

def test_smart_analytics_is_real_and_user_isolated():
    engine,db=db_session()
    try:
        a=user(db,350003); b=user(db,350004)
        db.add_all([SignalReceipt(user_id=a.id,source="tradingview",idempotency_key="a",signal_text="BUY EURUSD",status="risk_blocked",rejection_reason="Daily loss limit reached",final_decision="rejected",execution_latency_ms=12), SignalReceipt(user_id=b.id,source="tradingview",idempotency_key="b",signal_text="BUY XAUUSD",status="executed",final_decision="executed")])
        db.add(Trade(user_id=a.id,order_type="BUY",symbol="EURUSD",entry_price=1.1,stop_loss=1.09,take_profits=[1.12],position_size=1,risk_percentage=.01,risk_amount=10,potential_reward=20,signal_text="x",status="closed",profit_loss=25,closed_at=datetime.utcnow()))
        db.commit(); result=SmartAnalyticsService(db).summary(a.telegram_id,"all")
        assert result['metrics']['total_signals']==1 and result['metrics']['rejected_signals']==1 and result['metrics']['total_pnl']==25
        assert 'XAUUSD' not in result['symbols']
    finally: db.close();engine.dispose()

def test_notification_event_is_idempotent():
    engine,db=db_session()
    try:
        u=user(db,350005); service=NotificationService(db,bot=None)
        first=asyncio.run(service.notify_event(u.telegram_id,'signal_rejected',title='Signal rejected',message='Daily loss limit reached',event_key='signal:1'))
        second=asyncio.run(service.notify_event(u.telegram_id,'signal_rejected',title='Signal rejected',message='Daily loss limit reached',event_key='signal:1'))
        assert first is True and second is True
        assert db.query(__import__('database.models',fromlist=['Notification']).Notification).filter_by(user_id=u.id,event_key='signal:1').count()==1
    finally: db.close();engine.dispose()

def test_phase35_frontend_routes_and_migration_contract():
    root=__import__('pathlib').Path(__file__).resolve().parents[1]
    js=(root/'web/static/js/app.js').read_text(); html=(root/'web/static/index.html').read_text(); app=(root/'web/app.py').read_text(); mig=(root/'database/migrations/versions/019_competitive_advantage.py').read_text()
    assert '/api/analytics' in js and '/api/protection' in js
    assert 'data-page="analytics"' in html and 'data-page="protection"' in html
    assert 'analytics_router' in app and 'protection_router' in app
    assert 'revision = "019"' in mig and 'down_revision = "018"' in mig


def test_pipeline_persists_complete_phase35_decision_context():
    engine,db=db_session()
    try:
        u=user(db,350006)
        class News:
            def assess(self, symbol): return {"status":"inactive","reason":"No protected event","events":[]}
        class Executor:
            bot=None
            async def execute_trade(self, *args, **kwargs): return {"success":False,"status":"dry_run","error":"Trading is disabled in dry-run mode"}
        pipeline=SignalPipeline(db,Executor()); pipeline.news=News()
        result=asyncio.run(pipeline.process(UnifiedSignal(source="manual",user_id=u.telegram_id,external_id="phase35-ctx",payload="BUY EURUSD\nEntry 1.1000\nSL 1.0900\nTP1 1.1200"),confirmed=True))
        receipt=db.query(SignalReceipt).one()
        assert result["status"] == "dry_run"
        assert receipt.validation_status == "passed" and receipt.risk_status == "passed"
        assert receipt.final_decision == "failed" and receipt.execution_latency_ms is not None
        assert receipt.direction == "LONG" and receipt.signal_id == "phase35-ctx"
    finally: db.close();engine.dispose()
