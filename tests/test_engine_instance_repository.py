from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.database import Base
from database.models import EngineInstance, User
from database.repositories import EngineInstanceRepository


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_engine_binding_is_owned_by_one_user_and_can_be_disabled():
    db = _session()
    try:
        first = User(telegram_id=1001)
        second = User(telegram_id=1002)
        db.add_all([first, second])
        db.commit()

        repo = EngineInstanceRepository(db)
        row = repo.upsert_for_user(
            first.id,
            engine_instance_id="bridge-a",
            endpoint="http://bridge-a:8001",
            account_reference="demo-1",
            api_key_ciphertext="fernet:v1:encrypted",
            engine_version="v1.0.1",
        )
        assert row.user_id == first.id
        assert repo.get_active_for_telegram_id(1001).engine_instance_id == "bridge-a"
        assert repo.get_active_for_telegram_id(1002) is None

        try:
            repo.upsert_for_user(
                second.id,
                engine_instance_id="bridge-a",
                endpoint="http://bridge-a:8001",
                account_reference="demo-2",
                api_key_ciphertext="fernet:v1:encrypted",
            )
        except ValueError as exc:
            assert "another user" in str(exc)
        else:
            raise AssertionError("cross-user engine ownership was accepted")

        assert repo.disable_for_user(first.id, "bridge-a") is True
        assert repo.get_active_for_telegram_id(1001) is None
        assert db.query(EngineInstance).filter_by(engine_instance_id="bridge-a").one().is_active is False
    finally:
        db.close()
