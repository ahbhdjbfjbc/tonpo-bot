import io
import logging
from pathlib import Path

from utils.log_redaction import REDACTED, install_secret_redaction

ROOT = Path(__file__).parents[1]


def test_secrets_are_redacted_from_messages_and_tracebacks():
    token = "123456789:AAExampleSecretTokenValue"
    stream = io.StringIO()
    logger = logging.getLogger("tonpo.redaction.test")
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.handlers = [handler]
    install_secret_redaction([token], logger)

    logger.error("url=https://api.telegram.org/bot%s/getMe", token)
    try:
        raise RuntimeError(f"The token `{token}` was rejected by the server.")
    except RuntimeError:
        logger.exception("boom")

    output = stream.getvalue()
    assert token not in output
    assert output.count(REDACTED) >= 2


def test_short_values_are_not_treated_as_secrets():
    stream = io.StringIO()
    logger = logging.getLogger("tonpo.redaction.short")
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    logger.handlers = [handler]
    install_secret_redaction(["true", ""], logger)
    logger.warning("dry_run=true")
    assert "dry_run=true" in stream.getvalue()


def test_webhook_secret_is_stable_and_telegram_compatible():
    from bot.main import telegram_webhook_secret

    secret = telegram_webhook_secret("123456:ABC")
    assert secret == telegram_webhook_secret("123456:ABC")
    assert secret != telegram_webhook_secret("123456:XYZ")
    assert 1 <= len(secret) <= 256 and secret.isalnum()
    assert "123456:ABC" not in secret


def test_docker_image_excludes_env_and_runs_unprivileged():
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    assert ".env" in ignore and ".git" in ignore
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "\nUSER tonpo\n" in dockerfile
