from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.exceptions import SubscriptionError
from database.database import Base
from database.models import PaymentRequest, SubscriptionPlan
from database.repositories import UserRepository
from services.subscription import SubscriptionService


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_legacy_upgrade_cannot_activate_from_unverified_payment_metadata():
    db = _db()
    user = UserRepository(db).create_user(telegram_id=730001, is_active=True, is_verified=True)
    db.add(SubscriptionPlan(
        name="Pro", tier="pro", price_monthly=10, price_yearly=100,
        max_trades_per_day=10, max_position_size=1, supports_auto_trading=True,
    ))
    db.commit()
    original_tier = user.subscription_tier

    with pytest.raises(SubscriptionError, match="admin-controlled"):
        SubscriptionService(db).upgrade_user(
            user.telegram_id, "pro", payment_id="caller-supplied-id", tx_hash="claimed-tx"
        )
    db.refresh(user)
    assert user.subscription_tier == original_tier


def test_even_verified_metadata_cannot_bypass_manual_admin_activation():
    db = _db()
    user = UserRepository(db).create_user(telegram_id=730002, is_active=True, is_verified=True)
    original_tier = user.subscription_tier
    with pytest.raises(SubscriptionError, match="admin-controlled"):
        SubscriptionService(db).upgrade_user(
            user.telegram_id, "pro", payment_id="caller-value", tx_hash="caller-value"
        )
    db.refresh(user)
    assert user.subscription_tier == original_tier
