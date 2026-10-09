"""Manual administrator payment approval safety tests."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config.settings import settings
from database.database import Base
from database.models import AdminAuditLog, PaymentRequest, SubscriptionPlan
from database.repositories import UserRepository
from services.payment import PaymentService


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)


def _setup(Session, telegram_id, monkeypatch):
    db = Session()
    user = UserRepository(db).create_user(telegram_id=telegram_id, is_active=True, is_verified=True)
    user.subscription_tier = "free"
    user.subscription_expiry = None
    db.add(SubscriptionPlan(name="Pro", tier="pro", price_monthly=29.99, price_yearly=299.0))
    db.commit()
    monkeypatch.setattr(settings, "USDT_WALLET_ADDRESS", "admin-test-wallet", raising=False)
    return db, user

def _request(db, user):
    return PaymentService(db).create_payment_request(
        user_id=user.telegram_id, plan_tier="pro", billing_period="monthly", currency="USDT"
    )

def _proof(service, user, pending, tx="tx-1", **extra):
    return service.submit_payment_proof(
        user_id=user.telegram_id, payment_id=pending["payment_id"],
        tx_hash=tx, amount=pending["amount"], currency="USDT", network="ERC20",
        **extra,
    )

def test_request_and_proof_never_activate_without_admin(monkeypatch):
    engine, Session = _db()
    db, user = _setup(Session, 460101, monkeypatch)
    try:
        pending = _request(db, user)
        submitted = _proof(PaymentService(db), user, pending)
        db.refresh(user)
        assert submitted["status"] == "submitted"
        assert user.subscription_tier == "free"
    finally:
        db.close(); engine.dispose()

def test_user_isolation_and_proof_validation(monkeypatch):
    engine, Session = _db()
    db, user_a = _setup(Session, 460102, monkeypatch)
    user_b = UserRepository(db).create_user(telegram_id=460103, is_active=True, is_verified=True)
    db.commit()
    try:
        pending = _request(db, user_a)
        with pytest.raises(ValueError, match="not found"):
            PaymentService(db).submit_payment_proof(
                user_id=user_b.telegram_id, payment_id=pending["payment_id"],
                tx_hash="cross-user", amount=pending["amount"], currency="USDT", network="ERC20"
            )
        with pytest.raises(ValueError, match="amount"):
            PaymentService(db).submit_payment_proof(
                user_id=user_a.telegram_id, payment_id=pending["payment_id"],
                tx_hash="bad-amount", amount="1", currency="USDT", network="ERC20"
            )
        with pytest.raises(ValueError, match="network"):
            PaymentService(db).submit_payment_proof(
                user_id=user_a.telegram_id, payment_id=pending["payment_id"],
                tx_hash="bad-network", amount=pending["amount"], currency="USDT", network="TRC20"
            )
        with pytest.raises(ValueError, match="recipient"):
            PaymentService(db).submit_payment_proof(
                user_id=user_a.telegram_id, payment_id=pending["payment_id"],
                tx_hash="bad-recipient", amount=pending["amount"], currency="USDT", network="ERC20", recipient="wrong"
            )
    finally:
        db.close(); engine.dispose()

def test_only_authorized_admin_can_approve_and_approval_is_audited(monkeypatch):
    engine, Session = _db()
    db, user = _setup(Session, 460104, monkeypatch)
    try:
        pending = _request(db, user)
        _proof(PaymentService(db), user, pending, tx="tx-admin")
        with pytest.raises(PermissionError):
            PaymentService(db).approve_payment(payment_id=pending["payment_id"], admin_id=999999)
        monkeypatch.setattr(settings, "ADMIN_USER_IDS", [900104], raising=False)
        approved = PaymentService(db).approve_payment(payment_id=pending["payment_id"], admin_id=900104)
        db.refresh(user)
        assert approved["status"] == "approved"
        assert user.subscription_tier == "pro"
        audit = db.query(AdminAuditLog).filter_by(action="payment_approve", target_id=pending["payment_id"]).one()
        assert audit.admin_telegram_id == 900104
        assert audit.result == "success"
    finally:
        db.close(); engine.dispose()

def test_approval_replay_and_two_sessions_are_idempotent(monkeypatch):
    engine, Session = _db()
    db, user = _setup(Session, 460105, monkeypatch)
    db2 = None
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [900105], raising=False)
    try:
        pending = _request(db, user)
        _proof(PaymentService(db), user, pending, tx="tx-replay")
        db2 = Session()
        first = PaymentService(db).approve_payment(payment_id=pending["payment_id"], admin_id=900105)
        second = PaymentService(db2).approve_payment(payment_id=pending["payment_id"], admin_id=900105)
        assert first["idempotent"] is False
        assert second["idempotent"] is True
        assert db.query(AdminAuditLog).filter_by(action="payment_approve").count() == 1
    finally:
        if db2 is not None:
            db2.close()
        db.close(); engine.dispose()

def test_duplicate_transaction_cannot_be_reused(monkeypatch):
    engine, Session = _db()
    db, user_a = _setup(Session, 460106, monkeypatch)
    user_b = UserRepository(db).create_user(telegram_id=460107, is_active=True, is_verified=True)
    db.commit()
    try:
        first = _request(db, user_a)
        _proof(PaymentService(db), user_a, first, tx="tx-unique")
        second = PaymentService(db).create_payment_request(user_id=user_b.telegram_id, plan_tier="pro", billing_period="monthly", currency="USDT")
        with pytest.raises(ValueError, match="already assigned"):
            _proof(PaymentService(db), user_b, second, tx="tx-unique")
    finally:
        db.close(); engine.dispose()

def test_expired_rejected_and_already_rejected_cannot_activate(monkeypatch):
    engine, Session = _db()
    db, user = _setup(Session, 460108, monkeypatch)
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", [900108], raising=False)
    try:
        pending = _request(db, user)
        payment = db.query(PaymentRequest).filter_by(uuid=pending["payment_id"]).one()
        payment.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(ValueError, match="expired"):
            _proof(PaymentService(db), user, pending, tx="tx-expired")
        db.refresh(user)
        assert user.subscription_tier == "free"

        fresh = _request(db, user)
        _proof(PaymentService(db), user, fresh, tx="tx-expired-after-submit")
        submitted = db.query(PaymentRequest).filter_by(uuid=fresh["payment_id"]).one()
        submitted.expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(ValueError, match="expired"):
            PaymentService(db).approve_payment(payment_id=fresh["payment_id"], admin_id=900108)
        db.refresh(user)
        assert user.subscription_tier == "free"

        fresh = _request(db, user)
        _proof(PaymentService(db), user, fresh, tx="tx-rejected")
        rejected = PaymentService(db).reject_payment(payment_id=fresh["payment_id"], admin_id=900108, reason="Proof not accepted")
        replay = PaymentService(db).reject_payment(payment_id=fresh["payment_id"], admin_id=900108, reason="ignored")
        assert rejected["status"] == replay["status"] == "rejected"
        with pytest.raises(ValueError, match="not accepting"):
            _proof(PaymentService(db), user, fresh, tx="tx-new")
        db.refresh(user)
        assert user.subscription_tier == "free"
        assert db.query(AdminAuditLog).filter_by(action="payment_reject").count() == 1
    finally:
        db.close(); engine.dispose()

def test_automatic_webhook_path_is_disabled(monkeypatch):
    engine, Session = _db()
    db, _ = _setup(Session, 460109, monkeypatch)
    try:
        with pytest.raises(PermissionError, match="admin approval"):
            PaymentService(db).process_verified_event(b"{}", "anything")
    finally:
        db.close(); engine.dispose()
