from pathlib import Path

import pytest

from config.webhook import require_webhook_url, validate_webhook_url


def test_webhook_requires_https_and_rejects_query_or_credentials():
    assert validate_webhook_url("https://hooks.example.test/telegram/") == "https://hooks.example.test/telegram"
    for url in (
        "http://hooks.example.test/webhook",
        "https://user:password@hooks.example.test/webhook",
        "https://hooks.example.test/webhook?token=secret",
        "https://hooks.example.test/webhook#fragment",
    ):
        with pytest.raises(ValueError):
            validate_webhook_url(url)


def test_enabling_webhook_without_url_fails_closed():
    with pytest.raises(ValueError, match="WEBHOOK_URL is required"):
        require_webhook_url(True, None)


def test_readme_documents_the_actual_webhook_setting_name():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    assert "`USE_WEBHOOK`" in readme
    assert "`WEBHOOK_MODE`" not in readme
