import asyncio
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database.database import Base
from database.models import EngineInstance, SubscriptionPlan
from database.repositories import UserRepository
from web.api import mt5
from web.schemas import EngineInstanceIn


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


class _HealthyEngine:
    def __init__(self, *_args, **_kwargs):
        pass

    async def health(self):
        return {"status": "ok"}

    async def close(self):
        return None


def test_bind_engine_enforces_persisted_plan_limit(monkeypatch):
    engine, db = _db()
    try:
        user = UserRepository(db).create_user(
            telegram_id=990001, is_active=True, is_verified=True,
            subscription_tier="free", subscription_expiry=datetime.utcnow() + timedelta(days=30),
            subscription_features={"max_connections": 1},
        )
        db.add(EngineInstance(
            user_id=user.id, engine_instance_id="engine-existing", provider="metadocker",
            endpoint="https://engine.example.com", account_reference="account-existing",
            api_key_ciphertext="encrypted-test-key", status="online",
            provision_status="active", is_active=True,
        ))
        db.commit()
        monkeypatch.setattr(mt5, "_validate_engine_endpoint", lambda _endpoint: None)
        monkeypatch.setattr(mt5, "MetaDockerConnectionAdapter", _HealthyEngine)
        monkeypatch.setattr(mt5, "encrypt_gateway_api_key", lambda value: "encrypted:" + value)
        payload = EngineInstanceIn(
            engine_instance_id="engine-new", endpoint="https://engine.example.com",
            account_reference="account-new", api_key="x" * 24,
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(mt5.bind_engine(payload, user, db))
        assert exc.value.status_code == 403
        assert db.query(EngineInstance).filter_by(engine_instance_id="engine-new").count() == 0
    finally:
        db.close()
        engine.dispose()
