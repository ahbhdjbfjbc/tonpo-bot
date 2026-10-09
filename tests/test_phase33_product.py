"""PHASE 33 premium UX and safety contract tests."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "web/static/js/app.js"
HTML = ROOT / "web/static/index.html"
CSS = ROOT / "web/static/css/app.css"


def test_premium_navigation_has_real_page_handlers():
    html = HTML.read_text()
    js = JS.read_text()
    for page in ("news", "subscription", "account", "tradingview"):
        assert f'data-page="{page}"' in html
        assert f"page === '{page}'" in js or (page == "account" and "page === 'mt5' || page === 'account'" in js)


def test_dashboard_uses_authoritative_states_and_no_fake_performance_copy():
    js = JS.read_text()
    assert "Automated Trading Protection &amp; Execution" in js
    assert "Trading Engine" in js and "News Protection" in js and "DRY RUN" in js


def test_frontend_has_safe_errors_and_no_direct_execution_route():
    js = JS.read_text()
    assert "The service could not complete this request." in js
    assert "/api/trades/execute" not in js
    assert "/api/signals/execute" not in js
    assert "Authorization" in js


def test_all_runtime_renderers_share_the_authenticated_api_scope():
    js = JS.read_text()
    for endpoint in ("/api/dashboard", "/api/news/status", "/api/results", "/api/mt5/status", "/api/signals"):
        assert endpoint in js
    assert "token" in js and "Bearer" in js
    assert js.rstrip().endswith("})();")


def test_mobile_premium_layout_contract_exists():
    css = CSS.read_text()
    assert ".premium-status-grid" in css
    assert "@media (max-width:640px)" in css
    assert ".table-wrap" in css and "overflow-x: auto" in css


def test_dry_run_is_not_presented_as_live_in_product_copy():
    html = HTML.read_text()
    js = JS.read_text()
    assert "TRADING_DRY_RUN=true" in (ROOT / ".env.example").read_text()
    assert "DRY RUN — لا أوامر حقيقية" in js
    assert "LIVE TRADING" not in html
