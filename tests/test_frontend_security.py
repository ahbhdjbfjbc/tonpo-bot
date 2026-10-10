import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


APP_JS = Path(__file__).parents[1] / "web" / "static" / "js" / "app.js"


def test_frontend_escape_html_encodes_all_html_significant_characters():
    source = APP_JS.read_text()
    start = source.index("  function escapeHtml(value) {")
    end = source.index("\n  }", start) + len("\n  }")
    function_source = source[start:end]
    payload = "<img src=x onerror=alert('x')> & \"quoted\""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    result = subprocess.run(
        [node, "-e", function_source + "; process.stdout.write(escapeHtml(" + json.dumps(payload) + "));"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == "&lt;img src=x onerror=alert(&#39;x&#39;)&gt; &amp; &quot;quoted&quot;"


def test_websocket_client_does_not_put_bearer_token_in_url():
    source = APP_JS.read_text()
    assert "/ws?token=" not in source
    assert "_ws.send(JSON.stringify({ type: 'auth', token }))" in source
    assert "sessionStorage.setItem('tonpo_token', token)" in source
    assert "localStorage.setItem('tonpo_token', token)" not in source


def test_signal_and_trade_rows_use_validated_dom_handlers_not_inline_javascript():
    source = APP_JS.read_text()
    assert "onclick=\"location.hash='signal/${s.id}'\"" not in source
    assert "onclick=\"location.hash='trade/${t.id}'\"" not in source
    assert "if (/^\\d+$/.test(id)) location.hash = `signal/${id}`" in source
    assert "if (/^\\d+$/.test(id)) location.hash = `trade/${id}`" in source
    assert "${(s.signal_text || '').replace(/</g,'&lt;')}" not in source


def test_frontend_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is unavailable")
    subprocess.run([node, "--check", str(APP_JS)], check=True, capture_output=True, text=True)


def test_spa_has_no_inline_script_and_loads_local_tailwind_config():
    html = (APP_JS.parents[1] / "index.html").read_text()
    assert "<script>" not in html
    assert '/static/js/tailwind-config.js' in html
    assert (APP_JS.parent / "tailwind-config.js").is_file()
