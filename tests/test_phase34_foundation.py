"""PHASE 34 foundation tests: trial, advisory AI, plans, and announcements."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from database.database import Base
from database.repositories import UserRepository
from services.ai_assistant import answer, build_user_context
from services.announcements import AnnouncementService
from services.subscription import SubscriptionService, TrialService

def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()

def test_new_user_receives_one_server_side_three_day_trial():
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(telegram_id=340001, is_verified=True)
        assert user.trial_used is True
        assert timedelta(days=2, hours=23) <= user.trial_end - user.trial_start <= timedelta(days=3, minutes=1)
        status = TrialService(db).get_trial_status(user.telegram_id)
        assert status["status"] == "ACTIVE" and status["active"] is True
    finally:
        db.close(); engine.dispose()

def test_expired_trial_cannot_be_restarted():
    engine, db = _db()
    try:
        now = datetime.utcnow()
        user = UserRepository(db).create_user(telegram_id=340002, trial_used=True, trial_start=now-timedelta(days=4), trial_end=now-timedelta(days=1), subscription_tier="free", subscription_expiry=now-timedelta(days=1))
        service = TrialService(db)
        assert service.get_trial_status(user.telegram_id)["status"] == "EXPIRED"
        assert service.start_trial(user.telegram_id)["success"] is False
    finally:
        db.close(); engine.dispose()

def test_ai_context_is_user_scoped_and_advisory_only():
    engine, db = _db()
    try:
        user_a = UserRepository(db).create_user(telegram_id=340003)
        user_b = UserRepository(db).create_user(telegram_id=340004)
        context = build_user_context(db, user_a)
        assert context["telegram_id"] == user_a.telegram_id and str(user_b.telegram_id) not in str(context)
        response = answer("activate live and execute a trade", db=db, user=user_a)
        assert response["intent"] == "refuse_mode_change" and "live" in response["reply"].lower()
    finally:
        db.close(); engine.dispose()

def test_announcement_delivery_is_idempotent_per_user_and_cycle():
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(telegram_id=340005, is_verified=True)
        announcement = AnnouncementService(db).create(title="Product update", message="A safe product notice", created_by=user.id, enabled=True)
        service = AnnouncementService(db)
        cycle = service.cycle_key()
        assert service.claim(announcement.id, user.id, cycle) is True
        assert service.claim(announcement.id, user.id, cycle) is False
        assert service.delivery_status(announcement.id, cycle)["total"] == 1
    finally:
        db.close(); engine.dispose()

def test_announcement_cycle_sends_once_and_does_not_retry_reserved_claim():
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(telegram_id=340006, is_verified=True)
        AnnouncementService(db).create(title="Daily notice", message="Read the latest update", created_by=user.id, enabled=True)
        bot = type("Bot", (), {"send_message": AsyncMock()})()
        service = AnnouncementService(db)
        first = asyncio.run(service.deliver_cycle(bot)); second = asyncio.run(service.deliver_cycle(bot))
        assert first["sent"] == 1 and second["sent"] == 0 and second["skipped"] == 1
        assert bot.send_message.await_count == 1
    finally:
        db.close(); engine.dispose()

def test_phase34_frontend_and_migration_contracts():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    js = (root / "web/static/js/app.js").read_text(); html = (root / "web/static/index.html").read_text(); migration = (root / "database/migrations/versions/018_announcements.py").read_text()
    assert "/api/admin/announcements" in js and "announcement" in js.lower() and "assistant" in html.lower()
    assert 'revision = "018"' in migration and 'down_revision = "017"' in migration and "announcement_deliveries" in migration
