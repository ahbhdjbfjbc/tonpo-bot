from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base
from database.models import SubscriptionPlan
from database.repositories import UserRepository
from gateway_client.adapter import GatewayManager


def test_gateway_entitlement_checks_persisted_account_and_fails_closed(monkeypatch):
    import database.database as database_module

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        user = UserRepository(db).create_user(
            telegram_id=880001,
            is_active=True,
            is_verified=True,
            subscription_tier="free",
            subscription_expiry=None,
        )
        db.add(SubscriptionPlan(
            name="Free", tier="free", price_monthly=0, price_yearly=0,
            max_trades_per_day=10, max_position_size=1, max_connections=1,
        ))
        db.commit()
        monkeypatch.setattr(database_module.db_manager, "get_session", lambda: Session())
        manager = GatewayManager()

        assert manager._check_connection_entitlement(880001) == (True, "")
        user.gateway_user_id = "gateway-user"
        user.gateway_account_id = "gateway-account"
        db.commit()
        allowed, reason = manager._check_connection_entitlement(880001)
        assert allowed is False
        assert "already connected" in reason

        def unavailable_database():
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(database_module.db_manager, "get_session", unavailable_database)
        allowed, reason = manager._check_connection_entitlement(880001)
        assert allowed is False
        assert "Unable to verify" in reason
    finally:
        db.close()
        engine.dispose()
