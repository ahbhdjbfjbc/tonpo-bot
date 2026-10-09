"""Guest access and public Mini App surface tests."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from web.api import public as public_api
from web.deps import get_current_user


def test_public_catalog_is_read_only_and_contains_only_public_plan_data(monkeypatch):
    class Catalog:
        def __init__(self, db):
            assert db == "db"

        def public_plan_catalog(self):
            return [{"tier": "free", "name": "Free", "price_monthly": 0.0}]

    monkeypatch.setattr(public_api, "SubscriptionService", Catalog)
    result = public_api.public_catalog("db")
    assert result["plans"][0]["tier"] == "free"
    assert "users" not in result
    assert "trades" not in result
    assert "credentials" not in result


def test_public_overview_feeds_original_dashboard_without_user_data(monkeypatch):
    class Catalog:
        def __init__(self, db):
            assert db == "db"

        def public_plan_catalog(self):
            return [{"tier": "free", "name": "Free"}]

    monkeypatch.setattr(public_api, "SubscriptionService", Catalog)
    result = public_api.public_overview("db")
    assert result["public"] is True
    assert result["dry_run"] is True
    assert result["account"] == {"connected": False}
    assert result["recent_trades"] == []
    assert result["subscription"]["plans"][0]["tier"] == "free"


def test_guest_bootstrap_opens_public_surface_without_jwt_or_api_key():
    content = (Path(__file__).parents[1] / "web/static/js/app.js").read_text()
    assert "let guestMode = false" in content
    assert "function enterGuestMode" in content
    assert "api('/api/public/catalog')" in content
    assert "لا تحتاج API Key لفتح Mini App" in content
    assert "localStorage.removeItem('tonpo_token')" in content


def test_initial_html_is_guest_first_and_loads_current_bootstrap():
    content = (Path(__file__).parents[1] / "web/static/index.html").read_text()
    assert 'id="login-screen" class="hidden' in content
    assert '<div id="app" class="min-h-screen flex">' in content
    assert 'TONPO · GUEST MODE' in content
    assert '/static/js/app.js?v=guest-mode-1' in content
    assert content.index('telegram-web-app.js') < content.index('/static/js/app.js?v=guest-mode-1')


def test_protected_dependency_rejects_guest_without_credentials():
    with pytest.raises(HTTPException) as error:
        get_current_user(None, None, None)
    assert error.value.status_code == 401


def test_guest_surface_does_not_disable_server_side_authentication():
    deps = (Path(__file__).parents[1] / "web/deps.py").read_text()
    assert "def get_current_user" in deps
    assert "Authentication required" in deps
    assert "verify_jwt" in deps


def test_guest_uses_original_dashboard_and_keeps_navigation_available():
    content = (Path(__file__).parents[1] / "web/static/js/app.js").read_text()
    assert "if (page === 'dashboard') await renderDashboard(el, guestMessage);" in content
    assert "await renderGuestFeatureGate(el, page)" in content
    assert "if (guestMode && page !== 'dashboard') page = 'dashboard';" not in content
    assert "item.classList.toggle('hidden', guestMode" not in content
    assert "api('/api/public/overview')" in content


def test_assistant_allows_public_guidance_but_uses_optional_account_context():
    content = (Path(__file__).parents[1] / "web/api/assistant.py").read_text()
    assert "get_optional_user" in content
    assert "get_current_user" not in content
    client_js = (Path(__file__).parents[1] / "web/static/js/app.js").read_text()
    assert "if (!wrap || !token) return;" not in client_js
