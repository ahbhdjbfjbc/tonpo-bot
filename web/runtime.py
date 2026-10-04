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


def get_signal_pipeline(db: Session) -> SignalPipeline:
    """
    Return a SignalPipeline bound to the given DB session.
    Prefer the bot-wired instance when available; otherwise construct one
    with a TradeExecutor (respects TRADING_DRY_RUN).
    """
    global _pipeline, _executor
    if _pipeline is not None and getattr(_pipeline, "db", None) is db:
        return _pipeline

    if _executor is None:
        _executor = TradeExecutor(db, bot=None, execution_provider=_execution_provider)
    else:
        if hasattr(_executor, "db"):
            _executor.db = db

    return SignalPipeline(db, _executor)


async def get_gateway_connection(user) -> Any:
    """
    Attempt to obtain a live Tonpo connection for the user.
    Returns None when gateway is not wired or credentials missing.
    Never invents account data.
    """
    if _execution_provider is None:
        return None
    if not getattr(user, "has_gateway_credentials", False):
        return None
    try:
        return await _execution_provider.get_connection(user.telegram_id)
    except Exception as exc:
        logger.info("Gateway connection unavailable for user %s: %s", user.id, exc)
        return None
