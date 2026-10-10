from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.database import Base
from database.models import User
from web.api import webhooks


def test_target_users_are_active_subscribers_only(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add_all([
            User(telegram_id=101, is_active=True, is_verified=True, is_banned=False,
                 subscription_tier="pro", subscription_expiry=datetime.utcnow() + timedelta(days=1)),
            User(telegram_id=102, is_active=True, is_verified=True, is_banned=False,
                 subscription_tier="free"),
            User(telegram_id=103, is_active=True, is_verified=True, is_banned=False,
                 subscription_tier="pro", subscription_expiry=datetime.utcnow() - timedelta(days=1)),
            User(telegram_id=104, is_active=False, is_verified=True, is_banned=False,
                 subscription_tier="pro"),
        ])
        db.commit()
        from config.settings import settings
        monkeypatch.setattr(settings, "TRADINGVIEW_BROADCAST_TO_SUBSCRIBERS", True, raising=False)
        assert webhooks._target_user_ids(db) == [101]
    finally:
        db.close()
