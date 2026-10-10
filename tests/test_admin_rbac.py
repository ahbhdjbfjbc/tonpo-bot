from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from web import deps
from web.api.auth import _is_admin


def test_admin_user_id_is_authorized(monkeypatch):
    user = SimpleNamespace(telegram_id=7001)
    monkeypatch.setattr(deps.settings, "ADMIN_USER_IDS", [7001], raising=False)

    assert deps.require_admin(user=user) is user
    assert _is_admin(user) is True


def test_database_role_is_denied_until_explicit_mapping(monkeypatch):
    user = SimpleNamespace(telegram_id=7002)
    monkeypatch.setattr(deps.settings, "ADMIN_USER_IDS", [], raising=False)

    with pytest.raises(HTTPException) as exc:
        deps.require_admin(user=user)

    assert exc.value.status_code == 403
    assert _is_admin(user, db=object()) is False


def test_adminrole_is_ignored_by_telegram_and_payment_gates(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database.database import Base
    import database.models
    from database.models import AdminRole
    from bot.admin import AdminHandler
    from services.payment import PaymentService

    monkeypatch.setattr(deps.settings, "ADMIN_USER_IDS", [], raising=False)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        db.add(AdminRole(telegram_id=7003, role="SUPER_ADMIN", permissions=["*"]))
        db.commit()

        handler = AdminHandler(db, None)
        assert handler.role_for(7003) == ""
        assert handler.has_permission(7003, "users.manage") is False
        assert PaymentService(db)._admin_role(7003) is None
    finally:
        db.close()
        engine.dispose()


def test_telegram_wrap_admin_denies_database_role_without_allowlist(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from bot.middleware import AuthMiddleware

    monkeypatch.setattr(deps.settings, "ADMIN_USER_IDS", [], raising=False)
    called = []
    denied_messages = []

    class NoRoleLookup:
        def query(self, *_args, **_kwargs):
            raise AssertionError("admin authorization must not consult database roles")

        def rollback(self):
            raise AssertionError("role database must not be touched")

    async def privileged_handler(update, context):
        called.append(True)

    async def reply(message):
        denied_messages.append(message)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=7004),
        effective_message=SimpleNamespace(reply_text=reply),
        callback_query=None,
    )
    asyncio.run(AuthMiddleware(NoRoleLookup()).wrap_admin(privileged_handler)(update, None))

    assert not called
    assert denied_messages
