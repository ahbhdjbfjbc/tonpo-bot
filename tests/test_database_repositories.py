import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.database import Base
import database.models  # register mapped tables on Base
from database.repositories import UserRepository, TradeRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_user_repository_create_read_update_delete(session):
    repo = UserRepository(session)
    credentials = {"mt5_account_id": "123456", "mt5_server": "Demo"}
    user = repo.create_user(telegram_id=778899, telegram_username="tester", **credentials)
    assert repo.get_by_telegram_id(778899).id == user.id
    assert user.mt5_password is None
    assert repo.update_user(778899, telegram_username="updated").telegram_username == "updated"
    assert repo.delete_user(778899)
    assert repo.get_by_telegram_id(778899).is_active is False


def test_trade_repository_persists_and_finds_signal(session):
    user = UserRepository(session).create_user(
        telegram_id=778900, telegram_username="trader",
    )
    repo = TradeRepository(session)
    trade = repo.create_trade(
        user.id, symbol="EURUSD", order_type="Buy", status="pending", signal_hash="abc",
        entry_price=1.1, stop_loss=1.09, take_profits=[1.12], position_size=0.1,
        risk_percentage=1.0, risk_amount=10, potential_reward=20, signal_text="BUY EURUSD",
    )
    assert repo.get_by_uuid(trade.uuid).symbol == "EURUSD"
    assert repo.check_duplicate("abc", user.id)
