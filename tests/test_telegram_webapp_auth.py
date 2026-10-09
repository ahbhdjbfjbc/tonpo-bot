"""Focused Telegram Mini App authentication tests; no network or broker access."""

import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException

from config.settings import settings
from services.auth import AuthService
from web.api import auth as auth_api
from web.schemas import TelegramWebAppLoginRequest


TEST_BOT_TOKEN = "123456:test-only-token"


def init_data(telegram_id=12345, *, auth_date=None, bot_token=TEST_BOT_TOKEN):
    timestamp = auth_date or int(datetime.now(timezone.utc).timestamp())
    values = {
        "auth_date": str(timestamp),
        "query_id": "test-query",
        "user": json.dumps({"id": telegram_id, "first_name": "Test"}, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def verifier(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", TEST_BOT_TOKEN, raising=False)
    service = AuthService.__new__(AuthService)
    return service


def test_valid_init_data_is_verified(monkeypatch):
    service = verifier(monkeypatch)
    now = int(datetime.now(timezone.utc).timestamp())
    result = service.verify_telegram_webapp_init_data(init_data(auth_date=now), now=now)
    assert result["telegram_id"] == 12345


def test_invalid_hash_is_rejected(monkeypatch):
    service = verifier(monkeypatch)
    value = init_data()
    assert service.verify_telegram_webapp_init_data(value.replace("hash=", "hash=0")) is None


def test_expired_init_data_is_rejected(monkeypatch):
    service = verifier(monkeypatch)
    now = 2_000_000_000
    assert service.verify_telegram_webapp_init_data(
        init_data(auth_date=now - 86401), now=now
    ) is None


def test_missing_init_data_is_rejected(monkeypatch):
    service = verifier(monkeypatch)
    assert service.verify_telegram_webapp_init_data("") is None


def test_webapp_login_resolves_existing_registered_user(monkeypatch):
    monkeypatch.setattr(settings, "JWT_EXPIRY_HOURS", 24, raising=False)
    user = SimpleNamespace(
        id=7, telegram_id=12345, telegram_username="existing", first_name="Test",
        subscription_tier="pro", is_verified=True, is_active=True, is_banned=False,
        has_gateway_credentials=False, win_rate=0.0, language="en",
    )

    class Repo:
        def __init__(self, db):
            pass

        def get_by_telegram_id(self, telegram_id):
            return user if telegram_id == user.telegram_id else None

    class Auth:
        def verify_telegram_webapp_init_data(self, value, **kwargs):
            return {"telegram_id": user.telegram_id}

        def generate_jwt(self, user_id, expires_delta):
            assert user_id == user.id
            return "test-session-token"

    monkeypatch.setattr(auth_api, "UserRepository", Repo)
    result = auth_api.telegram_webapp_login(
        TelegramWebAppLoginRequest(init_data="signed-init-data"), object(), Auth()
    )
    assert result.access_token == "test-session-token"
    assert result.user["telegram_id"] == user.telegram_id


@pytest.mark.parametrize("user", [
    None,
    SimpleNamespace(
        id=8, telegram_id=12345, telegram_username="inactive", first_name="Test",
        subscription_tier="free", is_verified=True, is_active=False, is_banned=False,
        has_gateway_credentials=False, win_rate=0.0, language="en",
    ),
    SimpleNamespace(
        id=9, telegram_id=12345, telegram_username="blocked", first_name="Test",
        subscription_tier="free", is_verified=True, is_active=True, is_banned=True,
        has_gateway_credentials=False, win_rate=0.0, language="en",
    ),
])
def test_webapp_login_rejects_unknown_inactive_or_blocked(monkeypatch, user):
    monkeypatch.setattr(settings, "JWT_EXPIRY_HOURS", 24, raising=False)

    class Repo:
        def __init__(self, db):
            pass

        def get_by_telegram_id(self, telegram_id):
            return user

    class Auth:
        def verify_telegram_webapp_init_data(self, value, **kwargs):
            return {"telegram_id": 12345}

    monkeypatch.setattr(auth_api, "UserRepository", Repo)
    with pytest.raises(HTTPException) as error:
        auth_api.telegram_webapp_login(
            TelegramWebAppLoginRequest(init_data="signed-init-data"), object(), Auth()
        )
    assert error.value.status_code == 403


def test_webapp_login_rejects_unverified_user(monkeypatch):
    user = SimpleNamespace(
        id=10, telegram_id=12345, is_verified=False, is_active=True, is_banned=False,
    )

    class Repo:
        def __init__(self, db):
            pass

        def get_by_telegram_id(self, telegram_id):
            return user

    class Auth:
        def verify_telegram_webapp_init_data(self, value, **kwargs):
            return {"telegram_id": 12345}

    monkeypatch.setattr(auth_api, "UserRepository", Repo)
    with pytest.raises(HTTPException) as error:
        auth_api.telegram_webapp_login(
            TelegramWebAppLoginRequest(init_data="signed-init-data"), object(), Auth()
        )
    assert error.value.status_code == 403


def test_frontend_does_not_contain_server_secrets():
    from pathlib import Path

    content = (Path(__file__).parents[1] / "web/static/js/app.js").read_text()
    assert "BOT_TOKEN" not in content
    assert "JWT_SECRET" not in content
    assert "ENCRYPTION_KEY" not in content
