"""Static checks for the unauthenticated Explore surface."""
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP_JS = (ROOT / "web/static/js/app.js").read_text()
INDEX = (ROOT / "web/static/index.html").read_text()


def test_explore_renders_public_previews_for_main_sections():
    for page in (
        "signals", "trades", "results", "analytics", "protection", "mt5",
        "account", "risk", "news", "subscription", "tradingview",
        "trading_mode", "settings", "support",
    ):
        assert f"{page}: [" in APP_JS
    assert "بيانات تجريبية — ليست بيانات تداول حقيقية" in APP_JS
    assert "وضع الاستكشاف" in APP_JS


def test_explore_bootstrap_does_not_force_login_without_token():
    assert "enterGuestMode('مرحبًا بك في وضع الاستكشاف" in APP_JS
    assert "api('/api/public/overview')" in APP_JS
    assert 'id="login-screen" class="hidden' in INDEX


def test_explore_does_not_create_user_data_or_disable_backend_auth():
    assert '"user": None' in (ROOT / "web/api/public.py").read_text()
    assert "get_current_user" not in (ROOT / "web/api/public.py").read_text()
    assert "get_current_user" in (ROOT / "web/api/dashboard.py").read_text()
    assert "api('/api/dashboard')" in APP_JS
