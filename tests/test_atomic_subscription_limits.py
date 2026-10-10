from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base
import database.models  # register all ORM tables
from database.models import SubscriptionPlan
from database.repositories import UserRepository
from services.subscription import SubscriptionService


def _database(limit=1):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    user = UserRepository(session).create_user(telegram_id=567890, is_verified=True)
    session.add(SubscriptionPlan(
        name="Free", tier="free", price_monthly=0, price_yearly=0,
        max_trades_per_day=limit, max_position_size=1,
        supports_multiple_tps=False, supports_auto_trading=False,
    ))
    session.commit()
    return engine, session, user


def test_daily_trade_slot_is_reserved_atomically_across_sessions():
    engine, first_session, user = _database(limit=1)
    second_session = sessionmaker(bind=engine)()
    try:
        first = SubscriptionService(first_session)
        second = SubscriptionService(second_session)

        allowed, info = first.reserve_trade_slot(user.telegram_id)
        denied, limit_info = second.reserve_trade_slot(user.telegram_id)

        assert allowed is True
        assert info["current"] == 1
        assert denied is False
        assert limit_info["current"] == 1
    finally:
        second_session.close()
        first_session.close()
        engine.dispose()


def test_reservation_rolls_over_without_a_racy_read_reset():
    engine, session, user = _database(limit=1)
    try:
        user.daily_trades = 1
        user.last_trade_date = datetime.utcnow() - timedelta(days=1)
        session.commit()

        allowed, info = SubscriptionService(session).reserve_trade_slot(user.telegram_id)

        session.refresh(user)
        assert allowed is True
        assert info["current"] == 1
        assert user.daily_trades == 1
        assert user.last_trade_date.date() == datetime.utcnow().date()
    finally:
        session.close()
        engine.dispose()


def test_failed_reservation_can_be_released_and_success_totals_are_separate():
    engine, session, user = _database(limit=2)
    try:
        service = SubscriptionService(session)
        allowed, info = service.reserve_trade_slot(user.telegram_id)
        assert allowed is True
        service.release_trade_slot(user.telegram_id, info["reserved_at"])
        session.commit()
        session.refresh(user)
        assert user.daily_trades == 0
        assert user.total_trades == 0

        allowed, info = service.reserve_trade_slot(user.telegram_id)
        assert allowed is True
        service.record_trade_statistics(user.telegram_id, 0.25)
        session.commit()
        session.refresh(user)
        assert user.daily_trades == 1
        assert user.total_trades == 1
        assert user.total_volume == 0.25
    finally:
        session.close()
        engine.dispose()


def test_create_user_translates_concurrent_unique_race_to_duplicate_account():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        repository = UserRepository(session)
        existing = repository.create_user(telegram_id=765432, is_verified=True)
        original_get = repository.get_by_telegram_id
        first_lookup = True

        def simulate_racing_preflight(telegram_id):
            nonlocal first_lookup
            if first_lookup:
                first_lookup = False
                return None
            return original_get(telegram_id)

        repository.get_by_telegram_id = simulate_racing_preflight
        try:
            repository.create_user(telegram_id=765432, is_verified=True)
        except ValueError as exc:
            assert "already exists" in str(exc)
        else:
            raise AssertionError("concurrent duplicate must not create a second account")

        session.expire_all()
        assert session.query(database.models.User).filter_by(telegram_id=765432).count() == 1
        assert session.query(database.models.UserSettings).filter_by(user_id=existing.id).count() == 1
    finally:
        session.close()
        engine.dispose()
