import pytest
from fastapi import HTTPException

from web.api import mt5


def test_endpoint_requires_exact_operator_allowlist(monkeypatch):
    monkeypatch.setattr(mt5.settings, "METADOCKER_ALLOWED_HOSTS", "engine.example.com,10.20.0.5", raising=False)
    monkeypatch.setattr(mt5.settings, "METADOCKER_REQUIRE_HTTPS", True, raising=False)

    mt5._validate_engine_endpoint("https://engine.example.com:8443")
    mt5._validate_engine_endpoint("https://10.20.0.5")

    for endpoint in (
        "https://169.254.169.254/latest/meta-data",
        "https://127.0.0.1:2375",
        "https://unlisted.internal",
        "https://attacker.example.com",
    ):
        with pytest.raises(HTTPException) as exc:
            mt5._validate_engine_endpoint(endpoint)
        assert exc.value.status_code == 422


def test_endpoint_rejects_embedded_credentials_query_and_http(monkeypatch):
    monkeypatch.setattr(mt5.settings, "METADOCKER_ALLOWED_HOSTS", "engine.example.com", raising=False)
    monkeypatch.setattr(mt5.settings, "METADOCKER_REQUIRE_HTTPS", True, raising=False)

    for endpoint in (
        "https://user:password@engine.example.com",
        "https://engine.example.com?next=http://127.0.0.1",
        "https://engine.example.com#fragment",
        "http://engine.example.com",
    ):
        with pytest.raises(HTTPException):
            mt5._validate_engine_endpoint(endpoint)
