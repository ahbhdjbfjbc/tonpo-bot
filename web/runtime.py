"""Runtime wiring: shared pipeline / executor / gateway for web process."""
from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy.orm import Session

from services.signal_pipeline import SignalPipeline
from services.trade_executor import TradeExecutor

logger = logging.getLogger(__name__)

_pipeline: Optional[SignalPipeline] = None
_executor: Optional[TradeExecutor] = None
_execution_provider: Any = None


def set_runtime(
    pipeline: Optional[SignalPipeline] = None,
    executor: Optional[TradeExecutor] = None,
    execution_provider: Any = None,
) -> None:
    global _pipeline, _executor, _execution_provider
    if pipeline is not None:
        _pipeline = pipeline
    if executor is not None:
        _executor = executor
    if execution_provider is not None:
        _execution_provider = execution_provider


async def initialize_web_execution_provider() -> Any:
    """Create the execution provider in the web process itself.

    The bot and ``web.run`` are separate processes, so the bot's in-memory
    runtime wiring cannot be relied upon by the webhook process.  In dry-run
    mode the provider is intentionally not connected to the external gateway.
    """
    global _execution_provider
    if _execution_provider is not None:
        return _execution_provider

    from config.settings import settings
    from gateway_client import ExecutionProvider, MetaDockerExecutionProvider

    if str(getattr(settings, "ENGINE_PROVIDER", "tonpo")).lower() == "metadocker":
        from database.database import db_manager

        provider = MetaDockerExecutionProvider(
            db_manager.get_session,
            timeout=float(getattr(settings, "METADOCKER_REQUEST_TIMEOUT", 15.0)),
        )
    else:
        provider = ExecutionProvider(use_gateway=bool(getattr(settings, "USE_GATEWAY", True)))
    set_runtime(execution_provider=provider)
    if not bool(getattr(settings, "TRADING_DRY_RUN", True)) and hasattr(provider, "initialize"):
        await provider.initialize(settings.gateway_config)
    return provider


async def shutdown_web_execution_provider() -> None:
    """Release the provider owned by the web process, if it was initialized."""
    global _execution_provider
    provider = _execution_provider
    _execution_provider = None
    if provider is not None:
        await provider.shutdown()


def get_signal_pipeline(db: Session) -> SignalPipeline:
    """
    Return a SignalPipeline bound to the given DB session.
    Prefer the bot-wired instance when available; otherwise construct one
    with a TradeExecutor (respects TRADING_DRY_RUN).
    """
    global _pipeline, _executor
    if _pipeline is not None and getattr(_pipeline, "db", None) is db:
        return _pipeline

    # A FastAPI request owns its SQLAlchemy session. Do not retarget an
    # executor's ``db`` attribute in place: its repositories/services retain
    # the session they were constructed with. Rebuild the existing executor
    # for a new request session while preserving the configured provider.
    if _executor is None or getattr(_executor, "db", None) is not db:
        bot = getattr(_executor, "bot", None) if _executor is not None else None
        provider = getattr(_executor, "execution_provider", _execution_provider) if _executor is not None else _execution_provider
        _executor = TradeExecutor(db, bot=bot, execution_provider=provider)

    return SignalPipeline(db, _executor)


async def get_gateway_connection(user) -> Any:
    """
    Attempt to obtain a live Tonpo connection for the user.
    Returns None when gateway is not wired or credentials missing.
    Never invents account data.
    """
    from config.settings import settings

    if bool(getattr(settings, "TRADING_DRY_RUN", True)):
        return None
    if _execution_provider is None:
        return None
    provider_name = getattr(_execution_provider, "provider_name", "tonpo")
    if provider_name != "metadocker" and not getattr(user, "has_gateway_credentials", False):
        return None
    try:
        return await _execution_provider.get_connection(user.telegram_id)
    except Exception as exc:
        logger.info("Gateway connection unavailable for user %s (%s)", user.id, type(exc).__name__)
        return None
