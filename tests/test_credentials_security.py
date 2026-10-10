import pytest
from cryptography.fernet import Fernet

from config.settings import settings
from services.auth import (
    EncryptionService,
    decrypt_gateway_api_key,
    encrypt_gateway_api_key,
)


def test_encryption_fails_closed_when_key_is_missing(monkeypatch):
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', None, raising=False)

    with pytest.raises(RuntimeError, match='ENCRYPTION_KEY must be configured'):
        EncryptionService()


def test_encryption_fails_closed_when_key_is_invalid(monkeypatch):
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', 'invalid-test-key', raising=False)

    with pytest.raises(RuntimeError, match='ENCRYPTION_KEY is invalid'):
        EncryptionService()


def test_encryption_round_trip_with_test_only_key(monkeypatch):
    test_key = Fernet.generate_key().decode('ascii')
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', test_key, raising=False)
    service = EncryptionService()

    encrypted = service.encrypt('dummy-test-password')

    assert encrypted != 'dummy-test-password'
    assert service.decrypt(encrypted) == 'dummy-test-password'


def test_auth_service_defers_encryption_until_needed(monkeypatch):
    from services.auth import AuthService

    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', None, raising=False)
    monkeypatch.setattr(settings, 'JWT_SECRET', 'dummy-test-jwt-secret-long-enough-123', raising=False)
    service = AuthService(object())

    assert service.encryption is None


def test_gateway_api_key_is_encrypted_and_legacy_plaintext_fails_closed(monkeypatch):
    test_key = Fernet.generate_key().decode('ascii')
    monkeypatch.setattr(settings, 'ENCRYPTION_KEY', test_key, raising=False)

    stored = encrypt_gateway_api_key('dummy-test-gateway-key')
    assert stored.startswith('fernet:v1:')
    assert 'dummy-test-gateway-key' not in stored
    assert decrypt_gateway_api_key(stored) == 'dummy-test-gateway-key'

    with pytest.raises(RuntimeError, match='not encrypted'):
        decrypt_gateway_api_key('legacy-plaintext-key')


def test_gateway_registration_error_details_are_redacted(caplog):
    import asyncio
    from gateway_client.adapter import ExecutionProvider

    class FailingGateway:
        async def register_user(self, *args):
            raise RuntimeError('dummy-test-credential-value')

    provider = ExecutionProvider.__new__(ExecutionProvider)
    provider.gateway_manager = FailingGateway()
    result = asyncio.run(provider.register_user(123, 'test-account', 'dummy-password', 'test-server'))

    assert result == (False, 'Gateway registration failed', {})
    assert 'dummy-test-credential-value' not in caplog.text
    assert 'dummy-password' not in caplog.text


def test_public_user_response_omits_stored_credentials():
    from types import SimpleNamespace
    from web.api.auth import _user_public

    user = SimpleNamespace(
        id=1,
        telegram_id=123,
        telegram_username='test_user',
        first_name='Test',
        subscription_tier='free',
        is_verified=False,
        has_gateway_credentials=True,
        win_rate=0.0,
        language='en',
        gateway_api_key='dummy-test-api-key',
        mt5_password='dummy-test-password',
    )

    response = _user_public(user)

    assert 'gateway_api_key' not in response
    assert 'mt5_password' not in response
    assert 'dummy-test-api-key' not in repr(response)
    assert 'dummy-test-password' not in repr(response)


def test_registration_password_stays_out_of_persistent_user_data():
    import asyncio
    from types import SimpleNamespace
    from bot.registration import ENTER_SERVER, RegistrationHandler

    handler = RegistrationHandler.__new__(RegistrationHandler)
    handler._pending_passwords = {}
    context = SimpleNamespace(user_data={})
    replies = []

    class Message:
        text = 'dummy-test-password'

        async def reply_text(self, message, **kwargs):
            replies.append(message)

    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=17),
        message=Message(),
    )
    result = asyncio.run(handler.receive_password(update, context))

    assert result == ENTER_SERVER
    assert 'mt5_password' not in context.user_data
    assert handler._pending_passwords[17][0] == 'dummy-test-password'
    assert isinstance(handler._pending_passwords[17][1], float)
    assert replies


def test_registration_password_is_purged_after_ttl(monkeypatch):
    from bot import registration
    from bot.registration import RegistrationHandler

    handler = RegistrationHandler.__new__(RegistrationHandler)
    handler._pending_passwords = {17: ('expired-test-password', 100.0), 18: ('fresh-test-password', 200.0)}
    monkeypatch.setattr(registration.settings, 'REGISTRATION_PASSWORD_TTL_SECONDS', 300, raising=False)
    monkeypatch.setattr(registration.time, 'monotonic', lambda: 401.0)

    assert handler.purge_expired_pending_passwords() == 1
    assert 17 not in handler._pending_passwords
    assert handler._get_pending_password(18) == 'fresh-test-password'


def test_database_user_data_persistence_filters_secret_fields(monkeypatch):
    import asyncio
    from database import db_persistence

    saved = {}
    monkeypatch.setattr(db_persistence, '_load', lambda key: None)
    monkeypatch.setattr(db_persistence, '_save', lambda key, value: saved.update({key: value}))
    persistence = db_persistence.DBPersistence()
    user_data = {
        'language': 'en',
        'mt5_password': 'dummy-test-password',
        'gateway_api_key': 'dummy-test-api-key',
        'nested': {'access_token': 'dummy-test-token', 'theme': 'dark'},
    }

    asyncio.run(persistence.update_user_data(17, user_data))
    restored = asyncio.run(persistence.get_user_data())

    assert restored == {17: {'language': 'en', 'nested': {'theme': 'dark'}}}
    assert saved[db_persistence._USER_KEY] == restored
    assert 'dummy-test-password' not in repr(saved)
    assert 'dummy-test-api-key' not in repr(saved)
    assert 'dummy-test-token' not in repr(saved)


def test_database_query_retry_does_not_log_exception_contents(caplog):
    import logging
    import pytest

    from database.repositories import BaseRepository

    class SessionStub:
        def rollback(self):
            pass

    def fail_query():
        raise RuntimeError("placeholder-credential-error")

    repository = BaseRepository(SessionStub())
    with caplog.at_level(logging.ERROR, logger="database.repositories"):
        with pytest.raises(RuntimeError):
            repository._safe_query(fail_query)

    assert "RuntimeError" in caplog.text
    assert "placeholder-credential-error" not in caplog.text


def test_jwt_secret_is_not_an_admin_api_bootstrap(monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from web.api.auth import login
    from web.schemas import LoginRequest

    class Query:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return SimpleNamespace(
                id=1,
                telegram_id=123,
                is_active=True,
                is_banned=False,
            )

    class DbStub:
        def query(self, model):
            return Query()

    class AuthStub:
        def validate_api_key(self, api_key):
            return None

    monkeypatch.setattr(settings, 'JWT_SECRET', 'dummy-test-jwt-secret-long-enough-123', raising=False)
    monkeypatch.setattr(settings, 'ADMIN_API_KEY', None, raising=False)
    monkeypatch.setattr(settings, 'ADMIN_USER_IDS', [123], raising=False)

    with pytest.raises(HTTPException) as error:
        login(
            LoginRequest(telegram_id=123, api_key=settings.JWT_SECRET),
            db=DbStub(),
            auth=AuthStub(),
        )

    assert error.value.status_code == 401
